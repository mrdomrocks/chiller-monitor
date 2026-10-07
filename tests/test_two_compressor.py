"""The Advance two-compressor Modbus export, converted to a register map."""

import csv

from fastapi.testclient import TestClient

from app.paths import ROOT
from app.two_compressor import SHEET, _display_name, two_compressor_document, two_compressor_samples


def _rows():
    lines = SHEET.read_text(encoding="utf-8-sig").splitlines()
    start = next(index for index, line in enumerate(lines) if line.startswith("RegName,"))
    return list(csv.DictReader(lines[start:]))


def test_two_compressor_sheet_keeps_every_register_name_and_address():
    rows = _rows()
    document = two_compressor_document()
    points = document["points"]
    assert len(points) == len(rows) == 297
    by_sheet = {}
    for row, point in zip(rows, points, strict=True):
        sheet = int(row["RegAddress"])
        modicon = 40000 + (sheet - 400000)
        assert point["address_number"] == modicon
        assert point["function"] == "holding"
        assert point["writable"] is False
        assert point["name"] == _display_name(row["RegName"], point["bit"])
        by_sheet[(sheet, point["bit"])] = point

    water = by_sheet[(400003, None)]
    assert water["id"] == "water_outlet"
    assert water["name"] == "Water Outlet"
    assert water["scale"] == 0.1
    assert water["decimals"] == 1
    assert water["unit"] == "°C"
    assert water["offset"] == 0

    suction = by_sheet[(400034, None)]
    assert suction["id"] == "comp_2_suction_pressure"
    assert suction["name"] == "2# Suction Pressure"
    assert suction["address_number"] == 40034
    assert suction["scale"] == 0.1
    assert suction["unit"] == "bar"

    discharge = by_sheet[(400041, None)]
    assert discharge["name"] == "2# Discharge Pressure"
    assert discharge["address_number"] == 40041
    assert discharge["unit"] == "bar"

    fan = by_sheet[(400048, None)]
    assert fan["scale"] == 0.01
    assert fan["decimals"] == 2
    assert fan["unit"] == "V"

    amount = by_sheet[(400302, None)]
    assert amount["id"] == "comp_amount"
    assert amount["name"] == "COMP Amount"
    assert amount["address_number"] == 40302

    condenser = by_sheet[(401001, None)]
    assert condenser["address_number"] == 41001
    assert condenser["name"] == "Cond Use"

    assert by_sheet[(400002, 3)]["id"] == "comp_2_running"
    assert by_sheet[(400002, 3)]["bit"] == 3
    assert by_sheet[(400002, 4)]["id"] == "comp_1_running"
    assert by_sheet[(400002, 6)]["id"] == "pump_running"
    assert by_sheet[(400016, None)]["dtype"] == "bool"
    assert by_sheet[(400016, None)]["bit"] is None
    assert by_sheet[(400202, None)]["id"] == "target_temperature"
    assert by_sheet[(400202, None)]["name"] == "Target Temperture"
    assert by_sheet[(400202, None)]["scale"] == 0.1
    assert by_sheet[(400067, None)]["unit"] == "°C"
    assert by_sheet[(400008, None)]["unit"] == "A"

    addresses = {point["address_number"] for point in points}
    assert 40027 not in addresses
    assert 40331 not in addresses
    assert document["bindings"]["supply_temp"] == "water_outlet"
    assert document["bindings"]["high_pressure"] == "comp_1_discharge_pressure"
    assert document["bindings"]["low_pressure"] == "comp_1_suction_pressure"
    assert document["bindings"]["pump_pressure"] is None
    assert document["bindings"]["comp_2_run"] == "comp_2_running"
    assert document["bindings"]["compressor_count"] == "comp_amount"
    assert document["bindings"]["setpoint"] == "target_temperature"
    assert two_compressor_samples()["comp_1_discharge_pressure"] == 24.4
    assert two_compressor_samples()["comp_2_suction_pressure"] == 8.8
    assert "evaporator_outlet_temp" not in two_compressor_samples()


def test_two_compressor_list_loads_onto_a_site(tmp_path, monkeypatch):
    monkeypatch.setenv("CHILLER_DATA", str(tmp_path))
    from app.main import app
    from app.store import create_site

    site = create_site("Advance")
    with TestClient(app) as client:
        loaded = client.post(f"/api/sites/{site['id']}/profile/two-compressor")
        assert loaded.status_code == 200, loaded.text
        body = loaded.json()
        by_id = {point["id"]: point for point in body["points"]}
        assert by_id["comp_2_discharge_pressure"]["address_number"] == 40041
        assert by_id["comp_1_running_current"]["scale"] == 0.1
        assert by_id["comp_1_running_current"]["unit"] == "A"
        assert body["bindings"]["comp_1_run"] == "comp_1_running"
        assert body["bindings"]["comp_2_run"] == "comp_2_running"
        assert body["layout"]["faceplate"] is True
        assert body["layout"]["profile"] is False
        assert body["layout"]["table"] is False
        assert len(body["points"]) >= 297
