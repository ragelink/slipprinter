"""Decoding the TM-U295's real-time status (DLE EOT n).

Bit meanings are from Epson's TM-U295 specification. Real-time status is
answered as soon as the request arrives, even while a job sits in the buffer.
"""

from dataclasses import dataclass

DLE_EOT = b"\x10\x04"
QUERIES = (1, 2, 3, 5)

# Every DLE EOT reply matches 0xx1xx10: bits 1 and 4 set, bits 0 and 7 clear.
_FIXED_MASK = 0b1001_0011
_FIXED_VALUE = 0b0001_0010


class StatusError(RuntimeError):
    """The printer didn't answer, or answered with something that isn't a status byte."""


def is_status_byte(value: int) -> bool:
    return value & _FIXED_MASK == _FIXED_VALUE


def bit(value: int, n: int) -> bool:
    return bool(value >> n & 1)


@dataclass(frozen=True)
class PrinterStatus:
    offline: bool
    drawer_pin_high: bool
    feed_button_pressed: bool
    stopped_at_paper_end: bool
    error: bool
    unrecoverable_error: bool
    waiting_for_slip: bool
    paper_at_top: bool
    paper_at_bottom: bool

    @classmethod
    def from_bytes(cls, printer: int, offline_cause: int, error_cause: int, slip: int) -> "PrinterStatus":
        for name, value in (("1", printer), ("2", offline_cause), ("3", error_cause), ("5", slip)):
            if not is_status_byte(value):
                raise StatusError(f"DLE EOT {name} returned 0x{value:02x}, which isn't a status byte")
        return cls(
            offline=bit(printer, 3),
            drawer_pin_high=bit(printer, 2),
            feed_button_pressed=bit(offline_cause, 3),
            stopped_at_paper_end=bit(offline_cause, 5),
            error=bit(offline_cause, 6),
            unrecoverable_error=bit(error_cause, 5),
            waiting_for_slip=bit(slip, 3),
            paper_at_bottom=not bit(slip, 5),
            paper_at_top=not bit(slip, 6),
        )

    @property
    def slip_present(self) -> bool:
        """A slip is in the paper path, at either sensor."""
        return self.paper_at_top or self.paper_at_bottom

    def problems(self) -> list[str]:
        """Why the printer can't take a job right now, ignoring the slip."""
        found = []
        if self.unrecoverable_error:
            found.append("unrecoverable error: power-cycle the printer")
        elif self.error:
            found.append("printer error: check the ribbon and paper path, then press RELEASE")
        if self.offline and not self.error:
            found.append("printer is offline (cover open or panel feed in progress)")
        if self.feed_button_pressed:
            found.append("panel feed button is in use")
        if self.stopped_at_paper_end:
            found.append("stopped at paper end: insert a new slip")
        return found
