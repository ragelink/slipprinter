import datetime as dt
from types import SimpleNamespace

import pytest

from slipprinter import cli, connection
from slipprinter.cli import main
from slipprinter.device import EJECT, SlipPrinter
from tests.fakes import IDLE, JOB_QUEUED, OFFLINE, SLIP_IN, FakeClock, FakeTransport

pytestmark = pytest.mark.always


@pytest.fixture
def fake_printer(monkeypatch):
    """Point the CLI at a fake printer; returns a function that scripts its states."""
    holder = {}

    def script(*states):
        clock = FakeClock()
        transport = FakeTransport(*states)
        holder["transport"] = transport
        monkeypatch.setattr(
            cli, "open_printer", lambda: SlipPrinter(transport, clock=clock, sleep=clock.sleep, poll_interval=1)
        )
        return transport

    return script


@pytest.fixture(autouse=True)
def no_tty(monkeypatch):
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)


def fake_ports(monkeypatch, *devices):
    monkeypatch.delenv(connection.PORT_ENV, raising=False)
    monkeypatch.setattr(connection.list_ports, "comports", lambda: [SimpleNamespace(device=d, vid=1) for d in devices])


CHECK = ["print", "check", "--set", "payee=Jane Example", "--set", "amount=1234.56", "--set", "date=2026-10-28"]


# ---------------------------------------------------------------- ports


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


# ---------------------------------------------------------------- status


@pytest.mark.parametrize(
    ("state", "code", "text"),
    [
        (IDLE, 0, "Printer ready (no slip)"),
        (SLIP_IN, 0, "Printer ready (slip inserted)"),
        (OFFLINE, 1, "not ready: printer is offline"),
        (JOB_QUEUED, 0, "a job is waiting in the printer's buffer"),
    ],
)
def test_status(fake_printer, capsys, state, code, text):
    fake_printer(state)
    assert main(["status"]) == code
    assert text in capsys.readouterr().out


def test_status_when_printer_silent(monkeypatch, capsys):
    transport = FakeTransport(silent=True)
    monkeypatch.setattr(cli, "open_printer", lambda: SlipPrinter(transport))
    assert main(["status"]) == 2
    assert "null-modem" in capsys.readouterr().err


# ---------------------------------------------------------------- templates and preview


def test_templates_lists_fields_and_user_dir(capsys, tmp_path, monkeypatch):
    monkeypatch.setenv("SLIP_TEMPLATES", str(tmp_path))
    assert main(["templates"]) == 0
    out = capsys.readouterr().out
    assert "check: Personal check, front" in out
    assert "amount_words" in out and "(from amount)" in out
    assert "memo" in out and "(optional)" in out
    assert str(tmp_path) in out


def test_templates_reports_broken_personal_template(capsys, tmp_path, monkeypatch):
    monkeypatch.setenv("SLIP_TEMPLATES", str(tmp_path))
    (tmp_path / "mine.yaml").write_text("name: mine\nfields: {a: {line: 0, col: 0, width: 99}}\n")
    assert main(["templates"]) == 1
    assert "! mine.yaml: field 'a': runs past the last column" in capsys.readouterr().out


def test_preview_needs_no_printer(capsys, monkeypatch):
    monkeypatch.setattr(cli, "open_printer", lambda: pytest.fail("preview opened the printer"))
    assert main(["preview", "check", "--set", "payee=Jane Example", "--set", "amount=5"]) == 0
    out = capsys.readouterr().out
    assert "Jane Example" in out and "Five and 00/100" in out


def test_preview_prompts_for_missing_fields_when_interactive(capsys, monkeypatch):
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    answers = iter(["Jane Example", "12"])
    monkeypatch.setattr("builtins.input", lambda prompt: next(answers))
    assert main(["preview", "check"]) == 0
    assert "Twelve and 00/100" in capsys.readouterr().out


# ---------------------------------------------------------------- print


def test_print_waits_for_slip_then_prints_and_ejects(fake_printer, capsys):
    transport = fake_printer(IDLE, IDLE, SLIP_IN, SLIP_IN, IDLE)
    assert main([*CHECK, "--yes"]) == 0
    out = capsys.readouterr().out
    assert "Insert the check face up" in out
    assert "Printed and ejected." in out
    assert b"Jane Example" in transport.written
    assert transport.written.endswith(b"\x0c" + EJECT)  # page mode print, then eject


