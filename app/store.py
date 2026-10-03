"""Site profiles, register maps, and VPN config files stored locally."""

from __future__ import annotations

import json
import os
import re
import threading
import uuid
from copy import deepcopy

from app.decode import (
    DTYPES,
    FUNCTIONS,
    ORDERS,
    wire_address,
)
from app.paths import data_dir, vpn_dir
from app.template import ROLES, default_bindings, default_points

DEMO_ID = "demo"
_LOCK = threading.Lock()
_ID = re.compile(r"^[a-z][a-z0-9_]{0,40}$")
_WIDGETS = ("value", "gauge", "status", "alarm", "setpoint", "hidden")
_LAYOUT = (
    ("mimic", True),
    ("compressors", True),
    ("readings", True),
    ("status", True),
    ("outputs", True),
    ("table", True),
)


def _load() -> dict:
    path = data_dir() / "sites.json"
    if not path.exists():
        return {"sites": []}
    return json.loads(path.read_text(encoding="utf-8"))


def _save(data: dict) -> None:
    root = data_dir()
    root.mkdir(parents=True, exist_ok=True)
    vpn_dir().mkdir(parents=True, exist_ok=True)
    path = root / "sites.json"
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(path)
    os.chmod(path, 0o600)


def _optional_float(raw: dict, key: str) -> float | None:
    if key not in raw or raw[key] is None or raw[key] == "":
        return None
    value = float(raw[key])
    if value != value or value in (float("inf"), float("-inf")):
        raise ValueError(f"{key} must be a finite number")
    return value


def _optional_bit(raw: dict) -> int | None:
    if "bit" not in raw or raw["bit"] is None or raw["bit"] == "":
        return None
    bit = int(raw["bit"])
    if not 0 <= bit <= 15:
        raise ValueError("Bit must be 0–15 or empty")
    return bit


def new_point_id(name: str, taken: set[str]) -> str:
    base = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "point"
    if not base[0].isalpha():
        base = "p_" + base
    base = base[:32]
    candidate = base
    number = 2
    while candidate in taken or not _ID.match(candidate):
        candidate = f"{base[:32]}_{number}"
        number += 1
    return candidate


def normalize_point(raw: dict, taken: set[str] | None = None) -> dict:
    name = str(raw.get("name", "")).strip()
    if not name or len(name) > 80:
        raise ValueError("Point name is required (80 characters max)")
    function = raw.get("function", "holding")
    if function not in FUNCTIONS:
        raise ValueError("Register area must be coil, discrete, holding, or input")
    dtype = raw.get("dtype", "uint16")
    if dtype not in DTYPES:
        raise ValueError("Unknown data type")
    if function in ("coil", "discrete"):
        dtype = "bool"
    addressing = raw.get("addressing", "modicon")
    if "address_number" not in raw or raw["address_number"] == "":
        raise ValueError("Address is required")
    address_number = int(raw["address_number"])
    wire_address(function, address_number, addressing)
    order = raw.get("byte_order") or "ABCD"
    if order not in ORDERS:
        raise ValueError("Byte order must be ABCD, CDAB, BADC, or DCBA")
    widget = raw.get("widget", "value")
    if widget not in _WIDGETS:
        raise ValueError("Unknown display widget")
    bit = _optional_bit(raw)
    if bit is not None and dtype != "bool":
        raise ValueError("A bit index only applies to a boolean point")
    if bit is not None and function in ("coil", "discrete"):
        raise ValueError("Coils and discrete inputs do not use a bit index")
    writable = bool(raw.get("writable", False))
    if writable and function not in ("holding", "coil"):
        raise ValueError("Only holding registers and coils can be written")
    scale = float(raw.get("scale", 1))
    if scale == 0:
        raise ValueError("Scale cannot be 0")
    gauge_min = float(raw.get("gauge_min", 0))
    gauge_max = float(raw.get("gauge_max", 100))
    if gauge_min >= gauge_max:
        raise ValueError("Gauge minimum must be below the maximum")
    write_min = _optional_float(raw, "write_min")
    write_max = _optional_float(raw, "write_max")
    if write_min is not None and write_max is not None and write_min > write_max:
        raise ValueError("Write minimum must be below the maximum")
    point_id = str(raw.get("id") or "")
    if not _ID.match(point_id):
        point_id = new_point_id(name, taken or set())
    elif taken is not None and point_id in taken:
        raise ValueError(f"Duplicate point id {point_id}")
    decimals = int(raw.get("decimals", 0))
    if not 0 <= decimals <= 4:
        raise ValueError("Decimals must be 0–4")
    on_label = str(raw.get("on_label") or ("Alarm" if widget == "alarm" else "Running" if widget == "status" else "On"))
    off_label = str(raw.get("off_label") or ("Normal" if widget == "alarm" else "Stopped" if widget == "status" else "Off"))
    return {
        "id": point_id,
        "name": name,
        "group": str(raw.get("group") or "General")[:40],
        "notes": str(raw.get("notes") or "")[:300],
        "function": function,
        "addressing": addressing,
        "address_number": address_number,
        "dtype": dtype,
        "byte_order": order,
        "bit": bit,
        "scale": scale,
        "offset": float(raw.get("offset", 0)),
        "decimals": decimals,
        "unit": str(raw.get("unit") or "")[:16],
        "widget": widget,
        "gauge_min": gauge_min,
        "gauge_max": gauge_max,
        "alarm_low": _optional_float(raw, "alarm_low"),
        "alarm_high": _optional_float(raw, "alarm_high"),
        "writable": writable,
        "force_fc16": bool(raw.get("force_fc16", False)),
        "write_min": write_min,
        "write_max": write_max,
        "invert": bool(raw.get("invert", False)),
        "on_label": on_label[:24],
        "off_label": off_label[:24],
        "enabled": bool(raw.get("enabled", True)),
        "sort": int(raw.get("sort", 10)),
    }


