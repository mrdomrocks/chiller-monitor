"""Convert Modbus registers to engineering values and back.

Register order names are the usual four-byte layouts, most significant byte first:

- ABCD: high word first, high byte first (typical Modbus)
- CDAB: words swapped
- BADC: bytes swapped inside each word
- DCBA: bytes and words reversed
"""

from __future__ import annotations

import math
import struct

FUNCTIONS = ("coil", "discrete", "holding", "input")
DTYPES = ("bool", "uint16", "int16", "uint32", "int32", "float32", "float64")
ORDERS = ("ABCD", "CDAB", "BADC", "DCBA")

MODICON_BASE = {
    "coil": 1,
    "discrete": 10001,
    "input": 30001,
    "holding": 40001,
}

_WIDTH = {
    "bool": 1,
    "uint16": 1,
    "int16": 1,
    "uint32": 2,
    "int32": 2,
    "float32": 2,
    "float64": 4,
}

_UNPACK = {
    "uint16": "H",
    "int16": "h",
    "uint32": "I",
    "int32": "i",
    "float32": "f",
    "float64": "d",
}

_RANGES = {
    "uint16": (0, 65535),
    "int16": (-32768, 32767),
    "uint32": (0, 4294967295),
    "int32": (-2147483648, 2147483647),
}


def register_count(dtype: str) -> int:
    if dtype not in _WIDTH:
        raise ValueError(f"Unknown data type {dtype}")
    return _WIDTH[dtype]


def wire_address(function: str, number: int, addressing: str) -> int:
    """Return the 0-based address placed in the Modbus PDU."""
    if function not in MODICON_BASE:
        raise ValueError(f"Unknown register area {function}")
    number = int(number)
    if addressing == "protocol":
        if number < 0:
            raise ValueError("Protocol address must be 0 or greater")
        return number
    if addressing != "modicon":
        raise ValueError("Addressing must be modicon or protocol")
    if function == "coil":
        if 1 <= number <= 9999:
            return number - 1
        raise ValueError("Coil Modicon address must be 1–9999 (00001 style)")
    if function == "discrete":
        if 10001 <= number <= 19999:
            return number - 10001
        raise ValueError("Discrete Modicon address must be 10001–19999")
    if function == "input":
        if 30001 <= number <= 39999:
            return number - 30001
        raise ValueError("Input Modicon address must be 30001–39999")
    if 40001 <= number <= 49999:
        return number - 40001
    raise ValueError("Holding Modicon address must be 40001–49999")


def _to_bytes(registers: list[int], order: str) -> bytes:
    regs = [int(r) & 0xFFFF for r in registers]
    if order == "ABCD":
        return b"".join(struct.pack(">H", r) for r in regs)
    if order == "CDAB":
        swapped: list[int] = []
        for i in range(0, len(regs), 2):
            pair = regs[i : i + 2]
            swapped.extend((pair[1], pair[0]) if len(pair) == 2 else pair)
        return b"".join(struct.pack(">H", r) for r in swapped)
    if order == "BADC":
        return b"".join(struct.pack("<H", r) for r in regs)
    if order == "DCBA":
        return b"".join(struct.pack("<H", r) for r in reversed(regs))
    raise ValueError(f"Unknown byte order {order}")


def _from_bytes(payload: bytes, order: str) -> list[int]:
    count = len(payload) // 2
    if order == "ABCD":
        return list(struct.unpack(">" + "H" * count, payload))
    if order == "BADC":
        return list(struct.unpack("<" + "H" * count, payload))
    if order == "CDAB":
        regs = list(struct.unpack(">" + "H" * count, payload))
        swapped: list[int] = []
        for i in range(0, len(regs), 2):
            pair = regs[i : i + 2]
            swapped.extend((pair[1], pair[0]) if len(pair) == 2 else pair)
        return swapped
    if order == "DCBA":
        regs = list(struct.unpack("<" + "H" * count, payload))
        return list(reversed(regs))
    raise ValueError(f"Unknown byte order {order}")


def decode_registers(
    registers: list[int],
    dtype: str,
    order: str = "ABCD",
    bit: int | None = None,
) -> bool | int | float:
    if dtype == "bool":
        if not registers:
            raise ValueError("No register for a boolean point")
        word = int(registers[0]) & 0xFFFF
        if bit is None:
            return bool(word)
        if not 0 <= int(bit) <= 15:
            raise ValueError("Bit must be 0–15")
        return bool((word >> int(bit)) & 1)
    count = register_count(dtype)
    if len(registers) < count:
        raise ValueError(f"{dtype} needs {count} registers")
    payload = _to_bytes(registers[:count], order)
    value = struct.unpack(">" + _UNPACK[dtype], payload)[0]
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("Non-finite float from registers")
    return value


def encode_registers(value: int | float, dtype: str, order: str = "ABCD") -> list[int]:
    if dtype in _RANGES:
        ivalue = int(value)
        lo, hi = _RANGES[dtype]
        if not lo <= ivalue <= hi:
            raise ValueError(f"{dtype} raw value {ivalue} is outside {lo}–{hi}")
        payload = struct.pack(">" + _UNPACK[dtype], ivalue)
    elif dtype == "float32":
        payload = struct.pack(">f", float(value))
    elif dtype == "float64":
        payload = struct.pack(">d", float(value))
    else:
        raise ValueError(f"Cannot encode data type {dtype}")
    return _from_bytes(payload, order)


def engineering_from_raw(point: dict, raw: list) -> bool | float:
    function = point["function"]
    if function in ("coil", "discrete"):
        if not raw:
            raise ValueError("Empty bit response")
        value = bool(raw[0])
        if point.get("invert"):
            value = not value
        return value

    dtype = point["dtype"]
    if dtype == "bool":
        value = bool(decode_registers(raw, "bool", bit=point.get("bit")))
        if point.get("invert"):
            value = not value
        return value

    number = decode_registers(raw, dtype, point.get("byte_order") or "ABCD")
    scale = float(point.get("scale", 1))
    offset = float(point.get("offset", 0))
    return float(number) * scale + offset


def encode_numeric(point: dict, engineering: float) -> list[int]:
    scale = float(point.get("scale", 1))
    if scale == 0:
        raise ValueError("Scale is 0, so this point cannot be written")
    raw = (float(engineering) - float(point.get("offset", 0))) / scale
    if point["dtype"] in _RANGES:
        raw = int(round(raw))
    return encode_registers(raw, point["dtype"], point.get("byte_order") or "ABCD")


def wire_bool(point: dict, engineering: bool) -> bool:
    flag = bool(engineering)
    if point.get("invert"):
        flag = not flag
    return flag


def format_value(point: dict, value) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool) or point["dtype"] == "bool" or point["function"] in ("coil", "discrete"):
        return str(point.get("on_label") or "On") if value else str(point.get("off_label") or "Off")
    decimals = int(point.get("decimals", 0))
    return f"{float(value):.{decimals}f}"


def in_alarm(point: dict, value) -> bool:
    if value is None:
        return False
    is_bool = (
        isinstance(value, bool)
        or point["dtype"] == "bool"
        or point["function"] in ("coil", "discrete")
    )
    if is_bool:
        return bool(value) if point.get("widget") == "alarm" else False
    if point.get("alarm_high") is not None and float(value) > float(point["alarm_high"]):
        return True
    if point.get("alarm_low") is not None and float(value) < float(point["alarm_low"]):
        return True
    return False
