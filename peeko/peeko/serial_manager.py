import serial
import serial.tools.list_ports


def list_ports():
    """Return list of available serial ports as (device, description) tuples."""
    ports = serial.tools.list_ports.comports()
    return [(p.device, p.description) for p in sorted(ports, key=lambda x: x.device)]


class SerialManager:
    """Manages serial port open/close lifecycle."""

    def __init__(self):
        self._serial = None

    def open(self, port: str, baud: int = 9600, timeout: float = 0.5):
        if self._serial and self._serial.is_open:
            self._serial.close()
        self._serial = serial.Serial(port, baud, timeout=timeout)

    def close(self):
        if self._serial and self._serial.is_open:
            self._serial.close()
        self._serial = None

    @property
    def is_open(self) -> bool:
        return self._serial is not None and self._serial.is_open

    @property
    def serial_port(self):
        return self._serial

    @property
    def port_name(self) -> str:
        if self._serial:
            return self._serial.port
        return ""

    @property
    def baud_rate(self) -> int:
        if self._serial:
            return self._serial.baudrate
        return 0
