import pytest

from slipprinter.device import EJECT, INIT, STOP_AT_PAPER_END, NoSlipError, PrinterNotReadyError, SlipPrinter
from slipprinter.status import StatusError
from tests.fakes import ERROR, IDLE, JOB_QUEUED, OFFLINE, SLIP_IN, UNRECOVERABLE, FakeClock, FakeTransport

pytestmark = pytest.mark.always


def printer(*states, silent=False):
    clock = FakeClock()
    transport = FakeTransport(*states, silent=silent)
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
    p, t, _ = printer(SLIP_IN, SLIP_IN, IDLE)
    p.print_job(b"HELLO\n")
    assert bytes(t.written) == INIT + STOP_AT_PAPER_END + b"HELLO\n" + EJECT


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
    p, t, _ = printer(IDLE, SLIP_IN, SLIP_IN, IDLE)
    p.print_job(b"X", slip_timeout=5)
    assert t.written.endswith(b"X" + EJECT)


def test_print_fails_if_slip_never_leaves():
    p, _, _ = printer(SLIP_IN)
    with pytest.raises(PrinterNotReadyError, match="still in the printer"):
        p.print_job(b"X", eject_timeout=3)


def test_print_reports_error_during_job():
    p, _, _ = printer(SLIP_IN, {**ERROR, 5: 0x12})
    with pytest.raises(PrinterNotReadyError, match="error"):
        p.print_job(b"X")


def test_context_manager_closes_transport():
    p, t, _ = printer()
    with p:
        pass
    assert t.closed
