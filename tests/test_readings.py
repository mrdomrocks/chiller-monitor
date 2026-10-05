"""Operational readings exported as a spreadsheet."""

import csv
import io

from app.readings import readings_csv, sheet_address


def _point(**overrides):
    point = {
        "id": "water_outlet",
        "name": "Water Outlet Temp",
        "group": "Temperature",
        "function": "holding",
        "addressing": "modicon",
        "address_number": 40003,
        "bit": None,
        "unit": "°C",
        "enabled": True,
    }
    point.update(overrides)
    return point


def test_sheet_address_matches_the_controller_list():
    assert sheet_address(_point()) == "400003"
    assert sheet_address(_point(address_number=40078)) == "400078"
    assert sheet_address(_point(function="coil", address_number=1)) == ""
    assert sheet_address(_point(addressing="protocol", address_number=2)) == ""


def test_readings_csv_lists_each_point_and_its_value():
    site = {
        "name": "Plant 1",
        "points": [
            _point(),
            _point(
                id="comp_1_running",
                name="Comp #1 Running",
                group="Status",
                address_number=40002,
                bit=4,
                unit="",
            ),
            _point(id="spare", name="Spare", enabled=False, address_number=40010),
        ],
    }
    text = readings_csv(
        site,
        [
            {
                "time": "2026-10-05 21:00:00",
                "values": {
                    "water_outlet": {
                        "value": 7.2,
                        "display": "7.2",
                        "quality": "good",
                        "alarm": False,
                        "unit": "°C",
                        "raw": [72],
                    },
                    "comp_1_running": {
                        "value": True,
                        "display": "Running",
                        "quality": "good",
                        "alarm": False,
                        "unit": "",
                        "raw": [16],
                    },
                },
            }
        ],
    )
    rows = list(csv.DictReader(io.StringIO(text.lstrip("\ufeff"))))
    assert [row["point"] for row in rows] == ["Comp #1 Running", "Water Outlet Temp"]
    running, outlet = rows
    assert running["address"] == "40002"
    assert running["sheet_address"] == "400002"
    assert running["bit"] == "4"
    assert running["value"] == "true"
    assert running["display"] == "Running"
    assert running["raw"] == "16"
    assert outlet["time"] == "2026-10-05 21:00:00"
    assert outlet["site"] == "Plant 1"
    assert outlet["value"] == "7.2"
    assert outlet["unit"] == "°C"
    assert outlet["quality"] == "good"
    assert outlet["alarm"] == "no"
    assert outlet["sheet_address"] == "400003"


def test_readings_csv_lists_points_before_the_first_poll():
    text = readings_csv({"name": "Plant 1", "points": [_point()]}, [])
    rows = list(csv.DictReader(io.StringIO(text.lstrip("\ufeff"))))
    assert rows[0]["point"] == "Water Outlet Temp"
    assert rows[0]["value"] == ""
    assert rows[0]["quality"] == ""
