"""One live session: Modbus TCP, or RTU over TCP, on the laptop's current network."""

from __future__ import annotations

import asyncio
import logging
import time
from copy import deepcopy

from app.blocks import plan_reads
from app.alarms import fault_message
from app.decode import engineering_from_raw, encode_numeric, format_value, in_alarm, wire_bool
from app.modbus_tcp import ModbusTcpClient, apply_link
from app.simulator import ChillerSimulator
from app.store import DEMO_ID, DEMO_SIZES, ensure_demo, ensure_sized_demo, get_site, is_demo_site, sized_demo_id

log = logging.getLogger("chiller")


def idle_snapshot() -> dict:
    return {
        "site_id": None,
        "demo": False,
        "simulator_running": False,
        "vpn": {"state": "down", "detail": ""},
        "modbus": {
            "state": "idle",
            "detail": "Not connected",
            "host": "",
            "port": None,
            "unit_id": None,
        },
        "polled_at": None,
        "rtt_ms": None,
        "poll_ms": 1000,
        "values": {},
        "history": {},
    }


class Monitor:
    def __init__(self) -> None:
        self.site_id: str | None = None
        self.client: ModbusTcpClient | None = None
        self._sim: ChillerSimulator | None = None
        self._last_good = 0.0
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._lock = asyncio.Lock()
        self._subs: list[asyncio.Queue] = []
        self._last: dict[str, dict] = {}
        self._history: dict[str, list[float]] = {}
        self._snap: dict = idle_snapshot()

    def snapshot(self) -> dict:
        return deepcopy(self._snap)

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=1)
        self._subs.append(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        if queue in self._subs:
            self._subs.remove(queue)

    async def connect(self, site_id: str) -> dict:
        site = get_site(site_id)
        async with self._lock:
            await self._teardown_locked()
            self.site_id = site_id
            self._stop = asyncio.Event()
            self._last.clear()
            self._history.clear()
            self.client = ModbusTcpClient(
                site["modbus_host"],
                site["modbus_port"],
                site["unit_id"],
                site["timeout_s"],
            )
            apply_link(self.client, site)
            self._last_good = time.monotonic()
            self._task = asyncio.create_task(self._run(), name="chiller-poll")
            self._publish(self._connecting(site))
            log.info(
                "Polling %s at %s:%s unit %s",
                site["name"],
                site["modbus_host"],
                site["modbus_port"],
                site["unit_id"],
            )
            return self.snapshot()

    async def disconnect(self) -> dict:
        async with self._lock:
            await self._teardown_locked()
            return self.snapshot()

    async def start_demo(self) -> dict:
        async with self._lock:
            if self._sim is not None and self._sim.compressors:
                await self._teardown_locked()
                await self._stop_simulator()
            if self._sim is None:
                simulator = ChillerSimulator()
                await simulator.start()
                self._sim = simulator
            port = self._sim.port
        ensure_demo(port)
        return await self.connect(DEMO_ID)

    async def start_sized_demo(self, count: int) -> dict:
        count = int(count)
        if count not in DEMO_SIZES:
            raise ValueError("A sheet for that compressor count is not loaded yet")
        async with self._lock:
            await self._teardown_locked()
            await self._stop_simulator()
            ensure_sized_demo(count, 1502)
            simulator = ChillerSimulator(port=0, site_id=sized_demo_id(count), compressors=count)
            await simulator.start()
            self._sim = simulator
            port = simulator.port
        ensure_sized_demo(count, port)
        return await self.connect(sized_demo_id(count))

    async def stop_demo(self) -> dict:
        if is_demo_site(self.site_id):
            await self.disconnect()
        async with self._lock:
            await self._stop_simulator()
            snap = dict(self._snap)
            snap["simulator_running"] = False
            self._publish(snap)
            return self.snapshot()

    async def shutdown(self) -> None:
        await self.disconnect()
        async with self._lock:
            await self._stop_simulator()

    async def write(self, point_id: str, value) -> dict:
        client = self.client
        site_id = self.site_id
        if client is None or site_id is None:
            raise RuntimeError("Connect to this site before writing")
        site = get_site(site_id)
        point = next((item for item in site["points"] if item["id"] == point_id), None)
        if point is None:
            raise KeyError(point_id)
        if not point["writable"] or not point["enabled"]:
            raise ValueError(f"{point['name']} is not an enabled writable output")
        engineering = _coerce_write(point, value)
        if not isinstance(engineering, bool):
            if point.get("write_min") is not None and engineering < float(point["write_min"]):
                raise ValueError(f"Below the minimum of {point['write_min']}")
            if point.get("write_max") is not None and engineering > float(point["write_max"]):
                raise ValueError(f"Above the maximum of {point['write_max']}")
        await _write_point(client, point, engineering)
        return {"ok": True, "point_id": point_id, "value": engineering}

    async def _run(self) -> None:
        try:
            while not self._stop.is_set():
                started = time.perf_counter()
                await self._poll_once()
                interval = 1.0
                if self.site_id:
                    try:
                        interval = get_site(self.site_id)["poll_ms"] / 1000
                    except KeyError:
                        break
                remaining = max(0.05, interval - (time.perf_counter() - started))
                try:
                    await asyncio.wait_for(self._stop.wait(), remaining)
                    break
                except TimeoutError:
                    continue
        except asyncio.CancelledError:
            raise

    async def _poll_once(self) -> None:
        site_id = self.site_id
        client = self.client
        if not site_id or client is None or self._stop.is_set():
            return
        try:
            site = get_site(site_id)
        except KeyError:
            self._stop.set()
            return
        if apply_link(client, site):
            await client.close()
        link_timeout = float(site.get("link_timeout_s", 30))
        if self._last_good and time.monotonic() - self._last_good > link_timeout:
            await client.close()

        started = time.perf_counter()
        blocks = plan_reads(site["points"])
        fetched: dict[int, list | Exception] = {}
        errors: list[str] = []
        retries = int(site.get("retries", 3))
        for block in blocks:
            if self._stop.is_set():
                return
            failure: Exception | None = None
            for _attempt in range(retries):
                try:
                    fetched[id(block)] = await client.read(block.function, block.address, block.count)
                    failure = None
                    break
                except Exception as exc:
                    failure = exc
                    await client.close()
            if failure is not None:
                fetched[id(block)] = failure
                errors.append(str(failure))
        rtt = (time.perf_counter() - started) * 1000
        by_id = {point["id"]: point for point in site["points"]}
        values: dict[str, dict] = {}
        for block in blocks:
            result = fetched.get(id(block))
            for span in block.spans:
                point = by_id[span.point_id]
                if isinstance(result, Exception) or result is None:
                    values[span.point_id] = _stale(self._last.get(span.point_id), result)
                    continue
                offset = span.address - block.address
                piece = list(result[offset : offset + span.count])
                try:
                    engineering = engineering_from_raw(point, piece)
                    if isinstance(engineering, float):
                        engineering = round(engineering, int(point["decimals"]))
                    item = {
                        "value": engineering,
                        "display": format_value(point, engineering),
                        "message": fault_message(point, engineering) or "",
                        "quality": "good",
                        "alarm": in_alarm(point, engineering),
                        "unit": point["unit"],
                        "raw": [_as_int(part) for part in piece],
                        "detail": "",
                    }
                    self._last[span.point_id] = item
                    if isinstance(engineering, float):
                        history = self._history.setdefault(span.point_id, [])
                        history.append(float(engineering))
                        del history[:-40]
                    values[span.point_id] = item
                except Exception as exc:
                    values[span.point_id] = _stale(self._last.get(span.point_id), exc)

        good = any(item["quality"] == "good" for item in values.values())
        protocol = "rtu" if site.get("protocol") == "rtu" else "tcp"
        via = "RTU over TCP" if protocol == "rtu" else "Modbus TCP"
        if errors and not good:
            state, detail = "error", errors[0]
        elif errors:
            state, detail = "polling", "Partial read: " + errors[0]
        else:
            state, detail = "polling", f"{via}, unit {site['unit_id']}"
        if good:
            self._last_good = time.monotonic()
        previous_vpn = self._snap.get("vpn") or {"state": "down", "detail": ""}
        self._publish(
            {
                "site_id": site_id,
                "demo": is_demo_site(site_id) and self._sim is not None,
                "simulator_running": self._sim is not None,
                "vpn": previous_vpn,
                "modbus": {
                    "state": state,
                    "detail": detail,
                    "host": site["modbus_host"],
                    "port": site["modbus_port"],
                    "unit_id": site["unit_id"],
                    "protocol": protocol,
                },
                "polled_at": int(time.time() * 1000),
                "rtt_ms": round(rtt, 1),
                "poll_ms": site["poll_ms"],
                "values": values,
                "history": {key: list(items) for key, items in self._history.items()},
            }
        )

    async def _teardown_locked(self) -> None:
        self._stop.set()
        task = self._task
        self._task = None
        if self.client is not None:
            await self.client.close()
            self.client = None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:
                log.exception("Poller stopped after an error")
        self.site_id = None
        self._last.clear()
        self._history.clear()
        snap = idle_snapshot()
        snap["simulator_running"] = self._sim is not None
        self._publish(snap)

    async def _stop_simulator(self) -> None:
        simulator = self._sim
        self._sim = None
        if simulator is not None:
            await simulator.stop()

    def _connecting(self, site: dict) -> dict:
        protocol = "rtu" if site.get("protocol") == "rtu" else "tcp"
        via = "RTU over TCP" if protocol == "rtu" else "Modbus TCP"
        return {
            "site_id": site["id"],
            "demo": is_demo_site(site["id"]) and self._sim is not None,
            "simulator_running": self._sim is not None,
            "vpn": {"state": "skipped", "detail": "Using this laptop's current network."},
            "modbus": {
                "state": "connecting",
                "detail": f"Opening {via}",
                "host": site["modbus_host"],
                "port": site["modbus_port"],
                "unit_id": site["unit_id"],
                "protocol": protocol,
            },
            "polled_at": None,
            "rtt_ms": None,
            "poll_ms": site["poll_ms"],
            "values": {},
            "history": {},
        }

    def _publish(self, snap: dict | None = None) -> None:
        if snap is not None:
            self._snap = snap
        self._snap["simulator_running"] = self._sim is not None
        payload = deepcopy(self._snap)
        for queue in list(self._subs):
            if queue.full():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            try:
                queue.put_nowait(payload)
            except asyncio.QueueFull:
                pass


def _as_int(part) -> int:
    if isinstance(part, bool):
        return int(part)
    return int(part)


def _stale(previous: dict | None, error: BaseException | None) -> dict:
    detail = "" if error is None else str(error)
    if previous:
        item = dict(previous)
        item["quality"] = "stale"
        item["detail"] = detail
        return item
    return {
        "value": None,
        "display": "—",
        "message": "",
        "quality": "bad",
        "alarm": False,
        "unit": "",
        "raw": [],
        "detail": detail,
    }


def _coerce_write(point: dict, value):
    is_bool = point["dtype"] == "bool" or point["function"] == "coil"
    if is_bool:
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "on", "yes"}
        return bool(value)
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Enter a number to write") from exc


