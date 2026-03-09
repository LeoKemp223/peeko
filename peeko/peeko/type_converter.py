import struct

# Mapping from C type names to struct format characters
_TYPE_MAP = {
    # Unsigned integers
    "uint8_t": "B", "unsigned char": "B", "uint8": "B",
    "uint16_t": "H", "unsigned short": "H", "uint16": "H",
    "uint32_t": "I", "unsigned int": "I", "unsigned long": "I", "uint32": "I",
    "uint64_t": "Q", "unsigned long long": "Q", "uint64": "Q",
    # Signed integers
    "int8_t": "b", "signed char": "b", "char": "b", "int8": "b",
    "int16_t": "h", "short": "h", "int16": "h",
    "int32_t": "i", "int": "i", "long": "i", "int32": "i",
    "int64_t": "q", "long long": "q", "int64": "q",
    # Floating point
    "float": "f",
    "double": "d",
    # Boolean
    "bool": "?", "_Bool": "?",
}

# Size to unsigned format fallback
_SIZE_TO_UNSIGNED = {1: "B", 2: "H", 4: "I", 8: "Q"}
_SIZE_TO_SIGNED = {1: "b", 2: "h", 4: "i", 8: "q"}


class TypeConverter:
    """Converts between Python values and C-typed byte representations."""

    def __init__(self, little_endian: bool = True):
        self._prefix = "<" if little_endian else ">"

    def decode(self, data: bytes, data_type: str) -> object:
        """Decode raw bytes to a Python value based on C data type."""
        fmt_char = _TYPE_MAP.get(data_type)

        if fmt_char:
            fmt = self._prefix + fmt_char
            expected_size = struct.calcsize(fmt)
            if len(data) < expected_size:
                data = data + b'\x00' * (expected_size - len(data))
            return struct.unpack(fmt, data[:expected_size])[0]

        # Fallback: treat as unsigned integer based on size
        size = len(data)
        fmt_char = _SIZE_TO_UNSIGNED.get(size)
        if fmt_char:
            return struct.unpack(self._prefix + fmt_char, data)[0]

        # Arbitrary size: interpret as little/big endian integer
        if self._prefix == "<":
            return int.from_bytes(data, "little", signed=False)
        return int.from_bytes(data, "big", signed=False)

    def encode(self, value, data_type: str, size: int) -> bytes:
        """Encode a Python value to bytes based on C data type and size."""
        fmt_char = _TYPE_MAP.get(data_type)

        if fmt_char:
            fmt = self._prefix + fmt_char
            return struct.pack(fmt, value)

        # Fallback: pack as unsigned integer based on size
        fmt_char = _SIZE_TO_UNSIGNED.get(size)
        if fmt_char:
            return struct.pack(self._prefix + fmt_char, int(value))

        # Arbitrary size
        byteorder = "little" if self._prefix == "<" else "big"
        return int(value).to_bytes(size, byteorder, signed=False)

    def parse_value(self, value_str: str, data_type: str) -> object:
        """Parse a user-provided string value into the appropriate Python type."""
        value_str = value_str.strip()

        # Boolean
        if value_str.lower() in ("true", "1"):
            return True
        if value_str.lower() in ("false", "0") and data_type in ("bool", "_Bool"):
            return False

        # Float/double
        if data_type in ("float", "double"):
            return float(value_str)

        # Integer (decimal, hex, binary)
        if value_str.startswith("0x") or value_str.startswith("0X"):
            return int(value_str, 16)
        if value_str.startswith("0b") or value_str.startswith("0B"):
            return int(value_str, 2)

        # Try float first (for values like 3.14 assigned to int fields)
        if "." in value_str:
            return float(value_str)

        return int(value_str)

    def format_value(self, value, data_type: str) -> str:
        """Format a decoded value for display."""
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, float):
            if value == int(value) and abs(value) < 1e15:
                return f"{value:.1f}"
            return str(value)
        return str(value)
