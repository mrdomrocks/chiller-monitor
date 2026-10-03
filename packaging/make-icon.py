"""Draw the Chiller Monitor icon. No image library required."""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

SIZE = 256
AMBER = (255, 193, 74, 255)
INK = (16, 22, 20, 255)
COLD = (98, 224, 192, 255)


def _rounded(x: int, y: int, size: int, margin: int, radius: int) -> bool:
    left, right = margin, size - 1 - margin
    top, bottom = margin, size - 1 - margin
    if x < left or x > right or y < top or y > bottom:
        return False
    cx = left + radius if x < left + radius else right - radius if x > right - radius else x
    cy = top + radius if y < top + radius else bottom - radius if y > bottom - radius else y
    dx, dy = x - cx, y - cy
    return dx * dx + dy * dy <= radius * radius


def _pixel(x: int, y: int) -> tuple[int, int, int, int]:
    if not _rounded(x, y, SIZE, 16, 48):
        return (0, 0, 0, 0)
    cx = (SIZE - 1) / 2
    cy = (SIZE - 1) / 2
    dx, dy = x - cx, y - cy
    distance = (dx * dx + dy * dy) ** 0.5
    if distance < 78 and abs(dy) <= 16 and abs(dx) < 62:
        return COLD
    if distance < 86:
        return INK
    return AMBER


def _png(size: int) -> bytes:
    raw = bytearray()
    for y in range(size):
        raw.append(0)
        for x in range(size):
            raw.extend(_pixel(x, y))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(bytes(raw), 9)) + chunk(b"IEND", b"")


def _ico(png: bytes) -> bytes:
    header = struct.pack("<HHH", 0, 1, 1)
    entry = struct.pack("<BBBBHHII", 0, 0, 0, 0, 1, 32, len(png), 22)
    return header + entry + png


def main() -> None:
    out = Path(__file__).resolve().parent / "icons"
    out.mkdir(parents=True, exist_ok=True)
    png = _png(SIZE)
    (out / "chiller-monitor.png").write_bytes(png)
    (out / "chiller-monitor.ico").write_bytes(_ico(png))


if __name__ == "__main__":
    main()
