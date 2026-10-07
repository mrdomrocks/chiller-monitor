"""The Advance two-compressor controller sheet, as a register map.

The file is a Modbus Monitor export. Addresses are 6-digit, 1-based holding
registers (400001 is Modicon 40001). RegGain is the scale and RegOffset is the
offset. 0.100000001 in the file is the scale 0.1.
"""

from __future__ import annotations

import csv
import re
from functools import lru_cache

from app.paths import ROOT

SHEET = ROOT / "profiles" / "modbus-2-compressor.csv"
_PREFIX = re.compile(r"^(SI|Up|Cp|Tr|TR|Tp|Iop|EEV|Pd|Fp)\s*-\s*")
_BIT = re.compile(r"\.(\d+)$")
_ID = re.compile(r"^[a-z][a-z0-9_]{0,40}$")

# Faceplate and alarm ids stay stable. Everything else is the register name.
_IDS = {
    (400002, 0): "general_alarm",
    (400002, 3): "comp_2_running",
    (400002, 4): "comp_1_running",
    (400002, 6): "pump_running",
    (400003, None): "water_outlet",
    (400004, None): "evaporator_outlet_temp",
    (400006, None): "comp_2_running_current",
    (400007, None): "pump_running_current",
    (400008, None): "comp_1_running_current",
    (400016, None): "alarm_message1",
    (400017, None): "alarm_message_2",
    (400018, None): "alarm_message_3",
    (400019, None): "alarm_message_4",
    (400020, None): "alarm_message_5",
    (400021, None): "alarm_message_6",
    (400022, None): "alarm_message_7",
    (400033, None): "comp_1_suction_pressure",
    (400034, None): "comp_2_suction_pressure",
    (400035, None): "comp_1_suction_temp",
    (400036, None): "comp_1_evap_temp",
    (400037, None): "comp_2_suction_temp",
    (400038, None): "comp_2_evap_temp",
    (400039, None): "unit_active_status",
    (400040, None): "comp_1_discharge_pressure",
    (400041, None): "comp_2_discharge_pressure",
    (400048, None): "fan_output",
    (400063, None): "alarm_message_8",
    (400066, None): "alarm_message_9",
    (400067, None): "circuit_1_superheat",
    (400069, None): "circuit_1_eev_opening",
    (400202, None): "target_temperature",
    (400302, None): "comp_amount",
}


def _modicon(sheet_address: int) -> int:
    if 400001 <= sheet_address <= 465536:
        return 40000 + (sheet_address - 400000)
    return sheet_address


def _gain(text: str) -> float:
    value = float(text or 1)
    for candidate in (1.0, 0.1, 0.01, 0.001, 10.0):
        if abs(value - candidate) < 1e-4:
            return candidate
    return value


def _rows() -> list[dict[str, str]]:
    lines = SHEET.read_text(encoding="utf-8-sig").splitlines()
    start = next(index for index, line in enumerate(lines) if line.startswith("RegName,"))
    return list(csv.DictReader(lines[start:]))


def _display_name(reg_name: str, bit: int | None) -> str:
    name = _PREFIX.sub("", reg_name).strip()
    if bit is not None:
        name = _BIT.sub("", name).strip()
    return re.sub(r"\s+", " ", name)


def _slug(name: str) -> str:
    text = name.lower().replace("#", "")
    text = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    if not text or not text[0].isalpha():
        text = f"p_{text}".strip("_")
    return text[:40]


def _group(prefix: str, name: str, sheet_address: int, bit: int | None) -> str:
    lower = name.lower()
    if prefix == "SI":
        if "alarm" in lower or (sheet_address == 400002 and bit == 0):
            return "Alarm"
        if sheet_address == 400002:
            return "Status"
        if "temp" in lower:
            return "Temperature"
        if "pressure" in lower:
            return "Pressure"
        if "current" in lower:
            return "Current"
        if "run time" in lower:
            return "Runtime"
        if "flow" in lower:
            return "Flow"
        if "valve" in lower or "superheat" in lower:
            return "Valve"
        if "io board" in lower or "i/o board" in lower:
            return "IO"
        return "Process"
    if prefix == "Up":
        return "User"
    if prefix == "Cp":
        return "Condenser" if sheet_address >= 401000 else "Configuration"
    if prefix in ("Tr", "TR"):
        return "Control"
    if prefix == "Tp":
        return "Timing"
    if prefix == "Iop":
        return "Input"
    if prefix == "EEV":
        return "Valve"
    if prefix == "Pd":
        return "Pressure"
    if prefix == "Fp":
        return "Flow"
    return "General"


