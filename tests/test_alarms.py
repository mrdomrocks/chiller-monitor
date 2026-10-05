"""Fault wording on the chiller display comes from the controller sheet."""

import csv

from app.alarms import fault_message, sheet_faults
from app.paths import ROOT

SHEET = ROOT / "profiles" / "modbus-1-compressor.csv"


def _rows():
    with SHEET.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def test_sheet_names_every_alarm_output():
    catalog = sheet_faults()
    alarm_rows = [row for row in _rows() if row["Place"].strip().lower() == "alarm" or "alarm" in row["RegName"].lower()]
    assert len(alarm_rows) == 10
    for row in alarm_rows:
        address = int(row["RegAddress"]) - 400000 + 40000
        assert any(key[0] == address for key in catalog)


def test_fault_text_uses_the_sheet_wording():
    assert fault_message({"address_number": 40002, "bit": 0, "dtype": "bool"}, True) == "General Alarm"
    assert fault_message({"address_number": 40002, "bit": 0, "dtype": "bool"}, False) is None
    assert fault_message({"address_number": 40016, "bit": None, "dtype": "bool"}, True) == "Alarm Message1"
    assert fault_message({"address_number": 40022, "bit": None, "dtype": "bool"}, True) == "Alarm Message 7"
    assert fault_message({"address_number": 40063, "bit": None, "dtype": "bool"}, False) is None
    assert fault_message({"address_number": 40066, "bit": None, "dtype": "int16"}, 12) == "Alarm Message 9"
    assert fault_message({"address_number": 40066, "bit": None, "dtype": "int16"}, 0) is None
    assert fault_message({"address_number": 40039, "bit": None, "dtype": "int16"}, 4) == "Unit active status: Alarm"
    assert fault_message({"address_number": 40039, "bit": None, "dtype": "int16"}, 2) is None
    assert fault_message({"address_number": 40002, "bit": 6, "dtype": "bool"}, True) is None
    assert fault_message({"address_number": 40003, "bit": None, "dtype": "int16"}, 7) is None
