from types import SimpleNamespace

import pytest

from slipprinter import connection
from slipprinter.cli import main

pytestmark = pytest.mark.always


def fake_ports(monkeypatch, *devices):
    monkeypatch.delenv(connection.PORT_ENV, raising=False)
    monkeypatch.setattr(connection.list_ports, "comports", lambda: [SimpleNamespace(device=d, vid=1) for d in devices])


def test_ports_marks_the_selected_port(monkeypatch, capsys):
    fake_ports(monkeypatch, "/dev/cu.usbserial-TEST01")
    assert main(["ports"]) == 0
    assert capsys.readouterr().out == "* /dev/cu.usbserial-TEST01\n"


def test_ports_with_several_candidates_asks_to_pick(monkeypatch, capsys):
    fake_ports(monkeypatch, "/dev/cu.usbserial-A", "/dev/cu.usbserial-B")
    assert main(["ports"]) == 0
    out = capsys.readouterr().out
    assert "  /dev/cu.usbserial-A\n  /dev/cu.usbserial-B\n" in out
    assert "SLIP_PRINTER_PORT" in out


def test_ports_with_none_fails(monkeypatch, capsys):
    fake_ports(monkeypatch)
    assert main(["ports"]) == 1
    assert "No USB-serial ports" in capsys.readouterr().out


def test_version(capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(["--version"])
    assert exit_info.value.code == 0
    assert capsys.readouterr().out.startswith("slip ")