def test_print_validates_before_touching_printer(monkeypatch, capsys):
    monkeypatch.setattr(cli, "open_printer", lambda: pytest.fail("printer opened despite bad input"))
    assert main(["print", "check", "--set", "payee=Jane", "--set", "amount=lots", "--yes"]) == 2
    assert "not an amount" in capsys.readouterr().err


def test_print_asks_for_confirmation(fake_printer, monkeypatch, capsys):
    transport = fake_printer(SLIP_IN)
    monkeypatch.setattr("builtins.input", lambda prompt: "n")
    assert main(CHECK) == 1
    assert "Not printed." in capsys.readouterr().out
    assert transport.written == b""


def test_print_times_out_without_sending(fake_printer, capsys):
    transport = fake_printer(IDLE)
    assert main([*CHECK, "--yes", "--timeout", "3"]) == 2
    assert "No slip inserted within 3 s" in capsys.readouterr().err
    assert transport.written == b""


def test_print_refuses_when_offline(fake_printer, capsys):
    transport = fake_printer(OFFLINE)
    assert main([*CHECK, "--yes"]) == 2
    assert "offline" in capsys.readouterr().err
    assert transport.written == b""


@pytest.mark.parametrize(
    ("args", "error"),
    [
        (["print", "nope", "--yes"], "No template named 'nope'"),
        (["print", "check", "--set", "payee", "--yes"], "--set needs field=value"),
        (["print", "check", "--set", "colour=red", "--yes"], "unknown fields: colour"),
        (["print", "check", "--set", "amount=1", "--yes", "--no-input"], "Pay to the order of is required"),
    ],
)
def test_print_input_errors(args, error, capsys):
    assert main(args) == 2
    assert error in capsys.readouterr().err


def test_ctrl_c_while_waiting_sends_nothing(monkeypatch, capsys):
    transport = FakeTransport(IDLE)

    def interrupt(seconds):
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "open_printer", lambda: SlipPrinter(transport, sleep=interrupt))
    assert main([*CHECK, "--yes"]) == 130
    assert transport.written == b""


# ---------------------------------------------------------------- ruler


@pytest.mark.parametrize(("font", "columns"), [("5x7", 35), ("7x7", 42)])
def test_ruler_prints_full_width(fake_printer, font, columns):
    transport = fake_printer(SLIP_IN, SLIP_IN, IDLE)
    assert main(["ruler", "--font", font]) == 0
    expected_ones = "".join(str(i % 10) for i in range(1, columns + 1)).encode()
    assert expected_ones + b"\n" in transport.written


def test_rotated_ruler_prints_in_page_mode(fake_printer):
    transport = fake_printer(SLIP_IN)
    assert main(["ruler", "--rotated"]) == 0
    written = bytes(transport.written)
    assert b"\x1bL\x1bW\x00\x00\x00\x00\xd2\x00\x68\x01\x1bT\x01" in written  # 210 x 360, direction 1
    ones = "".join(str(i % 10) for i in range(1, 61)).encode()
    assert ones + b"\n" in written and b"\n15\n\x0c" in written  # 60 columns, lines to 15, then print the page


def test_today_default_is_used(fake_printer, monkeypatch):
    class FixedDate(dt.date):
        @classmethod
        def today(cls):
            return cls(2026, 1, 2)

    monkeypatch.setattr("slipprinter.template.dt.date", FixedDate)
    transport = fake_printer(SLIP_IN, SLIP_IN, IDLE)
    assert main(["print", "check", "--set", "payee=Jane", "--set", "amount=1", "--yes"]) == 0
    assert b"01/02/2026" in transport.written


# ---------------------------------------------------------------- printer actions


def test_info_decodes_printer_id(monkeypatch, capsys):
    class IdTransport(FakeTransport):
        def write(self, data):
            if data[:2] == b"\x1dI":
                self.pending = bytes([{1: 0x02, 2: 0x00, 3: 0x41}[data[2]]])
                return len(data)
            return super().write(data)

    transport = IdTransport(IDLE)
    monkeypatch.setattr(cli, "open_printer", lambda: SlipPrinter(transport))
    assert main(["info"]) == 0
    out = capsys.readouterr().out
    assert "Model: TM-U295 (ID 0x02)" in out and "no cutter" in out and "ROM version: 0x41" in out