def normalize_layout(raw: dict | None, current: dict | None = None) -> dict[str, bool]:
    merged = {key: default for key, default in _LAYOUT}
    for source in (current, raw):
        if not isinstance(source, dict):
            continue
        for key, _default in _LAYOUT:
            if key in source:
                merged[key] = bool(source[key])
    return merged


def normalize_bindings(bindings: dict | None, points: list[dict]) -> dict[str, str | None]:
    ids = {point["id"] for point in points}
    incoming = bindings or {}
    return {role["id"]: incoming.get(role["id"]) if incoming.get(role["id"]) in ids else None for role in ROLES}


def _clean_host(value: str) -> str:
    host = str(value or "").strip()
    if not host or len(host) > 253 or any(ch.isspace() for ch in host):
        raise ValueError("Enter the Modbus IP address of the gateway or controller")
    return host


def _connection_fields(raw: dict, current: dict | None = None) -> dict:
    current = current or {}
    name = str(raw.get("name", current.get("name", ""))).strip()
    if not name or len(name) > 80:
        raise ValueError("Site name is required")
    port = int(raw.get("modbus_port", current.get("modbus_port", 502)))
    if not 1 <= port <= 65535:
        raise ValueError("Modbus port must be 1–65535")
    unit = int(raw.get("unit_id", current.get("unit_id", 1)))
    if not 0 <= unit <= 255:
        raise ValueError("Unit id must be 0–255")
    timeout = float(raw.get("timeout_s", current.get("timeout_s", 3)))
    if not 0.2 <= timeout <= 30:
        raise ValueError("Timeout must be between 0.2 s and 30 s")
    poll = int(raw.get("poll_ms", current.get("poll_ms", 1000)))
    if not 200 <= poll <= 60000:
        raise ValueError("Poll interval must be between 200 ms and 60 s")
    retries = int(raw.get("retries", current.get("retries", 3)))
    if not 1 <= retries <= 10:
        raise ValueError("Retries must be between 1 and 10")
    link_timeout = float(raw.get("link_timeout_s", current.get("link_timeout_s", 30)))
    if not 1 <= link_timeout <= 120:
        raise ValueError("Link timeout must be between 1 s and 120 s")
    return {
        "name": name,
        "location": str(raw.get("location", current.get("location", "")))[:120],
        "notes": str(raw.get("notes", current.get("notes", "")))[:500],
        "evap_label": str(raw.get("evap_label", current.get("evap_label", "Evaporator")))[:40] or "Evaporator",
        "cond_label": str(raw.get("cond_label", current.get("cond_label", "Condenser")))[:40] or "Condenser",
        "vpn_mode": "none",
        "vpn_username": current.get("vpn_username", ""),
        "vpn_password": current.get("vpn_password", ""),
        "vpn_config_name": current.get("vpn_config_name"),
        "modbus_host": _clean_host(raw.get("modbus_host", current.get("modbus_host", "192.168.1.1"))),
        "modbus_port": port,
        "unit_id": unit,
        "timeout_s": timeout,
        "retries": retries,
        "link_timeout_s": link_timeout,
        "poll_ms": poll,
    }


def _new_site(name: str, site_id: str | None = None) -> dict:
    points = [normalize_point(point) for point in default_points()]
    site = {
        "id": site_id or uuid.uuid4().hex[:12],
        "points": points,
        "bindings": normalize_bindings(default_bindings(), points),
        "layout": normalize_layout(None),
    }
    site.update(
        _connection_fields(
            {
                "name": name,
                "modbus_host": "192.168.1.1",
                "notes": "Template addresses are an example chilled-water layout. Match every point to the controller register list before trusting the numbers.",
            }
        )
    )
    return site


