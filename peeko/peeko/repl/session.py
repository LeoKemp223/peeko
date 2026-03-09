from peeko.serial_manager import SerialManager
from peeko.state_manager import StateManager
from peeko.protocol import Protocol
from peeko.symbol_resolver import SymbolResolver
from peeko.type_converter import TypeConverter
from peeko.config import DEFAULT_BAUD


class Session:
    """Holds live connection state for the REPL session."""

    def __init__(self):
        self.state_mgr = StateManager()
        self.serial_mgr = SerialManager()
        self.protocol = None
        self.resolver = None
        self.converter = None
        self.endian = "little"
        self._restore()

    def _restore(self):
        """Attempt to restore previous session from state file."""
        state = self.state_mgr.load_state()
        if not state:
            return

        self.endian = state.get("endian", "little")

        # Try to re-open serial port
        if state.get("connected"):
            try:
                port = state["port"]
                baud = state.get("baud", DEFAULT_BAUD)
                self.serial_mgr.open(port, baud)
                self.protocol = Protocol(
                    self.serial_mgr.serial_port,
                    little_endian=(self.endian == "little"))
                self.converter = TypeConverter(little_endian=(self.endian == "little"))
            except Exception:
                self.serial_mgr = SerialManager()
                self.protocol = None

        # Try to load symbols
        symbols_path = state.get("symbols_path", "")
        if symbols_path:
            try:
                self.resolver = SymbolResolver(symbols_path)
            except Exception:
                self.resolver = None

    @property
    def is_connected(self) -> bool:
        return self.serial_mgr.is_open

    @property
    def prompt(self) -> str:
        if self.is_connected:
            return f"[{self.serial_mgr.port_name}] > "
        return "peeko> "

    def connect(self, port: str, baud: int, endian: str = "little"):
        if self.serial_mgr.is_open:
            self.serial_mgr.close()

        self.serial_mgr.open(port, baud)
        self.endian = endian
        self.protocol = Protocol(
            self.serial_mgr.serial_port,
            little_endian=(endian == "little"))
        self.converter = TypeConverter(little_endian=(endian == "little"))

        symbols_path = self.state_mgr.load_state().get("symbols_path", "")
        self.state_mgr.save_state(port, baud, endian, symbols_path)

        pong = self.protocol.ping()
        return pong

    def disconnect(self):
        if self.serial_mgr.is_open:
            port = self.serial_mgr.port_name
            self.serial_mgr.close()
            self.protocol = None
            return port
        return ""

    def load_symbols(self, path: str) -> int:
        self.resolver = SymbolResolver(path)
        self.state_mgr.update_state(symbols_path=path)
        return len(self.resolver.list_symbols())

    def close_and_clear(self):
        """Force quit: close connection and clear state."""
        self.disconnect()
        self.resolver = None
        self.state_mgr.clear_state()

    def save_state(self):
        """Preserve current state for next session."""
        if self.is_connected:
            state = self.state_mgr.load_state()
            self.state_mgr.save_state(
                self.serial_mgr.port_name,
                self.serial_mgr.baud_rate,
                self.endian,
                state.get("symbols_path", ""),
            )
