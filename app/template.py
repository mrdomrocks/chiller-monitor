"""Starter chilled-water map. Addresses are placeholders until matched to the controller."""

from __future__ import annotations

import copy

MAX_COMPRESSORS = 6

ROLES = [
    {"id": "supply_temp", "label": "Chilled water supply", "kind": "analog", "section": "Water"},
    {"id": "return_temp", "label": "Chilled water return", "kind": "analog", "section": "Water"},
    {"id": "setpoint", "label": "Setpoint", "kind": "analog", "section": "Water"},
    {"id": "capacity", "label": "Capacity", "kind": "analog", "section": "Water"},
    {"id": "condenser_in", "label": "Condenser inlet", "kind": "analog", "section": "Water"},
    {"id": "condenser_out", "label": "Condenser outlet", "kind": "analog", "section": "Water"},
    {"id": "flow", "label": "Chilled water flow", "kind": "analog", "section": "Water"},
    {"id": "pressure", "label": "Chilled water pressure", "kind": "analog", "section": "Water"},
    {"id": "compressor", "label": "Compressor", "kind": "bool", "section": "Status"},
    {"id": "evap_pump", "label": "Evaporator pump", "kind": "bool", "section": "Status"},
    {"id": "cond_pump", "label": "Condenser pump", "kind": "bool", "section": "Status"},
    {"id": "alarm", "label": "General alarm", "kind": "bool", "section": "Status"},
    {"id": "compressor_count", "label": "Fitted compressors", "kind": "analog", "section": "Compressors"},
    {"id": "chiller_name", "label": "Chiller name", "kind": "text", "section": "Plant"},
]
ROLES.extend(
    {"id": f"comp_{index}_load", "label": f"Compressor {index} load", "kind": "analog", "section": "Compressors"}
    for index in range(1, MAX_COMPRESSORS + 1)
)
ROLES.extend(
    {"id": f"comp_{index}_run", "label": f"Compressor {index} run", "kind": "bool", "section": "Compressors"}
    for index in range(1, MAX_COMPRESSORS + 1)
)


def _point(**overrides) -> dict:
    point = {
        "id": "",
        "name": "",
        "group": "General",
        "notes": "",
        "function": "holding",
        "addressing": "modicon",
        "address_number": 40001,
        "dtype": "uint16",
        "byte_order": "ABCD",
        "bit": None,
        "scale": 1.0,
        "offset": 0.0,
        "decimals": 0,
        "unit": "",
        "widget": "value",
        "gauge_min": 0,
        "gauge_max": 100,
        "alarm_low": None,
        "alarm_high": None,
        "writable": False,
        "force_fc16": False,
        "write_min": None,
        "write_max": None,
        "invert": False,
        "on_label": "On",
        "off_label": "Off",
        "enabled": True,
        "sort": 10,
    }
    point.update(overrides)
    return point


