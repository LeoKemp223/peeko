import struct
import time
from dataclasses import dataclass

from peeko.config import (
    SOF, CMD_READ_VAR, CMD_WRITE_VAR, CMD_READ_RESP, CMD_WRITE_RESP,
    CMD_ERROR, CMD_PING, CMD_PONG, NO_BITFIELD, DEFAULT_TIMEOUT_MS,
    MAX_RETRIES, MAX_PAYLOAD_SIZE, ERROR_NAMES,
)


@dataclass
class VarInfo:
    """Variable descriptor matching MCU-side VAR_INFO (8 bytes)."""
    address: int    # 4 bytes, memory address
    size: int       # 2 bytes, variable size in bytes
    bit_offset: int = NO_BITFIELD  # 1 byte, 0xFF = not bitfield
    bit_size: int = NO_BITFIELD    # 1 byte, 0xFF = not bitfield

    def pack(self) -> bytes:
        return struct.pack("<IHBB", self.address, self.size,
                           self.bit_offset, self.bit_size)


def crc16_ccitt(data: bytes) -> int:
    """CRC16-CCITT identical to MCU rv_crc16_ccitt(). Poly=0x1021, Init=0xFFFF."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ 0x1021) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return crc


class ProtocolError(Exception):
    pass


class Protocol:
    """Serial protocol matching MCU peeko.c frame format."""

    def __init__(self, serial_port, little_endian=True):
        self._port = serial_port
        self._little_endian = little_endian
        self._seq = 0

    def _next_seq(self) -> int:
        seq = self._seq
        self._seq = (self._seq + 1) & 0xFF
        return seq

    def _build_frame(self, cmd: int, seq: int, payload: bytes) -> bytes:
        payload_len = len(payload)
        header = struct.pack("<BHBB", SOF, payload_len, cmd, seq)
        frame_without_crc = header + payload
        crc = crc16_ccitt(frame_without_crc)
        return frame_without_crc + struct.pack("<H", crc)

    def _send_frame(self, frame: bytes):
        self._port.write(frame)
        self._port.flush()

    def _receive_frame(self, timeout_ms: int = DEFAULT_TIMEOUT_MS):
        """Receive and parse one complete frame. Returns (cmd, seq, payload)."""
        deadline = time.time() + timeout_ms / 1000.0
        original_timeout = self._port.timeout
        self._port.timeout = max(0.01, timeout_ms / 1000.0)

        try:
            # Wait for SOF
            while True:
                if time.time() > deadline:
                    raise ProtocolError("Timeout: No response from MCU")
                b = self._port.read(1)
                if not b:
                    raise ProtocolError("Timeout: No response from MCU")
                if b[0] == SOF:
                    break

            remaining_time = deadline - time.time()
            if remaining_time <= 0:
                raise ProtocolError("Timeout: No response from MCU")
            self._port.timeout = remaining_time

            # Read LEN (2 bytes, little-endian)
            len_bytes = self._port.read(2)
            if len(len_bytes) < 2:
                raise ProtocolError("Timeout reading frame length")
            payload_len = struct.unpack("<H", len_bytes)[0]

            if payload_len > MAX_PAYLOAD_SIZE:
                raise ProtocolError(f"Frame too large: {payload_len}")

            # Read CMD + SEQ + PAYLOAD + CRC
            need = 2 + payload_len + 2  # CMD(1) + SEQ(1) + PAYLOAD + CRC(2)
            rest = self._port.read(need)
            if len(rest) < need:
                raise ProtocolError("Timeout reading frame body")

            cmd = rest[0]
            seq = rest[1]
            payload = rest[2:2 + payload_len]
            recv_crc = struct.unpack("<H", rest[2 + payload_len:4 + payload_len])[0]

            # Verify CRC over SOF + LEN + CMD + SEQ + PAYLOAD
            frame_data = bytes([SOF]) + len_bytes + rest[:2 + payload_len]
            calc_crc = crc16_ccitt(frame_data)
            if recv_crc != calc_crc:
                raise ProtocolError("CRC mismatch in received frame")

            return cmd, seq, payload

        finally:
            self._port.timeout = original_timeout

    def _transact(self, cmd: int, payload: bytes,
                  expected_cmd: int, timeout_ms: int = DEFAULT_TIMEOUT_MS):
        """Send a command and wait for the expected response. Retries on failure."""
        last_error = None
        for attempt in range(MAX_RETRIES):
            seq = self._next_seq()
            frame = self._build_frame(cmd, seq, payload)
            try:
                self._port.reset_input_buffer()
                self._send_frame(frame)
                resp_cmd, resp_seq, resp_payload = self._receive_frame(timeout_ms)

                if resp_cmd == CMD_ERROR:
                    err_code = resp_payload[0] if resp_payload else 0xFF
                    err_name = ERROR_NAMES.get(err_code, f"Unknown(0x{err_code:02X})")
                    raise ProtocolError(f"MCU error: {err_name}")

                if resp_cmd != expected_cmd:
                    raise ProtocolError(
                        f"Unexpected response: 0x{resp_cmd:02X} "
                        f"(expected 0x{expected_cmd:02X})")

                return resp_payload

            except ProtocolError as e:
                last_error = e
                continue

        raise last_error

    def read_variables(self, var_infos: list):
        """Send READ_VAR, return list of raw bytes per variable."""
        count = len(var_infos)
        payload = bytes([count])
        for vi in var_infos:
            payload += vi.pack()

        resp = self._transact(CMD_READ_VAR, payload, CMD_READ_RESP)

        resp_count = resp[0]
        if resp_count != count:
            raise ProtocolError(
                f"Variable count mismatch: got {resp_count}, expected {count}")

        # Parse response data: COUNT(1) + concatenated data
        data_list = []
        offset = 1
        for vi in var_infos:
            if vi.bit_offset != NO_BITFIELD:
                data_size = 1  # bitfield returns single byte
            else:
                data_size = vi.size
            if offset + data_size > len(resp):
                raise ProtocolError("Response payload too short")
            data_list.append(resp[offset:offset + data_size])
            offset += data_size

        return data_list

    def write_variables(self, var_infos: list, data_list: list):
        """Send WRITE_VAR with variable info and data."""
        count = len(var_infos)
        payload = bytes([count])
        for vi, data in zip(var_infos, data_list):
            payload += vi.pack() + data

        resp = self._transact(CMD_WRITE_VAR, payload, CMD_WRITE_RESP)

        status = resp[0] if resp else 0xFF
        if status != 0x00:
            err_name = ERROR_NAMES.get(status, f"Unknown(0x{status:02X})")
            raise ProtocolError(f"Write failed: {err_name}")

    def ping(self) -> bool:
        """Send PING, expect PONG. Returns True on success."""
        try:
            self._transact(CMD_PING, b"", CMD_PONG)
            return True
        except ProtocolError:
            return False
