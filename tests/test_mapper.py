"""Passive Modbus RTU/ASCII capture and replay onto the plant page."""

import asyncio

import pytest
from fastapi.testclient import TestClient

from app.mapper import Mapper, configure_listen_only, mapper
from app.modbus_serial import (
    AsciiAssembler,
    RtuAssembler,
    ascii_frame,
    parse_ascii,
    parse_rtu,
    rtu_frame,
)
from app.modbus_tcp import ModbusError, ModbusTcpClient


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("CHILLER_DATA", str(tmp_path))
    mapper.reset()
    yield
    asyncio.run(mapper.shutdown())


def test_crc_and_gap_framing():
    body = bytes.fromhex("01030000000A")
    frame = rtu_frame(body)
    assert frame.hex().upper() == "01030000000AC5CD"
    parsed = parse_rtu(frame)
    assert parsed["ok"] is True
    assert parsed["role"] == "request"
    assert parsed["unit"] == 1
    bad = bytearray(frame)
    bad[-1] ^= 0xFF
    assert parse_rtu(bytes(bad))["ok"] is False
    assembler = RtuAssembler(0.01)
    assert assembler.feed(frame[:3], 1.0) == []
    assert assembler.feed(frame[3:], 1.004) == []
    assert assembler.flush(1.02) == [frame]


def test_ascii_frame_round_trip():
    frame = ascii_frame(bytes.fromhex("010300000001"))
    parsed = parse_ascii(frame)
    assert parsed["ok"] is True
    assert parsed["role"] == "request"
    assembled = AsciiAssembler().feed(b"noise" + frame)
    assert assembled == [frame]


def test_listen_only_setup_does_not_write():
    class Port:
        def __init__(self):
            self.is_open = False
            self.rts = True
            self.dtr = True
            self.writes = []

        def open(self):
            self.is_open = True

        def write(self, data):
            self.writes.append(data)

    port = Port()
    configure_listen_only(port)
    assert port.is_open is True
    assert port.rts is False
    assert port.dtr is False
    assert port.writes == []


def test_capture_builds_a_map_and_ignores_bad_frames():
    session = Mapper()
    session.mapping = True
    session.observe_raw(rtu_frame(bytes.fromhex("010300000001")))
    session.observe_raw(rtu_frame(bytes.fromhex("0103020048")))
    session.observe_raw(bytes.fromhex("010300000001FFFF"))
    point = session.snapshot()["points"][0]
    assert point["id"] == "u1_h_0"
    assert point["display"] == "72"
    assert point["function"] == "holding"
    assert session.noise == 1
    session.update_point(point["id"], {**point, "scale": 0.1, "decimals": 1, "name": "Supply"})
    assert session.snapshot()["points"][0]["display"] == "7.2"
    assert session.snapshot()["points"][0]["address_number"] == 0
    session.update_point(point["id"], {"addressing": "modicon"})
    assert session.snapshot()["points"][0]["address_number"] == 40001


def test_write_and_exception():
    session = Mapper()
    session.mapping = True
    write = rtu_frame(bytes.fromhex("010600020041"))
    session.observe_raw(write)
    session.observe_raw(write)
    point = session.snapshot()["points"][0]
    assert point["address_number"] == 2
    assert point["display"] == "65"
    assert point["writable"] is True
    before = len(session.points)
    session.observe_raw(rtu_frame(bytes.fromhex("0103000A0001")))
    session.observe_raw(rtu_frame(bytes.fromhex("018302")))
    assert len(session.points) == before


def test_multiple_register_write():
    session = Mapper()
    session.mapping = True
    request = rtu_frame(bytes.fromhex("0110000A00020400010002"))
    response = rtu_frame(bytes.fromhex("0110000A0002"))
    session.observe_raw(request)
    session.observe_raw(response)
    values = {point["address_number"]: point["display"] for point in session.snapshot()["points"]}
    assert values[10] == "1"
    assert values[11] == "2"


def test_replay_serves_the_captured_register():
    asyncio.run(replay_scenario())


async def replay_scenario():
    mapper.mapping = True
    mapper.observe_raw(rtu_frame(bytes.fromhex("010300000001")))
    mapper.observe_raw(rtu_frame(bytes.fromhex("0103020048")))
    await mapper.start_replay(None, 0)
    client = ModbusTcpClient("127.0.0.1", mapper.replay_port, 1, 1)
    try:
        assert await client.read_holding(0, 1) == [72]
        assert await client.read_holding(0, 2) == [72, 0]
    finally:
        await client.close()
        await mapper.stop_replay()


