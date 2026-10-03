"""Group point reads into the fewest Modbus requests that stay correct."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.decode import register_count, string_registers, wire_address


@dataclass
class Span:
    point_id: str
    function: str
    address: int
    count: int


@dataclass
class Block:
    function: str
    address: int
    count: int
    spans: list[Span] = field(default_factory=list)


def span_for(point: dict) -> Span:
    address = wire_address(point["function"], point["address_number"], point["addressing"])
    if point["function"] in ("coil", "discrete") or point["dtype"] == "bool":
        count = 1
    elif point["dtype"] == "string":
        count = string_registers(point)
    else:
        count = register_count(point["dtype"])
    return Span(point["id"], point["function"], address, count)


def plan_reads(points: list[dict], max_gap: int = 2, max_count: int = 120) -> list[Block]:
    grouped: dict[str, list[Span]] = {}
    for point in points:
        if not point.get("enabled", True):
            continue
        span = span_for(point)
        grouped.setdefault(span.function, []).append(span)

    blocks: list[Block] = []
    for function, spans in grouped.items():
        spans.sort(key=lambda item: (item.address, item.point_id))
        current: Block | None = None
        for span in spans:
            end = span.address + span.count
            if current is None:
                current = Block(function, span.address, span.count, [span])
                continue
            current_end = current.address + current.count
            new_count = max(current_end, end) - current.address
            gap = span.address - current_end
            if gap <= max_gap and new_count <= max_count:
                current.count = new_count
                current.spans.append(span)
            else:
                blocks.append(current)
                current = Block(function, span.address, span.count, [span])
        if current is not None:
            blocks.append(current)
    return blocks
