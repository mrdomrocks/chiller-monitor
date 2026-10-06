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
    assert imported["bindings"]["return_temp"] == "evaporator_outlet_temp"
    assert imported["bindings"]["high_pressure"] == "comp_1_discharge_pressure"
    assert imported["bindings"]["low_pressure"] == "comp_1_suction_pressure"
    assert imported["bindings"]["pump_pressure"] == "press_2_cool_inlet_nor"
    assert by_id["comp_1_discharge_pressure"]["unit"] == "bar"
    assert by_id["comp_1_suction_pressure"]["unit"] == "bar"
    assert by_id["press_2_cool_inlet_nor"]["unit"] == "bar"
    assert by_id["comp_1_discharge_pressure"]["gauge_max"] == 25
    assert by_id["comp_1_suction_pressure"]["gauge_max"] == 10
    assert by_id["press_2_cool_inlet_nor"]["gauge_max"] == 6
    assert by_id["evaporator_outlet_temp"]["name"] == "Return temperature"
    assert by_id["evaporator_outlet_temp"]["address_number"] == 40004
    assert imported["bindings"]["setpoint"] is None
    assert imported["layout"]["readings"] is False
    assert imported["layout"]["faceplate"] is True
    assert all(point["function"] == "holding" and not point["writable"] for point in imported["points"])
    assert 40027 not in {point["address_number"] for point in imported["points"]}

    stored = get_site(site["id"])
    name = next(point for point in stored["points"] if point["id"] == "chiller_name")
    used = {point["address_number"] for point in imported["points"]}
    assert name["address_number"] not in used
    assert name["address_number"] >= 40100


def test_single_compressor_demo_lists_every_sheet_register(tmp_path, monkeypatch):
    monkeypatch.setenv("CHILLER_DATA", str(tmp_path))
    from app.store import ensure_sized_demo, list_sites

    site = ensure_sized_demo(1, 1502)
    by_id = {point["id"]: point for point in site["points"]}
    assert by_id["water_outlet"]["address_number"] == 40003
    assert by_id["evaporator_outlet_temp"]["address_number"] == 40004
    assert by_id["comp_1_suction_pressure"]["address_number"] == 40033
    assert by_id["fan_output"]["address_number"] == 40048
    assert by_id["circuit_1_superheat"]["address_number"] == 40067
    assert by_id["circuit_1_eev_opening"]["address_number"] == 40069
    assert by_id["valve_4_opening"]["address_number"] == 40078
    assert "chw_supply" not in by_id
    sheet = {point["address_number"] for point in site["points"] if point["id"] != "chiller_name"}
    for gap in (40027, 40030, 40031, 40032, 40042, 40047, 40049, 40055):
        assert gap not in sheet
    again = ensure_sized_demo(1, 1502)
    assert sum(point["id"] == "water_outlet" for point in again["points"]) == 1

    two = ensure_sized_demo(2, 1502)
    assert any(point["id"] == "chw_supply" for point in two["points"])
    assert all(point["id"] != "water_outlet" for point in two["points"])

    from app.main import app
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        created = client.post("/api/sites", json={"name": "Sheet"}).json()
        loaded = client.post(f"/api/sites/{created['id']}/profile/one-compressor")
        assert loaded.status_code == 200
        points = loaded.json()["points"]
        assert any(point["id"] == "water_outlet" and point["address_number"] == 40003 for point in points)
        assert any(point["address_number"] == 40078 for point in points)

    list_sites()
    listed = next(item for item in list_sites() if item["id"] == "demo-1")
    assert any(point["id"] == "fan_output" for point in listed["points"])
    assert listed["bindings"]["high_pressure"] == "comp_1_discharge_pressure"
    assert listed["bindings"]["low_pressure"] == "comp_1_suction_pressure"
    assert listed["bindings"]["pump_pressure"] == "press_2_cool_inlet_nor"


def test_sheet_faceplate_bindings_fill_when_the_keys_are_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("CHILLER_DATA", str(tmp_path))
    from app.paths import data_dir
    from app.store import ensure_sized_demo, list_sites

    ensure_sized_demo(1, 1502)
    path = data_dir() / "sites.json"
    stored = json.loads(path.read_text(encoding="utf-8"))
    demo = next(site for site in stored["sites"] if site["id"] == "demo-1")
    for role in ("high_pressure", "low_pressure", "pump_pressure"):
        demo["bindings"].pop(role, None)
    demo["bindings"]["high_pressure"] = None
    path.write_text(json.dumps(stored), encoding="utf-8")

    listed = next(item for item in list_sites() if item["id"] == "demo-1")
    assert listed["bindings"]["high_pressure"] is None
    assert listed["bindings"]["low_pressure"] == "comp_1_suction_pressure"
    assert listed["bindings"]["pump_pressure"] == "press_2_cool_inlet_nor"


def test_blank_sheet_pressures_are_shown_in_bar(tmp_path, monkeypatch):
    monkeypatch.setenv("CHILLER_DATA", str(tmp_path))
    from app.paths import data_dir
    from app.store import ensure_sized_demo, list_sites

    ensure_sized_demo(1, 1502)
    path = data_dir() / "sites.json"
    stored = json.loads(path.read_text(encoding="utf-8"))
    demo = next(site for site in stored["sites"] if site["id"] == "demo-1")
    for point in demo["points"]:
        if point["id"] == "comp_1_discharge_pressure":
            point["unit"] = ""
            point["gauge_min"] = 0
            point["gauge_max"] = 100
        elif point["id"] == "comp_1_suction_pressure":
            point["unit"] = "kPa"
            point["gauge_min"] = 0
            point["gauge_max"] = 40
        elif point["id"] == "press_2_cool_inlet_nor":
            point["unit"] = ""
            point["gauge_min"] = 0
            point["gauge_max"] = 100
    path.write_text(json.dumps(stored), encoding="utf-8")

    listed = next(item for item in list_sites() if item["id"] == "demo-1")
    by_id = {point["id"]: point for point in listed["points"]}
    assert by_id["comp_1_discharge_pressure"]["unit"] == "bar"
    assert by_id["comp_1_discharge_pressure"]["gauge_max"] == 25
    assert by_id["comp_1_suction_pressure"]["unit"] == "kPa"
    assert by_id["comp_1_suction_pressure"]["gauge_max"] == 40
    assert by_id["press_2_cool_inlet_nor"]["unit"] == "bar"
    assert by_id["press_2_cool_inlet_nor"]["gauge_max"] == 6