def test_plant_page_reads_the_replay():
    import time

    from app.main import app

    mapper.mapping = True
    mapper.observe_raw(rtu_frame(bytes.fromhex("010300000001")))
    mapper.observe_raw(rtu_frame(bytes.fromhex("0103020048")))
    with TestClient(app) as client:
        planted = client.post(
            "/api/mapper/plant",
            json={"unit": 1, "name": "Captured chiller", "replace": True},
        )
        assert planted.status_code == 200, planted.text
        site = planted.json()["site"]
        assert site["modbus_host"] == "127.0.0.1"
        assert site["layout"]["profile"] is True
        assert site["layout"]["mimic"] is False
        assert any(point["id"] == "u1_h_0" for point in site["points"])
        display = None
        for _ in range(40):
            live = client.get("/api/live").json()
            reading = (live.get("values") or {}).get("u1_h_0")
            if reading and reading.get("quality") == "good":
                display = reading.get("display")
                break
            time.sleep(0.05)
        assert display == "72"


def test_replay_of_an_exception_is_returned_to_the_client():
    asyncio.run(exception_scenario())


async def exception_scenario():
    mapper.observe_raw(rtu_frame(bytes.fromhex("0103000A0001")))
    mapper.observe_raw(rtu_frame(bytes.fromhex("018302")))
    await mapper.start_replay(None, 0)
    client = ModbusTcpClient("127.0.0.1", mapper.replay_port, 1, 1)
    try:
        with pytest.raises(ModbusError) as caught:
            await client.read_holding(10, 1)
        assert caught.value.code == 2
    finally:
        await client.close()
        await mapper.stop_replay()


def test_http_rejects_capture_without_a_port():
    from app.main import app

    with TestClient(app) as client:
        refused = client.post("/api/mapper/capture/start", json={"port": "", "baud": 9600})
        assert refused.status_code == 400
        state = client.get("/api/mapper")
        assert state.status_code == 200
        body = state.json()
        assert body["capturing"] is False
        assert body["mapping"] is False
        assert body["replace"] is False


def test_mapping_stays_off_until_turned_on():
    session = Mapper()
    session.observe_raw(rtu_frame(bytes.fromhex("010300000001")))
    session.observe_raw(rtu_frame(bytes.fromhex("0103020048")))
    assert session.snapshot()["points"] == []
    assert session.snapshot()["exchange_count"] == 1
    session.update_settings({**session.settings, "mapping": True})
    point = session.snapshot()["points"][0]
    assert point["id"] == "u1_h_0"
    assert point["display"] == "72"
    session.update_settings({**session.settings, "mapping": False})
    session.observe_raw(rtu_frame(bytes.fromhex("010300010001")))
    session.observe_raw(rtu_frame(bytes.fromhex("0103020007")))
    assert [point["id"] for point in session.snapshot()["points"]] == ["u1_h_0"]


def test_replace_off_keeps_the_site_map_and_loaded_recording():
    from app.main import app
    from app.store import create_site

    mapper.mapping = True
    mapper.observe_raw(rtu_frame(bytes.fromhex("010300000001")))
    mapper.observe_raw(rtu_frame(bytes.fromhex("0103020048")))
    site = create_site("Plant room")
    original = [point["id"] for point in site["points"]]
    with TestClient(app) as client:
        kept = client.post(
            "/api/mapper/plant",
            json={"unit": 1, "name": "Should not replace", "replace": False, "site_id": site["id"]},
        )
        assert kept.status_code == 200, kept.text
        opened = kept.json()["site"]
        assert opened["id"] == site["id"]
        assert opened["modbus_host"] == "127.0.0.1"
        assert [point["id"] for point in opened["points"]] == original
        assert kept.json()["mapper"]["replace"] is False
        loaded = client.post(
            "/api/mapper/recordings/import?replace=false",
            json={
                "name": "Other capture",
                "exchanges": [{"unit": 1, "request": "010300020001", "response": "0103020009"}],
            },
        )
        assert loaded.status_code == 200, loaded.text
        assert any(point["id"] == "u1_h_0" for point in loaded.json()["points"])
        assert any(item["name"] == "Other capture" for item in loaded.json()["recordings"])
