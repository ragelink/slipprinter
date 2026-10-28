"""Serial connection to the slip printer.

The Epson TM-U295 (serial) ships with DIP switches set to 9600 8N1 and XON/XOFF.
USB-serial cables often leave DSR/CTS unwired, so hardware flow control stays off.
"""

import os

from serial.tools import list_ports

PORT_ENV = "SLIP_PRINTER_PORT"
BAUDRATE = 9600


class PortNotFoundError(RuntimeError):
    """No usable serial port, or more than one candidate to choose from."""


def candidate_ports() -> list[str]:
    """USB-serial ports, as macOS call-out devices (/dev/cu.*) where available."""
    ports = []
    for port in list_ports.comports():
        if port.vid is None:  # Bluetooth and other non-USB ports
            continue
        ports.append(port.device.replace("/dev/tty.", "/dev/cu.", 1))
    return sorted(set(ports))


def find_port() -> str:
    """The port to use: $SLIP_PRINTER_PORT if set, else the single USB-serial port."""
    if os.environ.get(PORT_ENV):
        return os.environ[PORT_ENV]
    ports = candidate_ports()
    if len(ports) == 1:
        return ports[0]
    if not ports:
        raise PortNotFoundError(
            f"No USB-serial port found. Is the printer cable connected? Set {PORT_ENV} to override."
        )
    raise PortNotFoundError(f"Several USB-serial ports found ({', '.join(ports)}). Set {PORT_ENV} to pick one.")
