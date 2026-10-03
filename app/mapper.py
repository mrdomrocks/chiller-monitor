"""Passive RS-485 capture, a live register map, recordings, and TCP replay.

Capture opens the serial port and only reads. Replay answers a Modbus TCP
client, including this app's plant page, from the captured responses.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import threading
import time
import uuid
from datetime import datetime, timezone

from app.decode import (
    MODICON_BASE,
    engineering_from_raw,
    format_value,
    register_count,
    string_registers,
    wire_address,
)
from app.modbus_serial import (
    AsciiAssembler,
    Conversation,
    RtuAssembler,
    bit_values,
    char_bits,
    parse_ascii,
    parse_rtu,
    register_values,
    request_address,
    request_count,
    rtu_gap,
    write_values,
)
from app.modbus_tcp import ModbusDevice, _frame, _read_frame
from app.paths import data_dir
from app.store import create_site, normalize_point, replace_map, update_site

BAUD_RATES = (1200, 2400, 4800, 9600, 19200, 38400, 57600, 115200)
AREAS = {1: "coil", 2: "discrete", 3: "holding", 4: "input"}
AREA_LETTER = {"coil": "c", "discrete": "d", "holding": "h", "input": "i"}
MAX_KEPT = 2000
_RECORDING_ID = re.compile(r"^[a-f0-9]{12}$")


def recordings_dir():
    return data_dir() / "mapper"


def list_serial_ports() -> list[dict]:
    try:
        from serial.tools import list_ports
    except ImportError:
        return []
    return [
        {"device": port.device, "description": port.description or port.device}
        for port in list_ports.comports()
    ]


def configure_listen_only(ser):
    """Open a port for reception and leave the driver in receive."""
    ser.rtscts = False
    ser.dsrdtr = False
    ser.timeout = 0.05
    if not getattr(ser, "is_open", False):
        ser.open()
    try:
        ser.rts = False
        ser.dtr = False
    except Exception:
        pass
    return ser


def _point_id(unit: int, function: str, address: int) -> str:
    return f"u{int(unit)}_{AREA_LETTER[function]}_{int(address)}"


def _display_address(function: str, wire: int, addressing: str) -> int:
    if addressing == "protocol":
        return int(wire)
    return MODICON_BASE[function] + int(wire)


def _new_point(unit: int, function: str, address: int, writable: bool) -> dict:
    point_id = _point_id(unit, function, address)
    coil = function in ("coil", "discrete")
    point = normalize_point(
        {
            "id": point_id,
            "name": f"{function.title()} {address}",
            "group": "Captured",
            "notes": "Observed on RS-485. Monitor mode did not transmit this request.",
            "function": function,
            "addressing": "protocol",
            "address_number": address,
            "dtype": "bool" if coil else "uint16",
            "widget": "status" if coil else ("setpoint" if writable else "value"),
            "writable": writable and function in ("holding", "coil"),
            "scale": 1,
            "offset": 0,
            "decimals": 0,
            "sort": address,
        }
    )
    point["device"] = int(unit)
    point["edited"] = False
    return point


class ReplaySlave(ModbusDevice):
    """Serves a captured image, preferring an exact captured response PDU."""

    def __init__(self, unit: int, exact: dict[bytes, bytes]):
        super().__init__(unit=unit, size=65536)
        self.exact = exact

    def handle(self, unit: int, pdu: bytes) -> bytes:
        if unit == self.unit and pdu in self.exact:
            response = self.exact[pdu]
            if pdu and pdu[0] in (5, 6, 16) and response and not (response[0] & 0x80):
                super().handle(unit, pdu)
            return response
        return super().handle(unit, pdu)


class Mapper:
    def __init__(self):
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._serial = None
        self._server: asyncio.Server | None = None
        self._conversation = Conversation()
        self.settings = {
            "mode": "rtu",
            "port": "",
            "baud": 9600,
            "parity": "N",
            "stopbits": 1,
            "bytesize": 8,
        }
        self.reset()

    def reset(self) -> None:
        with self._lock:
            self.capturing = False
            self.recording = False
            self.mapping = False
            self.replace = False
            self.detail = "Idle. Monitor mode listens and does not transmit."
            self.frames: list[dict] = []
            self.noise = 0
            self.image: dict[int, dict[str, dict[int, int | bool]]] = {}
            self.points: dict[str, dict] = {}
            self.exact: dict[tuple[int, bytes], bytes] = {}
            self.exchanges: list[dict] = []
            self.replay_port: int | None = None
            self.replay_name = ""
            self._conversation.reset()

    def snapshot(self) -> dict:
        with self._lock:
            points = []
            for point in self._ordered_points():
                value, raw = self._reading(point)
                shown = dict(point)
                shown["value"] = value
                shown["display"] = format_value(point, value) if value is not None else "—"
                shown["raw"] = raw
                points.append(shown)
            units = sorted(
                {point["device"] for point in points}
                | {int(item["unit"]) for item in self.exchanges}
            )
            return {
                "capturing": self.capturing,
                "recording": self.recording,
                "mapping": self.mapping,
                "replace": self.replace,
                "replaying": self._server is not None,
                "replay_port": self.replay_port,
                "replay_name": self.replay_name,
                "detail": self.detail,
                "settings": dict(self.settings),
                "ports": list_serial_ports(),
                "baud_rates": list(BAUD_RATES),
                "noise": self.noise,
                "exchange_count": len(self.exchanges),
                "frames": list(self.frames[-40:]),
                "points": points,
                "units": units,
                "recordings": self._recording_index(),
            }

    def update_settings(self, raw: dict) -> dict:
        mode = str(raw.get("mode", self.settings["mode"])).lower()
        if mode not in ("rtu", "ascii"):
            raise ValueError("Mode must be RTU or ASCII")
        baud = int(raw.get("baud", self.settings["baud"]))
        if baud not in BAUD_RATES:
            raise ValueError("Choose a standard baud rate")
        parity = str(raw.get("parity", self.settings["parity"])).upper()
        if parity not in ("N", "E", "O"):
            raise ValueError("Parity must be N, E, or O")
        stopbits = float(raw.get("stopbits", self.settings["stopbits"]))
        if stopbits not in (1, 2):
            raise ValueError("Stop bits must be 1 or 2")
        bytesize = int(raw.get("bytesize", 7 if mode == "ascii" else 8))
        if bytesize not in (7, 8):
            raise ValueError("Data bits must be 7 or 8")
        port = str(raw.get("port", self.settings["port"])).strip()
        if len(port) > 200 or any(ch in port for ch in "\n\r\x00"):
            raise ValueError("Choose a serial port")
        with self._lock:
            self.settings = {
                "mode": mode,
                "port": port,
                "baud": baud,
                "parity": parity,
                "stopbits": int(stopbits),
                "bytesize": bytesize,
            }
            if "mapping" in raw:
                self._set_mapping_locked(bool(raw["mapping"]))
            if "replace" in raw:
                self.replace = bool(raw["replace"])
        return self.snapshot()

    def _set_mapping_locked(self, enabled: bool) -> None:
        enabled = bool(enabled)
        turning_on = enabled and not self.mapping
        self.mapping = enabled
        port = self.settings["port"]
        if turning_on:
            for item in list(self.exchanges):
                response = bytes.fromhex(item["response"])
                self._apply_exchange(
                    {
                        "request": {"unit": int(item["unit"]), "pdu": bytes.fromhex(item["request"])},
                        "response": {
                            "pdu": response,
                            "exception": bool(response[:1] and response[0] & 0x80),
                        },
                    }
                )
        if self.capturing and port:
            state = "on" if enabled else "off"
            self.detail = f"Mapping is {state}. Listening on {port}. Nothing is transmitted."
        elif enabled:
            self.detail = "Mapping is on. Registers seen on the wire are added to the map."
        else:
            self.detail = "Mapping is off. The map is left as it is."

    def start_capture(self, raw: dict | None = None) -> dict:
        if raw:
            self.update_settings(raw)
        if self.capturing:
            raise RuntimeError("Already listening")
        port = self.settings["port"]
        if not port:
            raise ValueError("Choose the USB to RS-485 adapter")
        try:
            import serial
        except ImportError as exc:
            raise RuntimeError("RS-485 capture needs pyserial. Install it with pip install pyserial.") from exc
        ser = serial.Serial()
        ser.port = port
        ser.baudrate = self.settings["baud"]
        ser.bytesize = self.settings["bytesize"]
        ser.parity = self.settings["parity"]
        ser.stopbits = self.settings["stopbits"]
        try:
            configure_listen_only(ser)
        except Exception as exc:
            raise RuntimeError(f"Cannot open {port} ({exc})") from exc
        gap = rtu_gap(self.settings["baud"], char_bits(self.settings["bytesize"], self.settings["parity"], self.settings["stopbits"]))
        if self.settings["mode"] == "rtu":
            ser.inter_byte_timeout = gap
        assembler = AsciiAssembler() if self.settings["mode"] == "ascii" else RtuAssembler(gap)
        self._stop.clear()
        self._serial = ser
        with self._lock:
            self.capturing = True
            self._conversation.reset()
            self.detail = f"Listening on {port}. Monitor mode does not transmit."
        self._thread = threading.Thread(
            target=self._listen,
            args=(ser, assembler, self.settings["mode"]),
            name="modbus-mapper",
            daemon=True,
        )
        self._thread.start()
        return self.snapshot()

    def stop_capture(self) -> dict:
        self._stop.set()
        serial = self._serial
        self._serial = None
        if serial is not None:
            try:
                serial.close()
            except Exception:
                pass
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=1)
        self._thread = None
        with self._lock:
            self.capturing = False
            if self.detail.startswith("Listening"):
                self.detail = "Monitor stopped. Nothing was transmitted."
        return self.snapshot()

    def observe_raw(self, raw: bytes, mode: str | None = None) -> None:
        chosen = mode or self.settings["mode"]
        parsed = parse_ascii(raw) if chosen == "ascii" else parse_rtu(raw)
        if parsed is None:
            return
        with self._lock:
            if not parsed.get("ok"):
                self.noise += 1
                return
            public = {
                "raw": parsed["raw"],
                "unit": parsed["unit"],
                "function": parsed["function"],
                "role": parsed["role"],
                "exception": parsed["exception"],
            }
            self.frames.append(public)
            del self.frames[:-MAX_KEPT]
            exchange = self._conversation.push(parsed)
            if exchange is None:
                return
            stored = {
                "unit": exchange["request"]["unit"],
                "request": exchange["request"]["pdu"].hex(),
                "response": exchange["response"]["pdu"].hex(),
            }
            self.exchanges.append(stored)
            del self.exchanges[:-MAX_KEPT]
            if self.mapping:
                self._apply_exchange(exchange)
            else:
                unit = int(exchange["request"]["unit"])
                self.exact[(unit, exchange["request"]["pdu"])] = exchange["response"]["pdu"]
            if self.recording:
                self.detail = f"Recording. {len(self.exchanges)} exchanges. Nothing is transmitted."

    def update_point(self, point_id: str, raw: dict) -> dict:
        with self._lock:
            current = self.points.get(point_id)
            if current is None:
                raise KeyError(point_id)
            wire = wire_address(current["function"], current["address_number"], current["addressing"])
            merged = {**current, **raw, "id": point_id, "function": current["function"]}
            addressing = merged.get("addressing") or current["addressing"]
            if addressing not in ("modicon", "protocol"):
                raise ValueError("Addressing must be modicon or protocol")
            merged["addressing"] = addressing
            merged["address_number"] = _display_address(current["function"], wire, addressing)
            normalised = normalize_point(merged)
            normalised["device"] = current["device"]
            normalised["edited"] = True
            self.points[point_id] = normalised
        return self.snapshot()

    def clear(self) -> dict:
        self.stop_capture()
        with self._lock:
            self.frames.clear()
            self.noise = 0
            self.image.clear()
            self.points.clear()
            self.exact.clear()
            self.exchanges.clear()
            self.recording = False
            self._conversation.reset()
            self.detail = "Cleared. Monitor mode listens and does not transmit."
        return self.snapshot()

    def set_recording(self, enabled: bool) -> dict:
        with self._lock:
            self.recording = bool(enabled)
            if self.recording:
                self.exchanges.clear()
                self.detail = "Recording. Exchanges from this point are kept. Nothing is transmitted."
            else:
                self.detail = f"Record paused. {len(self.exchanges)} exchanges kept."
        return self.snapshot()

    def save_recording(self, name: str) -> dict:
        title = str(name or "").strip() or datetime.now().strftime("Capture %H:%M:%S")
        if len(title) > 80:
            raise ValueError("Recording name must be 80 characters or less")
        with self._lock:
            if not self.exchanges and not self.points:
                raise ValueError("Nothing has been captured yet")
            document = self._document(title)
        self._write_recording(document)
        with self._lock:
            self.recording = False
            self.detail = f"Saved recording {title}."
        snap = self.snapshot()
        snap["saved_id"] = document["id"]
        return snap

    def import_recording(self, document: dict, replace: bool | None = None) -> dict:
        if not isinstance(document, dict):
            raise ValueError("A recording must be a JSON object")
        exchanges = document.get("exchanges") or []
        if not isinstance(exchanges, list):
            raise ValueError("Recording exchanges must be a list")
        title = str(document.get("name") or "Imported capture").strip()[:80] or "Imported capture"
        do_replace = self.replace if replace is None else bool(replace)
        if not do_replace:
            stored = _imported_document(document, title)
            self._write_recording(stored)
            with self._lock:
                self.replace = False
                self.detail = f"Saved recording {title}. Replace is off, so the current map was kept."
            snap = self.snapshot()
            snap["saved_id"] = stored["id"]
            return snap
        self.stop_capture()
        with self._lock:
            self.replace = True
            self._load_document(document, title)
            stored = self._document(title)
        self._write_recording(stored)
        with self._lock:
            self.detail = f"Loaded recording {title}. The current map was replaced."
        snap = self.snapshot()
        snap["saved_id"] = stored["id"]
        return snap

    def delete_recording(self, recording_id: str) -> dict:
        path = self._recording_path(recording_id)
        if path.exists():
            path.unlink()
        return self.snapshot()

    async def start_replay(self, recording_id: str | None, port: int) -> dict:
        source = self._source(recording_id)
        await self.stop_replay()
        slaves = _slaves_from(source)
        if not slaves:
            raise ValueError("The recording has no device responses to replay")

        async def on_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            try:
                while True:
                    transaction, unit, pdu = await _read_frame(reader)
                    slave = slaves.get(unit)
                    response = slave.handle(unit, pdu) if slave is not None else bytes([(pdu[:1] or b"\x00")[0] | 0x80, 11])
                    writer.write(_frame(transaction, unit, response))
                    await writer.drain()
            except (asyncio.IncompleteReadError, ConnectionError, OSError):
                pass
            finally:
                writer.close()
                try:
                    await writer.wait_closed()
                except Exception:
                    pass

        bind = int(port or 1502)
        if not 0 <= bind <= 65535:
            raise ValueError("Replay port must be 0–65535")
        try:
            server = await asyncio.start_server(on_client, "127.0.0.1", bind)
        except OSError:
            server = await asyncio.start_server(on_client, "127.0.0.1", 0)
        self._server = server
        actual = server.sockets[0].getsockname()[1]
        with self._lock:
            self.replay_port = actual
            self.replay_name = source.get("name") or "Current capture"
            self.detail = f"Replay emulator is on 127.0.0.1:{actual}. It answers from the captured responses."
        return self.snapshot()

    async def stop_replay(self) -> dict:
        server = self._server
        self._server = None
        if server is not None:
            server.close()
            try:
                await server.wait_closed()
            except Exception:
                pass
        with self._lock:
            self.replay_port = None
            if self.detail.startswith("Replay"):
                self.detail = "Replay stopped."
        return self.snapshot()

    async def shutdown(self) -> None:
        self.stop_capture()
        await self.stop_replay()

    def publish_site(
        self,
        unit: int,
        name: str,
        recording_id: str | None = None,
        replace: bool | None = None,
        site_id: str | None = None,
    ) -> dict:
        if self.replay_port is None:
            raise RuntimeError("Start the replay emulator before opening the plant page")
        do_replace = self.replace if replace is None else bool(replace)
        with self._lock:
            self.replace = do_replace
        if not do_replace:
            if not site_id:
                raise ValueError("Turn on Replace, or open a site to keep its register map")
            return update_site(
                site_id,
                {
                    "modbus_host": "127.0.0.1",
                    "modbus_port": self.replay_port,
                    "unit_id": int(unit),
                    "poll_ms": 500,
                },
            )
        if recording_id:
            document = json.loads(self._recording_path(recording_id).read_text(encoding="utf-8"))
            source = document.get("points") or []
        else:
            with self._lock:
                source = self._ordered_points()
        payload = []
        for point in source:
            if int(point.get("device", unit)) != int(unit):
                continue
            payload.append({key: value for key, value in point.items() if key not in ("device", "edited")})
        if not payload:
            raise ValueError("That unit has no mapped registers")
        title = str(name or "Mapper replay").strip()[:80] or "Mapper replay"
        site = create_site(title)
        site = replace_map(
            site["id"],
            {
                "points": payload,
                "bindings": {},
                "layout": {
                    "mimic": False,
                    "compressors": False,
                    "readings": False,
                    "status": True,
                    "outputs": True,
                    "profile": True,
                    "table": True,
                },
            },
        )
        return update_site(
            site["id"],
            {
                "name": title,
                "location": "Replay emulator",
                "modbus_host": "127.0.0.1",
                "modbus_port": self.replay_port,
                "unit_id": int(unit),
                "poll_ms": 500,
                "notes": "Registers captured from RS-485 and served by the replay emulator on this computer.",
            },
        )

    def _listen(self, ser, assembler, mode: str) -> None:
        try:
            while not self._stop.is_set():
                try:
                    waiting = int(getattr(ser, "in_waiting", 0) or 0)
                    chunk = ser.read(waiting or 1)
                except Exception as exc:
                    with self._lock:
                        self.capturing = False
                        self.detail = f"Serial port closed ({exc})."
                    return
                now = time.monotonic()
                for raw in assembler.feed(chunk, now):
                    self.observe_raw(raw, mode)
        finally:
            try:
                ser.close()
            except Exception:
                pass

    def _apply_exchange(self, exchange: dict) -> None:
        request = exchange["request"]
        response = exchange["response"]
        unit = int(request["unit"])
        request_pdu: bytes = request["pdu"]
        response_pdu: bytes = response["pdu"]
        self.exact[(unit, request_pdu)] = response_pdu
        if response.get("exception") or (response_pdu[:1] and response_pdu[0] & 0x80):
            return
        function = request_pdu[0]
        if function in (5, 6, 15, 16):
            address, values = write_values(request_pdu)
            area = "coil" if function in (5, 15) else "holding"
        elif function in AREAS:
            area = AREAS[function]
            address = request_address(request_pdu)
            if address is None:
                return
            if function in (1, 2):
                values = bit_values(response_pdu)[: request_count(request_pdu)]
            else:
                values = register_values(response_pdu)[: request_count(request_pdu)]
        else:
            return
        bank = self.image.setdefault(unit, {}).setdefault(area, {})
        for offset, value in enumerate(values):
            bank[address + offset] = value
            self._ensure_point(unit, area, address + offset, writable=function in (5, 6, 15, 16))

    def _ensure_point(self, unit: int, function: str, address: int, writable: bool) -> None:
        point_id = _point_id(unit, function, address)
        current = self.points.get(point_id)
        if current is None:
            self.points[point_id] = _new_point(unit, function, address, writable)
            return
        if writable and not current.get("edited"):
            current["writable"] = function in ("holding", "coil")
            if function in ("holding", "coil"):
                current["widget"] = "setpoint"

    def _reading(self, point: dict) -> tuple[object | None, list]:
        wire = wire_address(point["function"], point["address_number"], point["addressing"])
        bank = self.image.get(int(point["device"]), {}).get(point["function"], {})
        if point["function"] in ("coil", "discrete"):
            if wire not in bank:
                return None, []
            raw = [bool(bank[wire])]
        else:
            count = string_registers(point) if point["dtype"] == "string" else register_count(point["dtype"])
            if any((wire + offset) not in bank for offset in range(count)):
                return None, []
            raw = [int(bank[wire + offset]) for offset in range(count)]
        try:
            return engineering_from_raw(point, raw), raw
        except (ValueError, TypeError):
            return None, raw

    def _ordered_points(self) -> list[dict]:
        return sorted(self.points.values(), key=lambda point: (point["device"], point["function"], point["sort"], point["name"]))

    def _document(self, name: str) -> dict:
        return {
            "id": uuid.uuid4().hex[:12],
            "name": name,
            "saved": datetime.now(timezone.utc).isoformat(),
            "mode": self.settings["mode"],
            "exchanges": list(self.exchanges),
            "image": {
                str(unit): {area: {str(addr): value for addr, value in bank.items()} for area, bank in areas.items()}
                for unit, areas in self.image.items()
            },
            "points": list(self._ordered_points()),
            "exact": [
                {"unit": unit, "request": request.hex(), "response": response.hex()}
                for (unit, request), response in self.exact.items()
            ],
        }

    def _load_document(self, document: dict, name: str) -> None:
        self.image.clear()
        self.points.clear()
        self.exact.clear()
        self.exchanges.clear()
        self.frames.clear()
        self._conversation.reset()
        for item in document.get("exchanges") or []:
            if isinstance(item, dict) and item.get("request") and item.get("response"):
                self.exchanges.append(
                    {
                        "unit": int(item.get("unit", 1)),
                        "request": str(item["request"]),
                        "response": str(item["response"]),
                    }
                )
        for item in document.get("exact") or []:
            if not isinstance(item, dict):
                continue
            self.exact[(int(item["unit"]), bytes.fromhex(item["request"]))] = bytes.fromhex(item["response"])
        image = document.get("image") or {}
        if isinstance(image, dict):
            for unit, areas in image.items():
                if not isinstance(areas, dict):
                    continue
                for area, bank in areas.items():
                    if area not in AREA_LETTER or not isinstance(bank, dict):
                        continue
                    target = self.image.setdefault(int(unit), {}).setdefault(area, {})
                    for addr, value in bank.items():
                        target[int(addr)] = value
        for item in document.get("points") or []:
            if not isinstance(item, dict):
                continue
            point = normalize_point(item)
            point["device"] = int(item.get("device", item.get("unit", 1)))
            point["edited"] = bool(item.get("edited", True))
            self.points[point["id"]] = point
        if not self.points:
            for unit, areas in self.image.items():
                for area, bank in areas.items():
                    for address in bank:
                        self._ensure_point(unit, area, address, writable=False)
        self.replay_name = name

    def _source(self, recording_id: str | None) -> dict:
        if not recording_id:
            with self._lock:
                return self._document(self.replay_name or "Current capture")
        return json.loads(self._recording_path(recording_id).read_text(encoding="utf-8"))

    def _recording_index(self) -> list[dict]:
        root = recordings_dir()
        if not root.exists():
            return []
        found = []
        for path in root.glob("*.json"):
            try:
                document = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            found.append(
                {
                    "id": document.get("id") or path.stem,
                    "name": document.get("name") or path.stem,
                    "saved": document.get("saved") or "",
                    "exchanges": len(document.get("exchanges") or []),
                }
            )
        return sorted(found, key=lambda item: item["saved"], reverse=True)

    def _write_recording(self, document: dict) -> None:
        path = self._recording_path(document["id"])
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(document), encoding="utf-8")
        os.chmod(tmp, 0o600)
        tmp.replace(path)
        os.chmod(path, 0o600)

    def _recording_path(self, recording_id: str):
        if not _RECORDING_ID.match(str(recording_id)):
            raise ValueError("Unknown recording")
        path = (recordings_dir() / f"{recording_id}.json").resolve()
        path.relative_to(recordings_dir().resolve())
        return path


def _imported_document(document: dict, title: str) -> dict:
    exchanges = []
    for item in document.get("exchanges") or []:
        if not isinstance(item, dict) or not item.get("request") or not item.get("response"):
            continue
        bytes.fromhex(str(item["request"]))
        bytes.fromhex(str(item["response"]))
        exchanges.append(
            {
                "unit": int(item.get("unit", 1)),
                "request": str(item["request"]),
                "response": str(item["response"]),
            }
        )
    points = document.get("points") if isinstance(document.get("points"), list) else []
    if not exchanges and not points:
        raise ValueError("Nothing has been captured yet")
    mode = document.get("mode") if document.get("mode") in ("rtu", "ascii") else "rtu"
    return {
        "id": uuid.uuid4().hex[:12],
        "name": title,
        "saved": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "exchanges": exchanges[:MAX_KEPT],
        "image": document.get("image") if isinstance(document.get("image"), dict) else {},
        "points": points,
        "exact": document.get("exact") if isinstance(document.get("exact"), list) else [],
    }


def _slaves_from(document: dict) -> dict[int, ReplaySlave]:
    slaves: dict[int, ReplaySlave] = {}
    exacts: dict[int, dict[bytes, bytes]] = {}
    for item in document.get("exact") or []:
        exacts.setdefault(int(item["unit"]), {})[bytes.fromhex(item["request"])] = bytes.fromhex(item["response"])
    image = document.get("image") or {}
    units = {int(unit) for unit in image} | set(exacts)
    for unit in units:
        slave = ReplaySlave(unit, exacts.get(unit, {}))
        areas = image.get(str(unit), {})
        for area, attr in (("holding", "holding"), ("input", "inputs"), ("coil", "coils"), ("discrete", "discrete")):
            bank = areas.get(area, {})
            target = getattr(slave, attr)
            for addr, value in bank.items():
                index = int(addr)
                if 0 <= index < len(target):
                    target[index] = bool(value) if area in ("coil", "discrete") else int(value) & 0xFFFF
        slaves[unit] = slave
    return slaves


mapper = Mapper()
