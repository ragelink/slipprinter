import pytest

from slipprinter.status import PrinterStatus, StatusError, is_status_byte

pytestmark = pytest.mark.always


def status(printer=0x16, offline=0x12, error=0x12, slip=0x72):
    return PrinterStatus.from_bytes(printer, offline, error, slip)


def test_measured_idle_values_mean_online_with_no_slip():
    s = status()
    assert not s.offline and not s.error and not s.unrecoverable_error
    assert s.drawer_pin_high
    assert not s.paper_at_top and not s.paper_at_bottom and not s.slip_present
    assert s.problems() == []


@pytest.mark.parametrize(
    ("slip", "top", "bottom"),
    [(0x12, True, True), (0x32, True, False), (0x52, False, True), (0x72, False, False)],
)
def test_slip_sensor_bits(slip, top, bottom):
    s = status(slip=slip)
    assert (s.paper_at_top, s.paper_at_bottom, s.slip_present) == (top, bottom, top or bottom)


def test_waiting_for_slip_bit():
    assert status(slip=0x7A).waiting_for_slip
    assert not status(slip=0x72).waiting_for_slip


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({"printer": 0x1E}, "offline"),
        ({"printer": 0x1E, "offline": 0x52}, "printer error"),
        ({"printer": 0x1E, "offline": 0x52, "error": 0x32}, "unrecoverable"),
        ({"printer": 0x1E, "offline": 0x1A}, "feed button"),
        ({"printer": 0x1E, "offline": 0x32}, "paper end"),
    ],
)
def test_problems_explain_why_not_ready(kwargs, expected):
    assert any(expected in p for p in status(**kwargs).problems())


def test_error_is_not_also_reported_as_plain_offline():
    problems = status(printer=0x1E, offline=0x52).problems()
    assert not any("offline" in p for p in problems)


@pytest.mark.parametrize("value", [0x00, 0xFF, 0x11, 0x13, 0x03])
def test_non_status_bytes_are_rejected(value):
    assert not is_status_byte(value)
    with pytest.raises(StatusError, match="isn't a status byte"):
        status(slip=value)