def default_points() -> list[dict]:
    return copy.deepcopy(
        [
            _point(
                id="chw_supply",
                name="CHW supply",
                group="Temperature",
                notes="Leaving chilled water. int16, scale 0.1. Match the address to the controller manual.",
                address_number=40001,
                dtype="int16",
                scale=0.1,
                decimals=1,
                unit="°C",
                widget="gauge",
                gauge_min=0,
                gauge_max=20,
                alarm_low=4,
                alarm_high=7.6,
                sort=10,
            ),
            _point(
                id="chw_return",
                name="CHW return",
                group="Temperature",
                notes="Entering chilled water.",
                address_number=40002,
                dtype="int16",
                scale=0.1,
                decimals=1,
                unit="°C",
                widget="gauge",
                gauge_min=0,
                gauge_max=25,
                sort=20,
            ),
            _point(
                id="setpoint",
                name="Setpoint",
                group="Setpoint",
                notes="Active chilled-water setpoint. Writable holding register.",
                address_number=40003,
                dtype="int16",
                scale=0.1,
                decimals=1,
                unit="°C",
                widget="setpoint",
                gauge_min=0,
                gauge_max=20,
                writable=True,
                write_min=4,
                write_max=15,
                sort=30,
            ),
            _point(
                id="capacity",
                name="Capacity",
                group="Process",
                notes="Running capacity.",
                address_number=40004,
                dtype="uint16",
                unit="%",
                widget="gauge",
                gauge_min=0,
                gauge_max=100,
                sort=40,
            ),
            _point(
                id="cond_in",
                name="Condenser in",
                group="Temperature",
                notes="Condenser water inlet, or rename this point if the machine is air-cooled.",
                address_number=40005,
                dtype="int16",
                scale=0.1,
                decimals=1,
                unit="°C",
                widget="gauge",
                gauge_min=0,
                gauge_max=50,
                sort=50,
            ),
            _point(
                id="cond_out",
                name="Condenser out",
                group="Temperature",
                address_number=40006,
                dtype="int16",
                scale=0.1,
                decimals=1,
                unit="°C",
                widget="gauge",
                gauge_min=0,
                gauge_max=55,
                sort=60,
            ),
            _point(
                id="flow",
                name="CHW flow",
                group="Process",
                address_number=40007,
                dtype="int16",
                scale=0.1,
                decimals=1,
                unit="m³/h",
                widget="gauge",
                gauge_min=0,
                gauge_max=40,
                sort=70,
            ),
            _point(
                id="pressure",
                name="CHW pressure",
                group="Process",
                address_number=40008,
                dtype="int16",
                scale=0.01,
                decimals=2,
                unit="bar",
                widget="gauge",
                gauge_min=0,
                gauge_max=6,
                sort=80,
            ),
            _point(
                id="compressor",
                name="Compressor",
                group="Status",
                notes="Bit 0 of status word 40009. Plant run lamp: on when any fitted compressor is running.",
                address_number=40009,
                dtype="bool",
                bit=0,
                widget="status",
                on_label="Running",
                off_label="Stopped",
                sort=90,
            ),
            _point(
                id="evap_pump",
                name="Evaporator pump",
                group="Status",
                notes="Bit 1 of status word 40009.",
                address_number=40009,
                dtype="bool",
                bit=1,
                widget="status",
                on_label="Running",
                off_label="Stopped",
                sort=100,
            ),
            _point(
                id="cond_pump",
                name="Condenser pump",
                group="Status",
                notes="Bit 2 of status word 40009.",
                address_number=40009,
                dtype="bool",
                bit=2,
                widget="status",
                on_label="Running",
                off_label="Stopped",
                sort=110,
            ),
            _point(
                id="general_alarm",
                name="General alarm",
                group="Alarm",
                notes="Bit 3 of status word 40009.",
                address_number=40009,
                dtype="bool",
                bit=3,
                widget="alarm",
                on_label="Alarm",
                off_label="Normal",
                sort=120,
            ),
            _point(
                id="enable",
                name="Enable",
                group="Status",
                notes="Coil output. The demo compressor runs only while this is on.",
                function="coil",
                address_number=1,
                dtype="bool",
                widget="status",
                writable=True,
                on_label="Enabled",
                off_label="Disabled",
                sort=130,
            ),
            _point(
                id="power",
                name="Power",
                group="Process",
                notes="Float32 across 40011 and 40012, byte order ABCD.",
                address_number=40011,
                dtype="float32",
                decimals=1,
                unit="kW",
                widget="gauge",
                gauge_min=0,
                gauge_max=150,
                sort=140,
            ),
            *_compressor_points(),
            _point(
                id="chiller_name",
                name="Chiller name",
                group="Identity",
                notes="ASCII text, two characters per register. The plant heading uses this when it is not blank. An empty register shows as Chiller. Match the address and length to the controller.",
                address_number=40021,
                dtype="string",
                string_chars=16,
                widget="hidden",
                sort=400,
            ),
        ]
    )


def _compressor_points() -> list[dict]:
    points = [
        _point(
            id="compressor_count",
            name="Fitted compressors",
            group="Compressors",
            notes="Register value 1–6. The plant page shows that many compressor cards and hides the rest.",
            address_number=40013,
            dtype="uint16",
            widget="hidden",
            sort=150,
        )
    ]
    for index in range(1, MAX_COMPRESSORS + 1):
        points.append(
            _point(
                id=f"comp_{index}_load",
                name=f"Compressor {index}",
                group="Compressors",
                notes=f"Load percentage for compressor {index}. Shown when fitted compressors is {index} or more.",
                address_number=40013 + index,
                dtype="uint16",
                unit="%",
                widget="hidden",
                gauge_min=0,
                gauge_max=100,
                sort=150 + index * 10,
            )
        )
    for index in range(1, MAX_COMPRESSORS + 1):
        points.append(
            _point(
                id=f"comp_{index}_run",
                name=f"Compressor {index} run",
                group="Compressors",
                notes=f"Bit {index - 1} of register 40020. Running or stopped for compressor {index}.",
                address_number=40020,
                dtype="bool",
                bit=index - 1,
                widget="hidden",
                on_label="Running",
                off_label="Stopped",
                sort=220 + index,
            )
        )
    return points


def default_bindings() -> dict[str, str | None]:
    bindings = {
        "supply_temp": "chw_supply",
        "return_temp": "chw_return",
        "setpoint": "setpoint",
        "capacity": "capacity",
        "condenser_in": "cond_in",
        "condenser_out": "cond_out",
        "flow": "flow",
        "pressure": "pressure",
        "compressor": "compressor",
        "evap_pump": "evap_pump",
        "cond_pump": "cond_pump",
        "alarm": "general_alarm",
        "compressor_count": "compressor_count",
        "chiller_name": "chiller_name",
    }
    for index in range(1, MAX_COMPRESSORS + 1):
        bindings[f"comp_{index}_load"] = f"comp_{index}_load"
        bindings[f"comp_{index}_run"] = f"comp_{index}_run"
    return bindings