def public_site(site: dict) -> dict:
    data = deepcopy(site)
    data["vpn_password_set"] = bool(data.get("vpn_password"))
    data["vpn_password"] = ""
    data["vpn_config_ready"] = vpn_config_path(site) is not None
    data["points"] = sorted(data["points"], key=lambda point: (point["sort"], point["name"].lower()))
    data["layout"] = normalize_layout(data.get("layout"))
    return data


def vpn_config_path(site: dict):
    if not site.get("vpn_config_name"):
        return None
    path = (vpn_dir() / f"{site['id']}.conf").resolve()
    try:
        path.relative_to(vpn_dir().resolve())
    except ValueError:
        return None
    if not path.is_file():
        return None
    return path


def list_sites() -> list[dict]:
    with _LOCK:
        return [public_site(site) for site in _load()["sites"]]


def get_site(site_id: str) -> dict:
    with _LOCK:
        for site in _load()["sites"]:
            if site["id"] == site_id:
                return deepcopy(site)
    raise KeyError(site_id)


def create_site(name: str) -> dict:
    with _LOCK:
        data = _load()
        site = _new_site(name)
        data["sites"].append(site)
        _save(data)
        return public_site(site)


def update_site(site_id: str, raw: dict) -> dict:
    with _LOCK:
        data = _load()
        site = _find(data, site_id)
        site.update(_connection_fields(raw, site))
        _save(data)
        return public_site(site)


def delete_site(site_id: str) -> None:
    with _LOCK:
        data = _load()
        before = len(data["sites"])
        data["sites"] = [site for site in data["sites"] if site["id"] != site_id]
        if len(data["sites"]) == before:
            raise KeyError(site_id)
        _save(data)
    path = vpn_dir() / f"{site_id}.conf"
    auth = vpn_dir() / f"{site_id}.auth"
    for item in (path, auth):
        if item.exists():
            item.unlink()


def save_vpn_config(site_id: str, filename: str, text: str) -> dict:
    if "\x00" in text:
        raise ValueError("VPN config must be a text file")
    with _LOCK:
        data = _load()
        site = _find(data, site_id)
        mode = site["vpn_mode"]
        lowered = text.lower()
        if mode == "wireguard" and "[interface]" not in lowered:
            raise ValueError("This does not look like a WireGuard config. It needs an [Interface] section.")
        if mode == "openvpn" and not any(token in lowered for token in ("remote ", "client", "<ca>", "dev tun", "dev tap")):
            raise ValueError("This does not look like an OpenVPN profile.")
        if mode == "none":
            raise ValueError("Choose WireGuard or OpenVPN before uploading a profile.")
        vpn_dir().mkdir(parents=True, exist_ok=True)
        path = vpn_dir() / f"{site_id}.conf"
        path.write_text(text, encoding="utf-8")
        os.chmod(path, 0o600)
        site["vpn_config_name"] = os.path.basename(filename or "client.conf")[:120]
        _save(data)
        return public_site(site)


def clear_vpn_config(site_id: str) -> dict:
    with _LOCK:
        data = _load()
        site = _find(data, site_id)
        site["vpn_config_name"] = None
        _save(data)
        published = public_site(site)
    path = vpn_dir() / f"{site_id}.conf"
    if path.exists():
        path.unlink()
    return published


def add_point(site_id: str) -> tuple[dict, str]:
    with _LOCK:
        data = _load()
        site = _find(data, site_id)
        taken = {point["id"] for point in site["points"]}
        holding = [
            point["address_number"]
            for point in site["points"]
            if point["function"] == "holding" and point["addressing"] == "modicon"
        ]
        address = max(holding) + 1 if holding else 40100
        if address > 49999:
            address = 40100
        sort = max((point["sort"] for point in site["points"]), default=0) + 10
        point = normalize_point(
            {
                "name": "New point",
                "address_number": address,
                "sort": sort,
                "notes": "Set the area, address, type, and scale from the controller manual.",
            },
            taken,
        )
        site["points"].append(point)
        _save(data)
        return public_site(site), point["id"]


def update_point(site_id: str, point_id: str, raw: dict) -> dict:
    with _LOCK:
        data = _load()
        site = _find(data, site_id)
        for index, point in enumerate(site["points"]):
            if point["id"] == point_id:
                raw = dict(raw)
                raw["id"] = point_id
                raw["sort"] = point["sort"]
                site["points"][index] = normalize_point(raw)
                site["bindings"] = normalize_bindings(site["bindings"], site["points"])
                _save(data)
                return public_site(site)
    raise KeyError(point_id)


