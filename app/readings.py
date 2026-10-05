"""Turn live chiller readings into a spreadsheet."""

from __future__ import annotations

import csv
import io
import re
from datetime import datetime

# About an hour of samples when the site is polled once a second.
LOG_LIMIT = 3600

COLUMNS = (
    "time",
    "site",
    "point",
    "group",
    "address",
    "sheet_address",
    "bit",
    "value",
    "display",
    "unit",
    "quality",
    "alarm",
    "raw",
)

_SHEET = {
    "holding": (40001, 49999, 400000),
    "input": (30001, 39999, 300000),
    "discrete": (10001, 19999, 100000),
    "coil": (1, 9999, 0),
}


def now_stamp() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")


def sheet_address(point: dict) -> str:
    """Six-digit address from the controller sheet, beside the Modicon number."""
    if point.get("addressing") == "protocol":
        return ""
    span = _SHEET.get(point.get("function") or "")
    if span is None:
        return ""
    number = int(point.get("address_number") or 0)
    low, high, base = span
    if not low <= number <= high:
        return ""
    sheet = base + (number - low + 1)
    if sheet == number:
        return ""
    return str(sheet)


def readings_csv(site: dict, samples: list[dict] | None) -> str:
    """One row per point per sample. An empty log still lists the points."""
    points = [point for point in site.get("points") or [] if point.get("enabled", True)]
    points.sort(key=_point_order)
    if not samples:
        samples = [{"time": "", "values": {}}]
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow(COLUMNS)
    site_name = site.get("name") or ""
    for sample in samples:
        stamp = sample.get("time") or ""
        values = sample.get("values") or {}
        for point in points:
            reading = values.get(point["id"]) or {}
            raw = reading.get("raw") or []
            writer.writerow(
                [
                    stamp,
                    site_name,
                    point.get("name") or "",
                    point.get("group") or "",
                    point.get("address_number") if point.get("address_number") is not None else "",
                    sheet_address(point),
                    "" if point.get("bit") is None else point.get("bit"),
                    _cell(reading.get("value")),
                    reading.get("display") or "",
                    reading.get("unit") if reading else (point.get("unit") or ""),
                    reading.get("quality") or "",
                    _alarm(reading),
                    " ".join(str(part) for part in raw),
                ]
            )
    return "\ufeff" + buffer.getvalue()


def csv_filename(site_name: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", site_name or "site").strip("-").lower() or "site"
    stamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M")
    return f"{slug}-readings-{stamp}.csv"


def _point_order(point: dict) -> tuple:
    bit = point.get("bit")
    return (
        point.get("function") or "",
        int(point.get("address_number") or 0),
        -1 if bit is None else int(bit),
        (point.get("name") or "").lower(),
    )


def _cell(value) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _alarm(reading: dict) -> str:
    if not reading or "alarm" not in reading:
        return ""
    return "yes" if reading.get("alarm") else "no"