async def _write_point(client: ModbusTcpClient, point: dict, engineering) -> None:
    from app.blocks import span_for

    span = span_for(point)
    if point["function"] == "coil" or (point["dtype"] == "bool" and point["function"] == "coil"):
        await client.write_coil(span.address, wire_bool(point, bool(engineering)))
        return
    if point["dtype"] == "bool":
        flag = wire_bool(point, bool(engineering))
        if point.get("bit") is None:
            await client.write_register(span.address, 1 if flag else 0)
            return
        current = await client.read_holding(span.address, 1)
        word = current[0]
        bit = int(point["bit"])
        word = (word | (1 << bit)) if flag else (word & ~(1 << bit))
        await client.write_register(span.address, word & 0xFFFF)
        return
    registers = encode_numeric(point, float(engineering))
    if len(registers) == 1 and not point.get("force_fc16"):
        await client.write_register(span.address, registers[0])
    else:
        await client.write_registers(span.address, registers)


async def tcp_probe(host: str, port: int, timeout: float) -> tuple[bool, str]:
    try:
        _reader, writer = await asyncio.wait_for(asyncio.open_connection(host, int(port)), timeout)
    except Exception as exc:
        return False, f"Cannot open {host}:{port} ({exc})"
    writer.close()
    try:
        await writer.wait_closed()
    except Exception:
        pass
    return True, f"{host}:{port} accepted a TCP connection"


async def probe_site(site: dict) -> dict:
    tcp_ok, detail = await tcp_probe(site["modbus_host"], site["modbus_port"], site["timeout_s"])
    if not tcp_ok:
        return {"tcp": False, "modbus": False, "detail": detail}
    enabled = [point for point in site["points"] if point.get("enabled", True)]
    if not enabled:
        return {"tcp": True, "modbus": False, "detail": "TCP port is open, but no points are enabled"}
    point = sorted(enabled, key=lambda item: (item["sort"], item["name"]))[0]
    client = ModbusTcpClient(site["modbus_host"], site["modbus_port"], site["unit_id"], site["timeout_s"])
    apply_link(client, site)
    try:
        from app.blocks import span_for

        span = span_for(point)
        raw = await client.read(span.function, span.address, span.count)
        value = engineering_from_raw(point, raw)
        if isinstance(value, float):
            value = round(value, int(point["decimals"]))
        shown = format_value(point, value)
        unit = point["unit"]
        return {
            "tcp": True,
            "modbus": True,
            "detail": f"TCP open. {point['name']} = {shown}{(' ' + unit) if unit else ''}",
        }
    except Exception as exc:
        return {"tcp": True, "modbus": False, "detail": str(exc)}
    finally:
        await client.close()
