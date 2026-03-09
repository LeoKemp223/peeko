import os
from pathlib import Path

# Protocol constants (matching mcu_lib/inc/peeko.h)
SOF = 0xAA
FRAME_OVERHEAD = 7  # SOF(1) + LEN(2) + CMD(1) + SEQ(1) + CRC(2)
MAX_PAYLOAD_SIZE = 256
MAX_VARIABLES = 30

# Command types
CMD_READ_VAR = 0x01
CMD_WRITE_VAR = 0x02
CMD_READ_RESP = 0x81
CMD_WRITE_RESP = 0x82
CMD_ERROR = 0xFF
CMD_PING = 0x10
CMD_PONG = 0x90

# Error codes
ERR_OK = 0x00
ERR_CRC = 0x01
ERR_ADDR = 0x02
ERR_SIZE = 0x03
ERR_CMD = 0x04
ERR_TIMEOUT = 0x05

ERROR_NAMES = {
    ERR_OK: "OK",
    ERR_CRC: "CRC mismatch",
    ERR_ADDR: "Invalid address",
    ERR_SIZE: "Invalid size",
    ERR_CMD: "Unknown command",
    ERR_TIMEOUT: "Timeout",
}

# Bitfield marker
NO_BITFIELD = 0xFF

# Timing
DEFAULT_TIMEOUT_MS = 500
MAX_RETRIES = 3
DEFAULT_BAUD = 9600

# State persistence
STATE_DIR = Path(os.path.expanduser("~/.peeko"))
STATE_FILE = STATE_DIR / "state.json"
HISTORY_FILE = STATE_DIR / "history"
