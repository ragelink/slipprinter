import importlib
import sys
from types import SimpleNamespace

import pytest

from slipprinter import connection
from slipprinter.connection import PortNotFoundError, candidate_ports, find_port
from slipprinter.device import SlipPrinter

pytestmark = pytest.mark.always


def fake_ports(monkeypatch, *ports):
    monkeypatch.setattr(connection.list_ports, "comports", lambda: [SimpleNamespace(device=d, vid=v) for d, v in ports])


def test_candidates_skip_non_usb_and_prefer_callout_devices(monkeypatch):
    fake_ports(
        monkeypatch,
        ("/dev/tty.usbserial-TEST01", 0x0403),
        ("/dev/cu.usbserial-TEST01", 0x0403),
        ("/dev/cu.Bluetooth-Incoming-Port", None),
    )
    assert candidate_ports() == ["/dev/cu.usbserial-TEST01"]


def test_find_port_uses_the_single_candidate(monkeypatch):
    monkeypatch.delenv(connection.PORT_ENV, raising=False)
    fake_ports(monkeypatch, ("/dev/cu.usbserial-TEST01", 0x0403))
    assert find_port() == "/dev/cu.usbserial-TEST01"


def test_env_var_overrides_detection(monkeypatch):
    monkeypatch.setenv(connection.PORT_ENV, "/dev/cu.override")
    fake_ports(monkeypatch)
    assert find_port() == "/dev/cu.override"


def test_no_port_is_an_error(monkeypatch):
    monkeypatch.delenv(connection.PORT_ENV, raising=False)
    fake_ports(monkeypatch)
    with pytest.raises(PortNotFoundError, match="No USB-serial port"):
        find_port()


def test_several_ports_is_an_error_naming_them(monkeypatch):
    monkeypatch.delenv(connection.PORT_ENV, raising=False)
    fake_ports(monkeypatch, ("/dev/cu.usbserial-A", 0x0403), ("/dev/cu.usbserial-B", 0x067B))
    with pytest.raises(PortNotFoundError, match="usbserial-A.*usbserial-B"):
        find_port()


def test_printer_opens_9600_8n1_with_flow_control_handled_in_code(monkeypatch):
    opened = {}
    monkeypatch.setattr("slipprinter.device.serial.Serial", lambda *a, **k: opened.update(args=a, kwargs=k) or object())
    SlipPrinter.open("/dev/cu.usbserial-TEST01")
    assert opened["args"] == ("/dev/cu.usbserial-TEST01", 9600)
    # XON/XOFF is handled by SlipPrinter.write_paced; the driver's (and hardware) flow control stay off
    assert not {"xonxoff", "dsrdtr", "rtscts"} & set(opened["kwargs"])


@pytest.mark.parametrize("module", ["slipprinter.cli", "slipprinter.device", "slipprinter.library"])
def test_importing_never_touches_the_serial_port(monkeypatch, module):
    def boom(*args, **kwargs):
        raise AssertionError("serial port touched at import time")

    monkeypatch.setattr(connection.list_ports, "comports", boom)
    monkeypatch.setattr("serial.Serial", boom)
    sys.modules.pop(module, None)
    importlib.import_module(module)
