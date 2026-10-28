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
PAPER_STATUS = b"\x1bv"  # answered only after everything before it has printed
# The printer's flow control: it sends XOFF when its 512-byte buffer is nearly full and
# XON when there's room. USB-serial drivers don't reliably honor these, so we do it here.
XON, XOFF = 0x11, 0x13
CHUNK = 16  # small writes, so little is in flight when an XOFF arrives


class Transport(Protocol):
    @property
    def in_waiting(self) -> int: ...
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
        transport = serial.Serial(port or find_port(), BAUDRATE, timeout=1, write_timeout=10)
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
        while reply and reply[0] in (XON, XOFF):  # flow control, not the answer
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

    def wait_for_job(self, timeout: float) -> None:
        """Wait until everything sent so far has printed.

        ESC v (paper sensor status) is processed in order with the print data, so
        its reply only arrives once the job ahead of it is done. Slip sensors can't
        tell us that: a long sheet still covers them after it's ejected.
        """
        self.transport.reset_input_buffer()
        self.transport.write(PAPER_STATUS)
        self.transport.flush()
        deadline = self.clock() + timeout
        while self.clock() < deadline:
            reply = self.transport.read(1)
            if reply and reply[0] & 0x90 == 0:  # ESC v replies look like 0xx0xxxx
                return
            if not reply:
                self.sleep(self.poll_interval)
        status = self.status()
        problems = status.problems()
        detail = f": {'; '.join(problems)}" if problems else ""
        raise PrinterNotReadyError(f"Job didn't finish within {timeout:g} s{detail}")

    def write_paced(self, data: bytes, stall_timeout: float = 60) -> None:
        """Send `data` in small chunks, pausing whenever the printer sends XOFF until it sends XON."""
        paused, stalled_since, i = False, None, 0
        while True:
            waiting = self.transport.in_waiting
            for byte in self.transport.read(waiting) if waiting else b"":
                if byte == XOFF:
                    paused = True
                elif byte == XON:
                    paused = False
            if paused:
                stalled_since = self.clock() if stalled_since is None else stalled_since
                if self.clock() - stalled_since >= stall_timeout:
                    raise PrinterNotReadyError(f"Printer stopped accepting data for {stall_timeout:g} s")
                self.sleep(self.poll_interval / 10)
                continue
            stalled_since = None
            if i >= len(data):
                return
            self.transport.write(data[i : i + CHUNK])
            self.transport.flush()
            i += CHUNK

    def print_job(
        self, job: bytes, *, finish: bytes = EJECT, slip_timeout: float = 0, job_timeout: float = 120
    ) -> None:
        """Print `job` on the inserted slip, then `finish` (eject by default), and wait until the printer is done.

        With slip_timeout > 0, wait that long for a slip; otherwise one must already be in.
        """
        if slip_timeout > 0:
            self.wait_for_slip(slip_timeout)
        else:
            status = self.status()
            self.check_ready(status)
            if not status.slip_present:
                raise NoSlipError("No slip inserted")
        self.transport.reset_input_buffer()
        self.write_paced(INIT + STOP_AT_PAPER_END + job + finish)
        self.wait_for_job(job_timeout)

    def send(self, data: bytes) -> None:
        """Send raw bytes as they are, once the printer is ready. Callers validate them first."""
        self.check_ready(self.status())
        self.write_paced(data)

    def identify(self) -> dict[str, int]:
        """GS I: model ID, type ID and ROM version. These go through the buffer, so the printer must be idle."""
        self.check_ready(self.status())
        info = {}
        for name, n in (("model", 1), ("type", 2), ("rom", 3)):
            self.transport.reset_input_buffer()
            self.transport.write(b"\x1dI" + bytes([n]))
            self.transport.flush()
            reply = self.transport.read(1)
            if not reply:
                raise StatusError(f"No answer to GS I {n}")
            info[name] = reply[0]
        return info