@pytest.mark.parametrize(
    ("args", "state", "sent", "text"),
    [
        (["eject"], SLIP_IN, b"\x0c", "Ejected."),
        (["release"], SLIP_IN, b"\x1bq", "Released."),
        (["drawer"], IDLE, b"\x1bp\x00\x32\xfa", "Pulsed drawer pin 2."),
        (["drawer", "--pin", "5", "--on", "20", "--off", "40"], IDLE, b"\x1bp\x01\x0a\x14", "pin 5"),
        (["buttons", "disable"], IDLE, b"\x1bc5\x01", "Panel buttons disabled."),
        (["buttons", "enable"], IDLE, b"\x1bc5\x00", "Panel buttons enabled."),
        (["send", "ESC", "p", "0", "25", "250"], IDLE, b"\x1bp\x00\x19\xfa", "Sent 5 bytes."),
        (["send", '"Hi"', "LF"], SLIP_IN, b"Hi\n", "Sent 3 bytes."),
        (["send", "--force", '"Hi"'], IDLE, b"Hi", "Sent 2 bytes."),
    ],
)
def test_printer_actions(fake_printer, capsys, args, state, sent, text):
    transport = fake_printer(state)
    assert main(args) == 0
    assert bytes(transport.written) == sent
    assert text in capsys.readouterr().out


@pytest.mark.parametrize(
    ("args", "state", "error"),
    [
        (["eject"], IDLE, "No slip inserted"),
        (["send", '"Hi"'], IDLE, "--force"),
        (["send", "GS", "V", "0"], SLIP_IN, "no cutter"),
        (["drawer", "--on", "600"], IDLE, "2 to 510"),
        (["drawer"], OFFLINE, "offline"),
    ],
)
def test_printer_action_refusals_send_nothing(fake_printer, capsys, args, state, error):
    transport = fake_printer(state)
    assert main(args) == 2
    assert error in capsys.readouterr().err
    assert transport.written == b""


def test_print_uses_the_template_finish(fake_printer, tmp_path, monkeypatch):
    monkeypatch.setenv("SLIP_TEMPLATES", str(tmp_path))
    (tmp_path / "kick.yaml").write_text(
        "name: kick\nfinish: release\ndrawer: {pin: 2}\nfields: {a: {line: 0, col: 0, width: 3}}\n"
    )
    transport = fake_printer(SLIP_IN, SLIP_IN, IDLE)
    assert main(["print", "kick", "--set", "a=x", "--yes"]) == 0
    assert transport.written.endswith(b"\x1bq\x1bp\x00\x32\xfa")


# ---------------------------------------------------------------- images


@pytest.fixture
def picture(tmp_path):
    from PIL import Image as PILImage

    img = PILImage.new("L", (400, 100), 255)
    img.paste(0, (0, 0, 400, 50))
    path = tmp_path / "wide.png"
    img.save(path)
    return path


def test_image_shrinks_to_the_band_and_prints(fake_printer, picture, capsys):
    transport = fake_printer(SLIP_IN)
    assert main(["image", str(picture)]) == 0
    assert "210 x 39 dots" in capsys.readouterr().out  # 400x100 -> 210 wide, 52.5 tall, x 3/4 for the dots
    assert transport.written.count(b"\x1b*\x00\xd2\x00") == 5  # 39 rows = 5 bands of 210 columns
    assert transport.written.endswith(b"\x1bJ\x08" + EJECT)


def test_image_preview_saves_without_printing(picture, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "open_printer", lambda: pytest.fail("preview opened the printer"))
    out = tmp_path / "preview.png"
    assert main(["image", str(picture), "--density", "double", "--preview", str(out)]) == 0
    assert out.exists() and "400 x 38 dots" in capsys.readouterr().out


def test_image_errors(fake_printer, tmp_path, capsys):
    fake_printer(SLIP_IN)
    (tmp_path / "bad.png").write_text("nope")
    assert main(["image", str(tmp_path / "bad.png")]) == 2
    assert "can't read image" in capsys.readouterr().err
