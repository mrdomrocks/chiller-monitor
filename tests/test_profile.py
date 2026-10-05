"""The 1-compressor Modbus CSV, converted to a map the register page can import."""

import json

from app.paths import ROOT
from app.store import create_site, get_site, replace_map

MAP = ROOT / "profiles" / "modbus-1-compressor.json"


def test_one_compressor_profile_imports(tmp_path, monkeypatch):
    monkeypatch.setenv("CHILLER_DATA", str(tmp_path))
    document = json.loads(MAP.read_text(encoding="utf-8"))
    site = create_site("1 compressor")
    imported = replace_map(site["id"], document)

    assert len(imported["points"]) == 74
    by_id = {point["id"]: point for point in imported["points"]}
    assert by_id["water_outlet"]["address_number"] == 40003
    assert by_id["water_outlet"]["dtype"] == "int16"
    assert by_id["water_outlet"]["scale"] == 1
    assert by_id["general_alarm"] == {
        **by_id["general_alarm"],
        "address_number": 40002,
        "bit": 0,
        "dtype": "bool",
        "widget": "alarm",
    }
    assert by_id["comp_1_running"]["bit"] == 4
    assert by_id["pump_running"]["bit"] == 6
    assert by_id["unit_active_status"]["address_number"] == 40039
    assert by_id["alarm_message1"]["bit"] is None
    assert by_id["alarm_message_9"]["dtype"] == "int16"
    assert imported["bindings"]["supply_temp"] == "water_outlet"
    assert imported["bindings"]["alarm"] == "general_alarm"
    assert imported["bindings"]["compressor"] == "comp_1_running"
    assert imported["bindings"]["comp_1_run"] == "comp_1_running"
    assert imported["bindings"]["evap_pump"] == "pump_running"
    assert imported["bindings"]["return_temp"] is None
    assert imported["bindings"]["setpoint"] is None
    assert imported["layout"]["readings"] is False
    assert all(point["function"] == "holding" and not point["writable"] for point in imported["points"])
    assert 40027 not in {point["address_number"] for point in imported["points"]}

    stored = get_site(site["id"])
    name = next(point for point in stored["points"] if point["id"] == "chiller_name")
    used = {point["address_number"] for point in imported["points"]}
    assert name["address_number"] not in used
