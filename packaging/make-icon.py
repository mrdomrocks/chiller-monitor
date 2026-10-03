"""Build the app icon from the Aqua Cooling A on a grey background."""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

SIZE = 256
GREY = (107, 111, 116, 255)
HERE = Path(__file__).resolve().parent
WORDMARK = HERE / "icons" / "aqua-wordmark.png"


def _paeth(a: int, b: int, c: int) -> int:
    estimate = a + b - c
    da, db, dc = abs(estimate - a), abs(estimate - b), abs(estimate - c)
    if da <= db and da <= dc:
        return a
    return b if db <= dc else c


def read_png(path: Path) -> tuple[int, int, list[bytearray]]:
    data = path.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"{path} is not a PNG")
    pos = 8
    width = height = 0
    idat = b""
    while pos < len(data):
        length = struct.unpack(">I", data[pos : pos + 4])[0]
        tag = data[pos + 4 : pos + 8]
        chunk = data[pos + 8 : pos + 8 + length]
        pos += 12 + length
        if tag == b"IHDR":
            width, height, bit, color, *_rest = struct.unpack(">IIBBBBB", chunk)
            if bit != 8 or color != 6:
                raise ValueError("The wordmark must be 8-bit RGBA")
        elif tag == b"IDAT":
            idat += chunk
        elif tag == b"IEND":
            break
    raw = zlib.decompress(idat)
    rows: list[bytearray] = []
    stride = width * 4
    index = 0
    previous = bytearray(stride)
    for _y in range(height):
        filter_type = raw[index]
        index += 1
        row = bytearray(raw[index : index + stride])
        index += stride
        if filter_type == 1:
            for x in range(stride):
                left = row[x - 4] if x >= 4 else 0
                row[x] = (row[x] + left) & 255
        elif filter_type == 2:
            for x in range(stride):
                row[x] = (row[x] + previous[x]) & 255
        elif filter_type == 3:
            for x in range(stride):
                left = row[x - 4] if x >= 4 else 0
                row[x] = (row[x] + ((left + previous[x]) // 2)) & 255
        elif filter_type == 4:
            for x in range(stride):
                left = row[x - 4] if x >= 4 else 0
                up = previous[x]
                up_left = previous[x - 4] if x >= 4 else 0
                row[x] = (row[x] + _paeth(left, up, up_left)) & 255
        elif filter_type != 0:
            raise ValueError(f"Unsupported PNG filter {filter_type}")
        previous = row
        rows.append(row)
    return width, height, rows


def _ink(rows: list[bytearray], x: int, y: int) -> bool:
    offset = x * 4
    red, green, blue, alpha = rows[y][offset : offset + 4]
    return alpha > 30 and red + green + blue > 300


def letter_a(width: int, height: int, rows: list[bytearray]) -> tuple[bytearray, tuple[int, int, int, int]]:
    """The A is the first connected shape. The q sits close enough to overlap its box."""
    mask = bytearray(width * height)
    seed = next(
        (x, y)
        for x in range(width)
        for y in range(height)
        if _ink(rows, x, y)
    )
    stack = [seed]
    left = top = 10**9
    right = bottom = 0
    while stack:
        x, y = stack.pop()
        if not (0 <= x < width and 0 <= y < height):
            continue
        index = y * width + x
        if mask[index] or not _ink(rows, x, y):
            continue
        mask[index] = 1
        left, top = min(left, x), min(top, y)
        right, bottom = max(right, x), max(bottom, y)
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                stack.append((x + dx, y + dy))
    return mask, (left, top, right, bottom)


def _rounded(x: int, y: int, size: int, margin: int, radius: int) -> bool:
    left, right = margin, size - 1 - margin
    top, bottom = margin, size - 1 - margin
    if x < left or x > right or y < top or y > bottom:
        return False
    corner_x = left + radius if x < left + radius else right - radius if x > right - radius else x
    corner_y = top + radius if y < top + radius else bottom - radius if y > bottom - radius else y
    dx, dy = x - corner_x, y - corner_y
    return dx * dx + dy * dy <= radius * radius


def _pixel(rows: list[bytearray], mask: bytearray, x: int, y: int, width: int, height: int) -> tuple[int, int, int, int]:
    if not (0 <= x < width and 0 <= y < height) or not mask[y * width + x]:
        return (0, 0, 0, 0)
    offset = x * 4
    return tuple(rows[y][offset : offset + 4])  # type: ignore[return-value]


def _sample(
    rows: list[bytearray],
    mask: bytearray,
    x: float,
    y: float,
    width: int,
    height: int,
) -> tuple[int, int, int, int]:
    x = min(width - 1, max(0, x))
    y = min(height - 1, max(0, y))
    x0, y0 = int(x), int(y)
    fx, fy = x - x0, y - y0
    samples = (
        _pixel(rows, mask, x0, y0, width, height),
        _pixel(rows, mask, x0 + 1, y0, width, height),
        _pixel(rows, mask, x0, y0 + 1, width, height),
        _pixel(rows, mask, x0 + 1, y0 + 1, width, height),
    )
    weights = ((1 - fx) * (1 - fy), fx * (1 - fy), (1 - fx) * fy, fx * fy)
    channels = [0.0, 0.0, 0.0, 0.0]
    for sample, weight in zip(samples, weights):
        for index, value in enumerate(sample):
            channels[index] += value * weight
    return tuple(int(value) for value in channels)  # type: ignore[return-value]


def render(
    rows: list[bytearray],
    mask: bytearray,
    bounds: tuple[int, int, int, int],
    source_width: int,
    source_height: int,
) -> bytes:
    left, top, right, bottom = bounds
    glyph_w = right - left + 1
    glyph_h = bottom - top + 1
    margin = 28
    available = SIZE - margin * 2
    scale = min(available / glyph_w, available / glyph_h)
    drawn_w = glyph_w * scale
    drawn_h = glyph_h * scale
    origin_x = (SIZE - drawn_w) / 2
    origin_y = (SIZE - drawn_h) / 2
    raw = bytearray()
    for y in range(SIZE):
        raw.append(0)
        for x in range(SIZE):
            if not _rounded(x, y, SIZE, 8, 48):
                raw.extend((0, 0, 0, 0))
                continue
            sx = left + (x + 0.5 - origin_x) / scale
            sy = top + (y + 0.5 - origin_y) / scale
            if sx < left or sy < top or sx > right + 1 or sy > bottom + 1:
                raw.extend(GREY)
                continue
            red, green, blue, alpha = _sample(rows, mask, sx, sy, source_width, source_height)
            cover = alpha / 255
            raw.extend(
                (
                    int(GREY[0] * (1 - cover) + red * cover),
                    int(GREY[1] * (1 - cover) + green * cover),
                    int(GREY[2] * (1 - cover) + blue * cover),
                    255,
                )
            )
    return _png(raw)


def _png(raw: bytes) -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", SIZE, SIZE, 8, 6, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")


def _ico(png: bytes) -> bytes:
    header = struct.pack("<HHH", 0, 1, 1)
    entry = struct.pack("<BBBBHHII", 0, 0, 0, 0, 1, 32, len(png), 22)
    return header + entry + png


def main() -> None:
    width, height, rows = read_png(WORDMARK)
    mask, bounds = letter_a(width, height, rows)
    png = render(rows, mask, bounds, width, height)
    out = HERE / "icons"
    (out / "chiller-monitor.png").write_bytes(png)
    (out / "chiller-monitor.ico").write_bytes(_ico(png))


if __name__ == "__main__":
    main()
