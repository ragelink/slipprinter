import pytest

from slipprinter.device import EJECT, INIT, STOP_AT_PAPER_END, NoSlipError, PrinterNotReadyError, SlipPrinter
from slipprinter.status import StatusError
from tests.fakes import ERROR, IDLE, JOB_QUEUED, OFFLINE, SLIP_IN, UNRECOVERABLE, FakeClock, FakeTransport

pytestmark = pytest.mark.always


def printer(*states, silent=False, stuck=False):
    clock = FakeClock()
    transport = FakeTransport(*states, silent=silent, stuck=stuck)
    return SlipPrinter(transport, clock=clock, sleep=clock.sleep, poll_interval=0.5), transport, clock


def test_status_reads_all_four_real_time_queries():
    p, t, _ = printer(SLIP_IN)
    assert p.status().slip_present
    assert t.queries == 4


def test_silent_printer_explains_likely_cause():
    p, _, _ = printer(silent=True)
    with pytest.raises(StatusError, match="null-modem"):
        p.status()


def test_print_sends_init_paper_end_stop_job_and_eject():
    p, t, _ = printer(SLIP_IN)
    p.print_job(b"HELLO\n")
    assert bytes(t.written) == INIT + STOP_AT_PAPER_END + b"HELLO\n" + EJECT


def test_print_finishes_even_if_a_long_sheet_still_covers_the_sensors():
    p, t, _ = printer(SLIP_IN)  # the sheet never leaves the sensors
    p.print_job(b"HELLO\n")
    assert t.written.endswith(EJECT)


@pytest.mark.parametrize(
    ("state", "error", "match"),
    [
        (IDLE, NoSlipError, "No slip"),
        (OFFLINE, PrinterNotReadyError, "offline"),
        ({**ERROR, 5: 0x12}, PrinterNotReadyError, "error"),
        ({**UNRECOVERABLE, 5: 0x12}, PrinterNotReadyError, "power-cycle"),
        (JOB_QUEUED, PrinterNotReadyError, "buffer"),
    ],
)
def test_print_refuses_and_sends_nothing_unless_ready(state, error, match):
    p, t, _ = printer(state)
    with pytest.raises(error, match=match):
        p.print_job(b"HELLO\n")
    assert t.written == b""


def test_wait_for_slip_polls_until_inserted():
    p, t, clock = printer(IDLE, IDLE, IDLE, SLIP_IN)
    assert p.wait_for_slip(timeout=10).slip_present
    assert clock.now == 1.5


def test_wait_for_slip_times_out_without_sending():
    p, t, clock = printer(IDLE)
    with pytest.raises(NoSlipError, match="within 2 s"):
        p.wait_for_slip(timeout=2)
    assert t.written == b""
    assert clock.now == 2.0


def test_wait_for_slip_fails_fast_when_printer_breaks():
    p, _, clock = printer(IDLE, OFFLINE)
    with pytest.raises(PrinterNotReadyError, match="offline"):
        p.wait_for_slip(timeout=60)
    assert clock.now == 0.5


def test_print_with_slip_timeout_waits_then_prints():
    p, t, _ = printer(IDLE, SLIP_IN)
    p.print_job(b"X", slip_timeout=5)
    assert t.written.endswith(b"X" + EJECT)


def test_print_times_out_if_the_job_never_finishes():
    p, _, clock = printer(SLIP_IN, stuck=True)
    with pytest.raises(PrinterNotReadyError, match="didn't finish within 3 s"):
        p.print_job(b"X", job_timeout=3)
    assert clock.now >= 3


def test_print_reports_why_a_job_stalled():
    p, _, _ = printer(SLIP_IN, {**ERROR, 5: 0x12}, stuck=True)
    with pytest.raises(PrinterNotReadyError, match="didn't finish.*printer error"):
        p.print_job(b"X", job_timeout=1)


def test_status_bytes_arriving_while_waiting_are_not_mistaken_for_completion():
    p, t, _ = printer(SLIP_IN, stuck=True)
    original = t.write

    def write(data):
        written = original(data)
        if data == b"\x1bv":
            t.pending = b"\x16"  # a late DLE EOT reply, not the ESC v answer
        return written

    t.write = write
    with pytest.raises(PrinterNotReadyError, match="didn't finish"):
        p.wait_for_job(1)


def test_context_manager_closes_transport():
    p, t, _ = printer()
    with p:
        pass
    assert t.closed