def delete_point(site_id: str, point_id: str) -> dict:
    with _LOCK:
        data = _load()
        site = _find(data, site_id)
        kept = [point for point in site["points"] if point["id"] != point_id]
        if len(kept) == len(site["points"]):
            raise KeyError(point_id)
        site["points"] = kept
        site["bindings"] = normalize_bindings(site["bindings"], kept)
        _save(data)
        return public_site(site)


def move_point(site_id: str, point_id: str, direction: str) -> dict:
    if direction not in ("up", "down"):
        raise ValueError("Direction must be up or down")
    with _LOCK:
        data = _load()
        site = _find(data, site_id)
        order = sorted(site["points"], key=lambda point: (point["sort"], point["name"].lower()))
        index = next((i for i, point in enumerate(order) if point["id"] == point_id), None)
        if index is None:
            raise KeyError(point_id)
        swap = index - 1 if direction == "up" else index + 1
        if 0 <= swap < len(order):
            order[index], order[swap] = order[swap], order[index]
        for position, point in enumerate(order):
            point["sort"] = (position + 1) * 10
        site["points"] = order
        _save(data)
        return public_site(site)


def update_hmi(site_id: str, raw: dict) -> dict:
    with _LOCK:
        data = _load()
        site = _find(data, site_id)
        if "bindings" in raw:
            site["bindings"] = normalize_bindings(raw.get("bindings"), site["points"])
        if "evap_label" in raw:
            site["evap_label"] = str(raw.get("evap_label") or "Evaporator")[:40]
        if "cond_label" in raw:
            site["cond_label"] = str(raw.get("cond_label") or "Condenser")[:40]
        if "layout" in raw:
            site["layout"] = normalize_layout(raw.get("layout"), site.get("layout"))
        _save(data)
        return public_site(site)


def replace_map(site_id: str, raw: dict) -> dict:
    points_in = raw.get("points")
    if not isinstance(points_in, list) or not points_in:
        raise ValueError("Import needs a list of points")
    if len(points_in) > 400:
        raise ValueError("A map can contain at most 400 points")
    normalized = []
    taken: set[str] = set()
    for item in points_in:
        point = normalize_point(item, taken)
        taken.add(point["id"])
        normalized.append(point)
    with _LOCK:
        data = _load()
        site = _find(data, site_id)
        site["points"] = normalized
        site["bindings"] = normalize_bindings(raw.get("bindings", site.get("bindings")), normalized)
        if "layout" in raw:
            site["layout"] = normalize_layout(raw.get("layout"), site.get("layout"))
        _save(data)
        return public_site(site)


def apply_template(site_id: str) -> dict:
    with _LOCK:
        data = _load()
        site = _find(data, site_id)
        points = [normalize_point(point) for point in default_points()]
        site["points"] = points
        site["bindings"] = normalize_bindings(default_bindings(), points)
        _save(data)
        return public_site(site)


def _fill_missing_template(site: dict) -> None:
    taken = {point["id"] for point in site["points"]}
    for raw in default_points():
        if raw["id"] not in taken:
            site["points"].append(normalize_point(raw))
            taken.add(raw["id"])
    ids = {point["id"] for point in site["points"]}
    bindings = normalize_bindings(site.get("bindings"), site["points"])
    for role_id, point_id in default_bindings().items():
        if bindings.get(role_id) is None and point_id in ids:
            bindings[role_id] = point_id
    site["bindings"] = bindings


def ensure_demo(port: int) -> dict:
    with _LOCK:
        data = _load()
        found = next((site for site in data["sites"] if site["id"] == DEMO_ID), None)
        if found is None:
            found = _new_site("Demo chiller", DEMO_ID)
            found["location"] = "This computer"
            found["notes"] = (
                "Simulated controller on this PC. The map matches the demo registers. "
                "CHW supply alarms above its high limit so the banner can be seen."
            )
            found["modbus_host"] = "127.0.0.1"
            found["modbus_port"] = int(port)
            found["poll_ms"] = 500
            found["vpn_mode"] = "none"
            data["sites"].insert(0, found)
        else:
            found["modbus_host"] = "127.0.0.1"
            found["modbus_port"] = int(port)
            found["vpn_mode"] = "none"
        _fill_missing_template(found)
        for point in found["points"]:
            if point["id"] == "compressor_count":
                point["writable"] = True
                point["write_min"] = 1
                point["write_max"] = 6
                point["widget"] = "hidden"
        _save(data)
        return deepcopy(found)


def export_map(site_id: str) -> dict:
    site = get_site(site_id)
    return {
        "name": site["name"],
        "evap_label": site["evap_label"],
        "cond_label": site["cond_label"],
        "points": site["points"],
        "bindings": site["bindings"],
        "layout": normalize_layout(site.get("layout")),
    }


def _find(data: dict, site_id: str) -> dict:
    for site in data["sites"]:
        if site["id"] == site_id:
            return site
    raise KeyError(site_id)
