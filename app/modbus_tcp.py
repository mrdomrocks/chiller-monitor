"""A small Modbus TCP client and server for the function codes a chiller needs.

Function codes: 1, 2, 3, 4, 5, 6 and 16.
"""

from __future__ import annotations

import asyncio
import socket
import struct

EXCEPTION_TEXT = {
    1: "illegal function",
    2: "illegal data address",
    3: "illegal data value",
    4: "server device failure",
    10: "gateway path unavailable",
    11: "gateway target device failed to respond",
}


class ModbusError(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code


class _Reject(Exception):
    def __init__(self, code: int):
        super().__init__(EXCEPTION_TEXT.get(code, "modbus error"))
        self.code = code


class ModbusDevice:
    """In-memory slave used by the demo chiller."""

    def __init__(self, unit: int = 1, size: int = 200):
        self.unit = unit
        self.holding = [0] * size
        self.inputs = [0] * size
        self.coils = [False] * size
        self.discrete = [False] * size

    def handle(self, unit: int, pdu: bytes) -> bytes:
        if not pdu:
            return bytes([0x80, 3])
        function = pdu[0]
        if unit != self.unit:
            return bytes([function | 0x80, 11])
        try:
            if function == 1:
                return self._read_bits(function, self.coils, pdu)
            if function == 2:
                return self._read_bits(function, self.discrete, pdu)
            if function == 3:
                return self._read_regs(function, self.holding, pdu)
            if function == 4:
                return self._read_regs(function, self.inputs, pdu)
            if function == 5:
                return self._write_coil(pdu)
            if function == 6:
                return self._write_single(pdu)
            if function == 16:
                return self._write_multi(pdu)
            return bytes([function | 0x80, 1])
        except _Reject as exc:
            return bytes([function | 0x80, exc.code])

    def _read_regs(self, function: int, registers: list[int], pdu: bytes) -> bytes:
        if len(pdu) != 5:
            raise _Reject(3)
        address, count = struct.unpack(">HH", pdu[1:5])
        if count < 1 or count > 125:
            raise _Reject(3)
        if address + count > len(registers):
            raise _Reject(2)
        payload = struct.pack(">" + "H" * count, *registers[address : address + count])
        return bytes([function, len(payload)]) + payload

    def _read_bits(self, function: int, bits: list[bool], pdu: bytes) -> bytes:
        if len(pdu) != 5:
            raise _Reject(3)
        address, count = struct.unpack(">HH", pdu[1:5])
        if count < 1 or count > 2000:
            raise _Reject(3)
        if address + count > len(bits):
            raise _Reject(2)
        packed = bytearray((count + 7) // 8)
        for index in range(count):
            if bits[address + index]:
                packed[index // 8] |= 1 << (index % 8)
        return bytes([function, len(packed)]) + bytes(packed)

    def _write_coil(self, pdu: bytes) -> bytes:
        if len(pdu) != 5:
            raise _Reject(3)
        address, value = struct.unpack(">HH", pdu[1:5])
        if address >= len(self.coils):
            raise _Reject(2)
        if value == 0xFF00:
            self.coils[address] = True
        elif value == 0x0000:
            self.coils[address] = False
        else:
            raise _Reject(3)
        return pdu

    def _write_single(self, pdu: bytes) -> bytes:
        if len(pdu) != 5:
            raise _Reject(3)
        address, value = struct.unpack(">HH", pdu[1:5])
        if address >= len(self.holding):
            raise _Reject(2)
        self.holding[address] = value
        return pdu

    def _write_multi(self, pdu: bytes) -> bytes:
        if len(pdu) < 6:
            raise _Reject(3)
        address, count, byte_count = struct.unpack(">HHB", pdu[1:6])
        data = pdu[6:]
        if count < 1 or count > 123 or byte_count != count * 2 or len(data) != byte_count:
            raise _Reject(3)
        if address + count > len(self.holding):
            raise _Reject(2)
        values = struct.unpack(">" + "H" * count, data)
        self.holding[address : address + count] = values
        return struct.pack(">BHH", 16, address, count)


def _frame(transaction: int, unit: int, pdu: bytes) -> bytes:
    return struct.pack(">HHHB", transaction, 0, 1 + len(pdu), unit) + pdu


async def _read_frame(reader: asyncio.StreamReader) -> tuple[int, int, bytes]:
    header = await reader.readexactly(6)
    transaction, protocol, length = struct.unpack(">HHH", header)
    if protocol != 0 or length < 2 or length > 260:
        raise ModbusError(3, "Malformed Modbus TCP header")
    rest = await reader.readexactly(length)
    return transaction, rest[0], rest[1:]


async def serve_device(device: ModbusDevice, host: str, port: int) -> asyncio.Server:
    async def on_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            while True:
                transaction, unit, pdu = await _read_frame(reader)
                response = device.handle(unit, pdu)
                writer.write(_frame(transaction, unit, response))
                await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionError, ModbusError):
            pass
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    return await asyncio.start_server(on_client, host, port)


class ModbusTcpClient:
    def __init__(self, host: str, port: int, unit: int, timeout: float):
        self.host = host
        self.port = int(port)
        self.unit = int(unit)
        self.timeout = float(timeout)
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._tid = 0
        self._io = asyncio.Lock()

    @property
    def connected(self) -> bool:
        return self._writer is not None and not self._writer.is_closing()

    async def connect(self) -> None:
        if self.connected:
            return
        try:
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port),
                self.timeout,
            )
        except TimeoutError as exc:
            raise TimeoutError(f"Timed out opening {self.host}:{self.port}") from exc
        except OSError as exc:
            raise ConnectionError(f"Cannot reach {self.host}:{self.port} ({exc})") from exc
        sock = self._writer.transport.get_extra_info("socket")
        if sock is not None:
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

    async def close(self) -> None:
        writer = self._writer
        self._writer = None
        self._reader = None
        if writer is None:
            return
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass

    async def read(self, function: str, address: int, count: int) -> list:
        if function == "holding":
            return await self.read_holding(address, count)
        if function == "input":
            return await self.read_input(address, count)
        if function == "coil":
            return await self.read_coils(address, count)
        if function == "discrete":
            return await self.read_discrete(address, count)
        raise ValueError(f"Unknown register area {function}")

    async def read_holding(self, address: int, count: int) -> list[int]:
        return await self._read_registers(3, address, count)

    async def read_input(self, address: int, count: int) -> list[int]:
        return await self._read_registers(4, address, count)

    async def read_coils(self, address: int, count: int) -> list[bool]:
        return await self._read_bits(1, address, count)

    async def read_discrete(self, address: int, count: int) -> list[bool]:
        return await self._read_bits(2, address, count)

    async def write_register(self, address: int, value: int) -> None:
        pdu = struct.pack(">BHH", 6, address, int(value) & 0xFFFF)
        await self._expect(pdu, 6, address)

    async def write_registers(self, address: int, values: list[int]) -> None:
        payload = struct.pack(">" + "H" * len(values), *[int(v) & 0xFFFF for v in values])
        pdu = struct.pack(">BHHB", 16, address, len(values), len(payload)) + payload
        response = await self._transact(pdu)
        if response[0] != 16:
            self._raise_function(response, 16)
        got_address, got_count = struct.unpack(">HH", response[1:5])
        if got_address != address or got_count != len(values):
            raise ModbusError(3, "Unexpected response to write multiple registers")

    async def write_coil(self, address: int, value: bool) -> None:
        code = 0xFF00 if value else 0x0000
        pdu = struct.pack(">BHH", 5, address, code)
        await self._expect(pdu, 5, address)

    async def _read_registers(self, function: int, address: int, count: int) -> list[int]:
        pdu = struct.pack(">BHH", function, address, count)
        response = await self._transact(pdu)
        if response[0] != function:
            self._raise_function(response, function)
        byte_count = response[1]
        data = response[2:]
        if byte_count != count * 2 or len(data) < byte_count:
            raise ModbusError(3, "Short register response")
        return list(struct.unpack(">" + "H" * count, data[:byte_count]))

    async def _read_bits(self, function: int, address: int, count: int) -> list[bool]:
        pdu = struct.pack(">BHH", function, address, count)
        response = await self._transact(pdu)
        if response[0] != function:
            self._raise_function(response, function)
        data = response[2 : 2 + response[1]]
        flags: list[bool] = []
        for index in range(count):
            if index // 8 >= len(data):
                raise ModbusError(3, "Short coil response")
            flags.append(bool((data[index // 8] >> (index % 8)) & 1))
        return flags

    async def _expect(self, pdu: bytes, function: int, address: int) -> None:
        response = await self._transact(pdu)
        if response[0] != function:
            self._raise_function(response, function)
        if response != pdu:
            got, _ = struct.unpack(">HH", response[1:5])
            if got != address:
                raise ModbusError(3, "Write response did not echo the address")

    async def _transact(self, pdu: bytes) -> bytes:
        async with self._io:
            await self.connect()
            assert self._reader is not None and self._writer is not None
            self._tid = self._tid + 1 if self._tid < 65535 else 1
            self._writer.write(_frame(self._tid, self.unit, pdu))
            try:
                await asyncio.wait_for(self._writer.drain(), self.timeout)
                transaction, _unit, response = await asyncio.wait_for(
                    _read_frame(self._reader),
                    self.timeout,
                )
            except TimeoutError as exc:
                await self.close()
                raise TimeoutError(
                    f"Timed out waiting for Modbus from {self.host}:{self.port}"
                ) from exc
            except (asyncio.IncompleteReadError, ConnectionError, OSError) as exc:
                await self.close()
                raise ConnectionError(f"Modbus connection to {self.host}:{self.port} dropped") from exc
            if transaction != self._tid:
                await self.close()
                raise ModbusError(3, "Modbus transaction id did not match")
            return response

    def _raise_function(self, response: bytes, function: int) -> None:
        if response and response[0] == (function | 0x80) and len(response) > 1:
            code = response[1]
            text = EXCEPTION_TEXT.get(code, "error")
            raise ModbusError(code, f"Modbus exception {code} ({text}) on function {function}")
        raise ModbusError(1, f"Unexpected Modbus response to function {function}")
