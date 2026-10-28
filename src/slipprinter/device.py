"""Talking to the slip printer: status, waiting for a slip, and guarded printing.

A job sent with no slip inserted sits in the printer's buffer and prints onto
whatever goes in next, so nothing is sent until a slip is detected.
"""

import time
from collections.abc import Callable
from typing import Protocol

import serial

from slipprinter.connection import BAUDRATE, find_port
from slipprinter.status import DLE_EOT, QUERIES, PrinterStatus, StatusError

INIT = b"\x1b@"
# ESC c 4 n: stop printing when the top (bit 4) or bottom (bit 5) sensor runs out
# of paper. Off by default, which lets a job print into thin air past the slip.
STOP_AT_PAPER_END = b"\x1bc4\x30"
EJECT = b"\x0c"


class Transport(Protocol):
    def write(self, data: bytes) -> int | None: ...
    def read(self, size: int = 1) -> bytes: ...
    def flush(self) -> None: ...
    def reset_input_buffer(self) -> None: ...
    def close(self) -> None: ...


class PrinterNotReadyError(RuntimeError):
    """The printer is offline, in error, or busy with another job."""


class NoSlipError(RuntimeError):
    """No slip was inserted in time."""


class SlipPrinter:
    def __init__(
        self,
        transport: Transport,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        poll_interval: float = 0.25,
    ):
        self.transport = transport
        self.clock = clock
        self.sleep = sleep
        self.poll_interval = poll_interval

    @classmethod
    def open(cls, port: str | None = None) -> "SlipPrinter":
        transport = serial.Serial(port or find_port(), BAUDRATE, xonxoff=True, timeout=1, write_timeout=10)
        return cls(transport)

    def close(self) -> None:
        self.transport.close()

    def __enter__(self) -> "SlipPrinter":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def query(self, n: int) -> int:
        self.transport.reset_input_buffer()
        self.transport.write(DLE_EOT + bytes([n]))
        self.transport.flush()
        reply = self.transport.read(1)
        if not reply:
            raise StatusError(f"No answer to DLE EOT {n}. Is the printer on, and is the null-modem adapter in place?")
        return reply[0]

    def status(self) -> PrinterStatus:
        return PrinterStatus.from_bytes(*(self.query(n) for n in QUERIES))

    def check_ready(self, status: PrinterStatus) -> None:
        problems = status.problems()
        if status.waiting_for_slip:
            problems.append("another job is waiting in the printer's buffer: power-cycle the printer to clear it")
        if problems:
            raise PrinterNotReadyError("; ".join(problems))

    def wait_for_slip(self, timeout: float) -> PrinterStatus:
        """Poll until a slip is inserted. Raises at once if the printer isn't ready."""
        deadline = self.clock() + timeout
        while True:
            status = self.status()
            self.check_ready(status)
            if status.slip_present:
                return status
            if self.clock() >= deadline:
                raise NoSlipError(f"No slip inserted within {timeout:g} s")
            self.sleep(self.poll_interval)

    def wait_for_eject(self, timeout: float) -> PrinterStatus:
        """Poll until the slip has left both sensors, meaning the job is done."""
        deadline = self.clock() + timeout
        while True:
            status = self.status()
            if status.unrecoverable_error or status.error:
                raise PrinterNotReadyError("; ".join(status.problems()))
            if not status.slip_present:
                return status
            if self.clock() >= deadline:
                raise PrinterNotReadyError(f"Slip still in the printer after {timeout:g} s")
            self.sleep(self.poll_interval)

    def print_job(self, job: bytes, *, slip_timeout: float = 0, eject_timeout: float = 120) -> None:
        """Print `job` on the inserted slip, eject it, and wait for it to leave.

        With slip_timeout > 0, wait that long for a slip; otherwise one must already be in.
        """
        if slip_timeout > 0:
            self.wait_for_slip(slip_timeout)
        else:
            status = self.status()
            self.check_ready(status)
            if not status.slip_present:
                raise NoSlipError("No slip inserted")
        self.transport.write(INIT + STOP_AT_PAPER_END + job + EJECT)
        self.transport.flush()
        self.wait_for_eject(eject_timeout)
