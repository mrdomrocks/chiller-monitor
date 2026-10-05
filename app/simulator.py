"""Demo chiller. It serves whatever register map the demo site currently has."""

from __future__ import annotations

import asyncio
import logging
import math
import time

from app.decode import (
    encode_numeric,
    encode_string,
    engineering_from_raw,
    register_count,
    string_registers,
    wire_address,
    wire_bool,
)
from app.modbus_tcp import ModbusDevice, serve_device
from app.store import DEMO_ID, get_site
from app.template import MAX_COMPRESSORS, default_points

log = logging.getLogger("chiller.demo")

DEFAULTS: dict[str, float | bool] = {
    "chw_supply": 7.2,
    "chw_return": 12.2,
    "setpoint": 7.0,
    "capacity": 60,
    "cond_in": 28.0,
    "cond_out": 33.0,
    "flow": 18.0,
    "pressure": 2.4,
    "compressor": True,
    "evap_pump": True,
    "general_alarm": False,
    "enable": True,
    "power": 48.0,
    "compressor_count": 2,
}


def fitted_count(value, default: int = 2) -> int:
    try:
        count = int(round(float(value)))
    except (TypeError, ValueError):
        return default
    if 1 <= count <= MAX_COMPRESSORS:
        return count
    return default


def stage_loads(count: int, capacity: float, enabled: bool) -> list[tuple[float, bool]]:
    """Stage compressor load across the fitted machines. Unused slots stay at 0%."""
    count = fitted_count(count, default=0) if count else 0
    idle = [(0.0, False)] * MAX_COMPRESSORS
    if count <= 0 or not enabled or capacity <= 0:
        return idle
    span = 100.0 / count
    loads: list[tuple[float, bool]] = []
    for index in range(MAX_COMPRESSORS):
        if index >= count:
            loads.append((0.0, False))
            continue
        threshold = index * span
        if capacity <= threshold:
            loads.append((0.0, False))
            continue
        portion = min(100.0, max(0.0, (capacity - threshold) / span * 100.0))
        loads.append((portion, True))
    return loads


def _grow(items: list, address: int, fill):
    if address < 0 or address > 2000:
        return False
    if address >= len(items):
        items.extend([fill] * (address - len(items) + 8))
    return True


def paint(device: ModbusDevice, points: list[dict], values: dict) -> None:
    bit_words: dict[tuple[str, int], int] = {}
    for point in points:
        if not point.get("enabled", True) or point["id"] not in values:
            continue
        address = wire_address(point["function"], point["address_number"], point["addressing"])
        if point["function"] in ("coil", "discrete"):
            target = device.coils if point["function"] == "coil" else device.discrete
            if _grow(target, address, False):
                target[address] = wire_bool(point, bool(values[point["id"]]))
            continue
        if point["dtype"] == "string":
            registers = device.inputs if point["function"] == "input" else device.holding
            words = encode_string(
                str(values[point["id"]]),
                int(point.get("string_chars") or 16),
                point.get("byte_order") or "ABCD",
            )
            for offset, word in enumerate(words):
                if _grow(registers, address + offset, 0):
                    registers[address + offset] = word
            continue
        if point["dtype"] == "bool":
            flag = wire_bool(point, bool(values[point["id"]]))
            bit = 0 if point.get("bit") is None else int(point["bit"])
            key = (point["function"], address)
            word = bit_words.get(key, 0)
            if flag:
                word |= 1 << bit
            bit_words[key] = word
            continue
        registers = device.inputs if point["function"] == "input" else device.holding
        for offset, word in enumerate(encode_numeric(point, float(values[point["id"]]))):
            if _grow(registers, address + offset, 0):
                registers[address + offset] = word
    for (function, address), word in bit_words.items():
        registers = device.inputs if function == "input" else device.holding
        if _grow(registers, address, 0):
            registers[address] = word & 0xFFFF


def read_engineering(device: ModbusDevice, point: dict, fallback):
    try:
        address = wire_address(point["function"], point["address_number"], point["addressing"])
        if point["function"] in ("coil", "discrete"):
            bits = device.coils if point["function"] == "coil" else device.discrete
            if address >= len(bits):
                return fallback
            return engineering_from_raw(point, [bits[address]])
        if point["dtype"] == "bool":
            count = 1
        elif point["dtype"] == "string":
            count = string_registers(point)
        else:
            count = register_count(point["dtype"])
        registers = device.inputs if point["function"] == "input" else device.holding
        if address < 0 or address + count > len(registers):
            return fallback
        return engineering_from_raw(point, registers[address : address + count])
    except Exception:
        return fallback


