"""Modbus TCP client against the in-process demo device."""

import asyncio

import pytest

from app.decode import engineering_from_raw
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