_TEMPERATURES = {
    "water_outlet",
    "evaporator_outlet_temp",
    "comp_1_suction_temp",
    "comp_1_evap_temp",
    "comp_2_suction_temp",
    "comp_2_evap_temp",
    "target_temperature",
    "circuit_1_superheat",
}


def _unit(name: str, sheet_address: int, point_id: str) -> str:
    lower = name.lower()
    if "(v)" in lower or lower.startswith("fan output"):
        return "V"
    if "(sec)" in lower:
        return "s"
    if point_id in _TEMPERATURES or "superheat" in lower or ("temp" in lower and sheet_address < 400100):
        return "°C"
    if "current" in lower:
        return "A"
    if "(hour)" in lower:
        return "h"
    if "(min)" in lower:
        return "min"
    if sheet_address in (400033, 400034, 400040, 400041):
        return "bar"
    return ""


def _widget(point_id: str, reg_type: str) -> str:
    if point_id == "general_alarm" or point_id in {
        "alarm_message1",
        "alarm_message_2",
        "alarm_message_3",
        "alarm_message_4",
        "alarm_message_5",
        "alarm_message_6",
        "alarm_message_7",
    }:
        return "alarm"
    if point_id in {"comp_1_running", "comp_2_running", "pump_running"}:
        return "status"
    if point_id in {
        "water_outlet",
        "evaporator_outlet_temp",
        "comp_1_suction_pressure",
        "comp_2_suction_pressure",
        "comp_1_discharge_pressure",
        "comp_2_discharge_pressure",
        "fan_output",
        "circuit_1_superheat",
        "circuit_1_eev_opening",
        "target_temperature",
    }:
        return "gauge"
    return "value" if reg_type else "value"


def _gauge(point_id: str, unit: str) -> tuple[float, float]:
    if point_id in {"comp_1_discharge_pressure", "comp_2_discharge_pressure"}:
        return 0.0, 40.0
    if point_id in {"comp_1_suction_pressure", "comp_2_suction_pressure"}:
        return 0.0, 16.0
    if point_id == "water_outlet":
        return 0.0, 40.0
    if point_id == "fan_output":
        return 0.0, 12.0
    if unit == "°C":
        return -40.0, 80.0
    if unit == "A":
        return 0.0, 40.0
    return 0.0, 100.0


def _decimals(scale: float) -> int:
    if scale == 0.1:
        return 1
    if scale == 0.01:
        return 2
    if scale == 0.001:
        return 3
    return 0


def _sample(text: str, dtype: str) -> float | bool | None:
    if text is None or str(text).strip() == "":
        return None
    number = float(text)
    if dtype == "bool":
        return number != 0
    return number