class ChillerSimulator:
    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 1502,
        unit: int = 1,
        site_id: str = DEMO_ID,
        compressors: int | None = None,
    ):
        self.host = host
        self.port = port
        self.site_id = site_id
        self.compressors = compressors
        self.device = ModbusDevice(unit=unit)
        self._server: asyncio.Server | None = None
        self._task: asyncio.Task | None = None
        self._clients: set = set()

    def points(self) -> list[dict]:
        try:
            return get_site(self.site_id)["points"]
        except KeyError:
            return default_points()

    async def start(self) -> int:
        paint(self.device, default_points(), DEFAULTS)
        try:
            self._frame()
        except Exception:
            log.exception("Demo frame failed")
        try:
            self._server = await serve_device(self.device, self.host, self.port, self._clients)
        except OSError:
            self._server = await serve_device(self.device, self.host, 0, self._clients)
        self.port = self._server.sockets[0].getsockname()[1]
        self._task = asyncio.create_task(self._loop())
        log.info("Demo chiller listening on %s:%s", self.host, self.port)
        return self.port

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        if self._server is not None:
            for writer in list(self._clients):
                writer.close()
            self._server.close()
            await self._server.wait_closed()
            self._server = None
            self._clients.clear()

    async def _loop(self) -> None:
        try:
            while True:
                try:
                    self._frame()
                except Exception:
                    log.exception("Demo frame failed")
                await asyncio.sleep(0.5)
        except asyncio.CancelledError:
            raise

    def _frame(self) -> None:
        points = self.points()
        by_id = {point["id"]: point for point in points}
        now = time.monotonic()
        supply = 7.2 + math.sin(now / 8.0) * 0.8
        capacity = 60 + 25 * math.sin(now / 7.0)
        cond_in = 27 + math.sin(now / 12.0) * 1.5
        enabled = True
        setpoint = 7.0
        if "enable" in by_id:
            enabled = bool(read_engineering(self.device, by_id["enable"], True))
        if "setpoint" in by_id:
            setpoint = float(read_engineering(self.device, by_id["setpoint"], 7.0))
        limit = 7.6
        if "chw_supply" in by_id and by_id["chw_supply"].get("alarm_high") is not None:
            limit = float(by_id["chw_supply"]["alarm_high"])
        values: dict[str, float | bool] = {
            "chw_supply": supply,
            "chw_return": supply + 5.0,
            "setpoint": setpoint,
            "capacity": capacity,
            "cond_in": cond_in,
            "cond_out": cond_in + 5.0,
            "flow": 18 + math.sin(now / 9.0),
            "pressure": 2.3 + math.sin(now / 10.0) * 0.15,
            "evap_pump": True,
            "general_alarm": supply > limit,
            "enable": bool(enabled),
            "power": 22 + max(capacity, 0) * 0.45,
        }
        for point in points:
            if point["writable"] and point["id"] not in ("setpoint", "enable", "compressor_count"):
                values[point["id"]] = read_engineering(self.device, point, 0)
        if self.compressors:
            count = fitted_count(self.compressors)
            values["chiller_name"] = "1 compressor" if count == 1 else f"{count} compressors"
        else:
            count = 2
            count_point = by_id.get("compressor_count")
            if count_point is not None and count_point.get("writable"):
                count = fitted_count(read_engineering(self.device, count_point, 2))
        values["compressor_count"] = count
        staged = stage_loads(count, float(capacity), bool(enabled))
        for index, (load, running) in enumerate(staged, start=1):
            values[f"comp_{index}_load"] = load
            values[f"comp_{index}_run"] = running
        values["compressor"] = any(running for _load, running in staged)
        roles = {
            "supply_temp": supply,
            "return_temp": supply + 5.0,
            "setpoint": setpoint,
            "capacity": capacity,
            "condenser_in": cond_in,
            "condenser_out": cond_in + 5.0,
            "flow": values["flow"],
            "pressure": values["pressure"],
            "compressor": values["compressor"],
            "evap_pump": True,
            "alarm": values["general_alarm"],
            "compressor_count": count,
            "chiller_name": values.get("chiller_name", ""),
        }
        for index, (load, running) in enumerate(staged, start=1):
            roles[f"comp_{index}_load"] = load
            roles[f"comp_{index}_run"] = running
        try:
            bindings = get_site(self.site_id).get("bindings") or {}
        except KeyError:
            bindings = {}
        for role, point_id in bindings.items():
            if point_id and role in roles and point_id in by_id:
                values[point_id] = roles[role]
        if enabled:
            values.setdefault("unit_active_status", 2)
        else:
            values["unit_active_status"] = 0
        for point_id, sample in {
            "comp_1_suction_pressure": 45,
            "comp_1_discharge_pressure": 180,
            "fan_output": 7,
            "circuit_1_superheat": 6,
            "circuit_1_eev_opening": 42,
            "comp_1_running_current": 8,
            "pump_running_current": 3,
        }.items():
            if point_id in by_id and point_id not in values:
                values[point_id] = sample
        paint(self.device, points, values)
