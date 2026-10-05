"""Register decoding, block planning, and the Modbus TCP stack."""

import struct

import pytest

from app.blocks import plan_reads
from app.blocks import span_for
from app.decode import (
    decode_registers,
    describe_write,
    encode_registers,
    encode_string,
    engineering_from_raw,
    wire_address,
)
from app.template import default_bindings, default_points


def test_modicon_and_protocol_addresses():
    assert wire_address("holding", 40001, "modicon") == 0
    assert wire_address("input", 30002, "modicon") == 1
    assert wire_address("coil", 1, "modicon") == 0
    assert wire_address("discrete", 10001, "modicon") == 0
    assert wire_address("holding", 12, "protocol") == 12
    with pytest.raises(ValueError):
        wire_address("coil", 40001, "modicon")


def test_float_orders_match_struct():
    canonical = list(struct.unpack(">HH", struct.pack(">f", 12.5)))
    assert decode_registers(canonical, "float32", "ABCD") == pytest.approx(12.5)
    assert decode_registers([canonical[1], canonical[0]], "float32", "CDAB") == pytest.approx(12.5)

    raw = struct.pack(">f", 12.5)
    swapped = bytes([raw[1], raw[0], raw[3], raw[2]])
    badc_regs = list(struct.unpack(">HH", swapped))
    assert decode_registers(badc_regs, "float32", "BADC") == pytest.approx(12.5)
    dcba = list(struct.unpack(">HH", bytes(reversed(raw))))
    assert decode_registers(dcba, "float32", "DCBA") == pytest.approx(12.5)
    assert encode_registers(12.5, "float32", "ABCD") == canonical


def test_int16_scale_and_packed_bit():
    point = {
        "function": "holding",
        "dtype": "int16",
        "byte_order": "ABCD",
        "scale": 0.1,
        "offset": 0,
    }
    assert engineering_from_raw(point, [72]) == pytest.approx(7.2)
    alarm = {
        "function": "holding",
        "dtype": "bool",
        "bit": 3,
        "invert": False,
    }
    assert engineering_from_raw(alarm, [0b1000]) is True
    assert engineering_from_raw(alarm, [0b0111]) is False


def test_read_plan_merges_status_word_and_keeps_coils_separate():
    points = [point for point in default_points() if point["id"] in {"chw_supply", "chw_return", "compressor", "general_alarm", "enable"}]
    blocks = plan_reads(points)
    functions = {block.function for block in blocks}
    assert functions == {"holding", "coil"}
    status = next(block for block in blocks if any(span.point_id == "general_alarm" for span in block.spans))
    assert any(span.point_id == "compressor" for span in status.spans)
    assert status.count == 1
    coil = next(block for block in blocks if block.function == "coil")
    assert coil.address == 0
    assert coil.count == 1


def test_chiller_name_is_text_and_blank_when_unprogrammed():
    point = next(item for item in default_points() if item["id"] == "chiller_name")
    assert point["dtype"] == "string"
    assert point["widget"] == "hidden"
    assert default_bindings()["chiller_name"] == "chiller_name"
    assert span_for(point).count == 8
    stored = {
        "function": "holding",
        "dtype": "string",
        "byte_order": "ABCD",
        "string_chars": 16,
    }
    assert engineering_from_raw(stored, encode_string("Plant 1", 16)) == "Plant 1"
    assert engineering_from_raw(stored, [0] * 8) == ""
    assert engineering_from_raw(stored, [0x2020] * 8) == ""


def test_negative_int16_roundtrip():
    encoded = encode_registers(-50, "int16", "ABCD")
    assert decode_registers(encoded, "int16", "ABCD") == -50


def _point(point_id):
    return next(item for item in default_points() if item["id"] == point_id)


def test_float_setpoint_is_two_registers():
    point = _point("setpoint")
    capacity = _point("capacity")
    assert point["dtype"] == "float32"
    assert span_for(point).count == 2
    assert span_for(point).address == 2
    assert span_for(capacity).address == 9
    plan = describe_write(point, 7.5)
    assert plan["function"] == 16
    assert plan["address"] == 2
    assert plan["registers"] == [16624, 0]
    assert "IEEE 754" in plan["text"]
    assert "ABCD" in plan["text"]
    assert "Function 16" in plan["text"]
    assert "40003 is protocol address 2." in plan["text"]
    assert "40003 = 16624 (0x40F0)" in plan["text"]
    assert "40004 = 0 (0x0000)" in plan["text"]


def test_cdab_writes_the_low_word_first():
    point = {**_point("setpoint"), "byte_order": "CDAB"}
    plan = describe_write(point, 7.5)
    assert plan["registers"] == [0, 16624]
    assert "CDAB swaps the two words" in plan["text"]
    assert "40003 = 0 (0x0000)" in plan["text"]
    assert "40004 = 16624 (0x40F0)" in plan["text"]


def test_scaled_integer_is_not_described_as_a_float():
    plan = describe_write(_point("chw_supply"), 7.5)
    assert plan["function"] == 6
    assert plan["registers"] == [75]
    assert "not as a float" in plan["text"]
    assert "Register = (7.5 − 0) / 0.1 = 75." in plan["text"]
    assert "40001 = 75 (0x004B)" in plan["text"]


def test_write_plan_rejects_a_setpoint_outside_the_limit():
    with pytest.raises(ValueError, match="minimum"):
        describe_write(_point("setpoint"), 3)
