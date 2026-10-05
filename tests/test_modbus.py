"""Modbus TCP and RTU-over-TCP clients against an in-process device."""

import asyncio

import pytest

from app.decode import engineering_from_raw
from app.modbus_serial import parse_rtu, rtu_frame, rtu_response_length
from app.modbus_tcp import ModbusDevice, ModbusError, ModbusTcpClient, serve_device


def test_read_write_and_wrong_unit():
    asyncio.run(scenario())


async def scenario():
    device = ModbusDevice(unit=1)
    device.holding[0] = 72
    device.holding[8] = 0b1010
    server = await serve_device(device, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    client = ModbusTcpClient("127.0.0.1", port, 1, 1)
    try:
        assert await client.read_holding(0, 1) == [72]
        point = {"function": "holding", "dtype": "bool", "bit": 3, "invert": False}
        regs = await client.read_holding(8, 1)
        assert engineering_from_raw(point, regs) is True
        await client.write_register(2, 65)
        assert device.holding[2] == 65
        await client.write_coil(0, False)
        assert device.coils[0] is False
        other = ModbusTcpClient("127.0.0.1", port, 9, 1)
        with pytest.raises(ModbusError) as caught:
            await other.read_holding(0, 1)
        assert caught.value.code == 11
        await other.close()
    finally:
        await client.close()
        server.close()
        await server.wait_closed()


def test_rtu_response_length_follows_the_header():
    assert rtu_response_length(b"") is None
    assert rtu_response_length(bytes.fromhex("0103")) is None
    assert rtu_response_length(bytes.fromhex("010302")) == 7
    assert rtu_response_length(bytes.fromhex("0183")) == 5
    assert rtu_response_length(bytes.fromhex("0106")) == 8


def test_rtu_over_tcp_reads_and_writes():
    asyncio.run(rtu_scenario())


async def _read_rtu_request(reader: asyncio.StreamReader) -> bytes:
    head = bytearray(await reader.readexactly(2))
    function = head[1]
    if function in (1, 2, 3, 4, 5, 6):
        head.extend(await reader.readexactly(6))
    elif function == 16:
        head.extend(await reader.readexactly(5))
        head.extend(await reader.readexactly(head[6] + 2))
    else:
        raise RuntimeError(f"unexpected function {function}")
    return bytes(head)


async def _serve_rtu(device: ModbusDevice, split: bool = False):
    async def on_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            while True:
                frame = await _read_rtu_request(reader)
                parsed = parse_rtu(frame)
                assert parsed and parsed["ok"]
                pdu = device.handle(parsed["unit"], parsed["pdu"])
                response = rtu_frame(bytes([parsed["unit"]]) + pdu)
                if split:
                    writer.write(response[:3])
                    await writer.drain()
                    await asyncio.sleep(0.02)
                    writer.write(response[3:])
                else:
                    writer.write(response)
                await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionError, AssertionError):
            pass
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    return await asyncio.start_server(on_client, "127.0.0.1", 0)


async def rtu_scenario():
    device = ModbusDevice(unit=1)
    device.holding[0] = 72
    device.coils[1] = True
    server = await _serve_rtu(device, split=True)
    port = server.sockets[0].getsockname()[1]
    client = ModbusTcpClient("127.0.0.1", port, 1, 1)
    client.framing = "rtu"
    client.inter_frame_s = 0.01
    try:
        assert await client.read_holding(0, 1) == [72]
        await client.write_register(2, 65)
        assert device.holding[2] == 65
        assert await client.read_coils(1, 1) == [True]
        await client.write_registers(4, [1, 2])
        assert device.holding[4:6] == [1, 2]
        other = ModbusTcpClient("127.0.0.1", port, 9, 1)
        other.framing = "rtu"
        with pytest.raises(ModbusError) as caught:
            await other.read_holding(0, 1)
        assert caught.value.code == 11
        await other.close()
    finally:
        await client.close()
        server.close()
        await server.wait_closed()


def test_monitor_reads_an_rtu_over_tcp_gateway(tmp_path, monkeypatch):
    monkeypatch.setenv("CHILLER_DATA", str(tmp_path))
    asyncio.run(monitor_rtu())


async def monitor_rtu():
    from app.monitor import Monitor
    from app.store import create_site, update_site

    device = ModbusDevice(unit=1)
    device.holding[0] = 72
    server = await _serve_rtu(device)
    port = server.sockets[0].getsockname()[1]
    site = create_site("Gateway")
    update_site(
        site["id"],
        {
            "name": "Gateway",
            "protocol": "rtu",
            "modbus_host": "127.0.0.1",
            "modbus_port": port,
            "inter_frame_ms": 5,
            "poll_ms": 200,
            "timeout_s": 1,
        },
    )
    monitor = Monitor()
    try:
        await monitor.connect(site["id"])
        supply = None
        snap = {}
        for _ in range(30):
            await asyncio.sleep(0.1)
            snap = monitor.snapshot()
            supply = snap["values"].get("chw_supply")
            if supply and supply["quality"] == "good":
                break
        assert supply is not None
        assert supply["quality"] == "good"
        assert supply["value"] == 7.2
        assert snap["modbus"]["state"] == "polling"
        assert snap["modbus"]["protocol"] == "rtu"
    finally:
        await monitor.shutdown()
        server.close()
        await server.wait_closed()


def test_rtu_over_tcp_rejects_a_bad_crc():
    asyncio.run(bad_crc_scenario())


async def bad_crc_scenario():
    async def on_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            await _read_rtu_request(reader)
            writer.write(bytes.fromhex("01030200480000"))
            await writer.drain()
            await asyncio.sleep(0.2)
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            writer.close()

    server = await asyncio.start_server(on_client, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    client = ModbusTcpClient("127.0.0.1", port, 1, 1)
    client.framing = "rtu"
    try:
        with pytest.raises(ModbusError) as caught:
            await client.read_holding(0, 1)
        assert "CRC" in str(caught.value)
        assert client.connected is False
    finally:
        await client.close()
        server.close()
        await server.wait_closed()
