"""Fault text for the chiller display, taken from the controller sheet.

The sheet names each alarm output. Where it also gives a value, such as
``4 = Alarm``, that wording is the message. Alarm-message registers have no
further sentence, so the register name is the fault Modbus can output.
"""

from __future__ import annotations

import csv
import re
from functools import lru_cache

from app.paths import ROOT

_SHEET = ROOT / "profiles" / "modbus-1-compressor.csv"
_ENUM = re.compile(r"(\d+)\s*=\s*([^,]+)")
_BIT = re.compile(r"\.(\d+)$")


def _modicon(sheet_address: int) -> int:
    if 400001 <= sheet_address <= 465536:
        return 40000 + (sheet_address - 400000)
    return sheet_address


def _title(reg_name: str, meaningful: str) -> str:
    prefix = _ENUM.sub("", meaningful).strip(" ,")
    if prefix:
        return prefix
    name = reg_name.removeprefix("SI - ").strip()
    return _BIT.sub("", name).strip()


def _is_fault_row(reg_name: str, place: str, states: dict[int, str]) -> bool:
    if place.strip().lower() == "alarm":
        return True
    if "alarm" in reg_name.lower():
        return True
    return any(label.strip().lower() == "alarm" for label in states.values())


@lru_cache(maxsize=1)
def sheet_faults() -> dict[tuple[int, int | None], dict]:
    catalog: dict[tuple[int, int | None], dict] = {}
    with _SHEET.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            meaningful = row.get("Meaningful Name") or ""
            states = {int(number): label.strip() for number, label in _ENUM.findall(meaningful)}
            reg_name = row.get("RegName") or ""
            if not _is_fault_row(reg_name, row.get("Place") or "", states):
                continue
            bit_match = _BIT.search(reg_name.strip())
            bit = int(bit_match.group(1)) if bit_match else None
            address = _modicon(int(row["RegAddress"]))
            catalog[(address, bit)] = {
                "title": _title(reg_name, meaningful),
                "states": states,
            }
    return catalog


def fault_message(point: dict, value) -> str | None:
    """The sheet's wording for this live value, when the value is a fault."""
    if value is None:
        return None
    bit = point.get("bit")
    bit = None if bit is None or bit == "" else int(bit)
    spec = sheet_faults().get((int(point.get("address_number") or 0), bit))
    if spec is None:
        return None
    states: dict[int, str] = spec["states"]
    is_bool = (
        isinstance(value, bool)
        or point.get("dtype") == "bool"
        or point.get("function") in ("coil", "discrete")
    )
    if is_bool:
        return spec["title"] if bool(value) else None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    if number in states:
        label = states[number]
        if label.lower() != "alarm":
            return None
        title = spec["title"]
        if title.lower() == "alarm":
            return title
        return f"{title}: {label}"
    if states or number == 0:
        return None
    return spec["title"]