@lru_cache(maxsize=1)
def _built() -> tuple[tuple[dict, ...], tuple[tuple[str, float | bool], ...]]:
    points: list[dict] = []
    samples: list[tuple[str, float | bool]] = []
    taken: set[str] = set()
    for row in _rows():
        reg_name = (row.get("RegName") or "").strip()
        sheet_address = int(row["RegAddress"])
        reg_type = (row.get("RegType") or "").strip().upper()
        if reg_type not in {"INT16", "BIT"}:
            raise ValueError(f"Unsupported type {reg_type} on {reg_name}")
        order = (row.get("RegByteSwap") or "ABCD_BE").strip()
        if order != "ABCD_BE":
            raise ValueError(f"Unsupported byte order {order} on {reg_name}")
        bit_match = _BIT.search(reg_name) if reg_type == "BIT" else None
        bit = int(bit_match.group(1)) if bit_match else None
        name = _display_name(reg_name, bit)
        if not name or len(name) > 80:
            raise ValueError(f"Register name cannot be stored: {reg_name}")
        prefix_match = _PREFIX.match(reg_name)
        prefix = prefix_match.group(1) if prefix_match else ""
        point_id = _IDS.get((sheet_address, bit)) or _slug(name)
        if point_id in taken:
            suffix = f"_{_modicon(sheet_address)}"
            point_id = f"{point_id[: 41 - len(suffix)]}{suffix}"
        if point_id in taken or not _ID.match(point_id):
            raise ValueError(f"Point id {point_id} is not usable for {reg_name}")
        taken.add(point_id)
        scale = _gain(row.get("RegGain") or "1")
        offset = float(row.get("RegOffset") or 0)
        dtype = "bool" if reg_type == "BIT" else "int16"
        unit = _unit(name, sheet_address, point_id)
        gauge_min, gauge_max = _gauge(point_id, unit)
        modicon = _modicon(sheet_address)
        note = f"CSV {reg_name} at {sheet_address}. Modicon {modicon}. Gain {scale:g}, offset {offset:g}."
        if bit is not None:
            note += f" Bit {bit}."
        elif reg_type == "BIT":
            note += " BIT with no bit number: on when the register is not zero."
        if sheet_address == 400004:
            note += " The captured sheet value is -3270.1, an open-sensor reading."
        if sheet_address == 400034:
            note += " This is compressor 2 suction pressure, not pump pressure."
        points.append(
            {
                "id": point_id,
                "name": name,
                "group": _group(prefix, name, sheet_address, bit),
                "notes": note[:300],
                "function": "holding",
                "addressing": "modicon",
                "address_number": modicon,
                "dtype": dtype,
                "byte_order": "ABCD",
                "bit": bit,
                "scale": scale,
                "offset": offset,
                "decimals": _decimals(scale),
                "unit": unit,
                "widget": _widget(point_id, reg_type),
                "gauge_min": gauge_min,
                "gauge_max": gauge_max,
                "writable": False,
                "enabled": True,
                "sort": 800000 + (modicon - 40000) * 20 + (0 if bit is None else 1 + bit),
            }
        )
        sample = _sample(row.get("RegValue") or "", dtype)
        # The captured evaporator reading is the open-sensor sentinel, not a temperature.
        if sheet_address == 400004 and isinstance(sample, float) and sample < -40:
            sample = None
        if sample is not None:
            samples.append((point_id, sample))
    return tuple(points), tuple(samples)


def two_compressor_document() -> dict:
    """Every row of the two-compressor sheet, ready to replace a site map."""
    points = [dict(point) for point in _built()[0]]
    return {
        "name": "2 compressors",
        "source": "Advance - 2 Compressor Chiller.csv",
        "addressing": (
            "CSV addresses 400001-401005 are 6-digit 1-based holding registers, "
            "stored as Modicon 40001-41005. Gain is the scale. 0.100000001 is 0.1."
        ),
        "evap_label": "Evaporator",
        "cond_label": "Condenser",
        "points": points,
        "bindings": {
            "supply_temp": "water_outlet",
            "return_temp": "evaporator_outlet_temp",
            "setpoint": "target_temperature",
            "capacity": None,
            "condenser_in": None,
            "condenser_out": None,
            "flow": None,
            "pressure": None,
            "high_pressure": "comp_1_discharge_pressure",
            "low_pressure": "comp_1_suction_pressure",
            "pump_pressure": None,
            "compressor": "comp_1_running",
            "evap_pump": "pump_running",
            "alarm": "general_alarm",
            "compressor_count": "comp_amount",
            "chiller_name": None,
            "comp_1_load": None,
            "comp_2_load": None,
            "comp_3_load": None,
            "comp_4_load": None,
            "comp_5_load": None,
            "comp_6_load": None,
            "comp_1_run": "comp_1_running",
            "comp_2_run": "comp_2_running",
            "comp_3_run": None,
            "comp_4_run": None,
            "comp_5_run": None,
            "comp_6_run": None,
        },
        "layout": {
            "faceplate": True,
            "mimic": False,
            "compressors": False,
            "readings": False,
            "status": False,
            "outputs": False,
            "profile": False,
            "table": False,
        },
    }


def two_compressor_samples() -> dict[str, float | bool]:
    """Engineering values captured in the sheet. The open evaporator sensor is left out."""
    return dict(_built()[1])
