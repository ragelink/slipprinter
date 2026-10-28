//! Decoding the TM-U295's real-time status (DLE EOT n).
//!
//! Bit meanings are from Epson's TM-U295 specification. Real-time status is
//! answered as soon as the request arrives, even while a job sits in the buffer.

use crate::{Error, Result};

pub const DLE_EOT: [u8; 2] = [0x10, 0x04];
pub const QUERIES: [u8; 4] = [1, 2, 3, 5];

// Every DLE EOT reply matches 0xx1xx10: bits 1 and 4 set, bits 0 and 7 clear.
const FIXED_MASK: u8 = 0b1001_0011;
const FIXED_VALUE: u8 = 0b0001_0010;

pub fn is_status_byte(value: u8) -> bool {
    value & FIXED_MASK == FIXED_VALUE
}

fn bit(value: u8, n: u8) -> bool {
    value >> n & 1 == 1
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct PrinterStatus {
    pub offline: bool,
    pub drawer_pin_high: bool,
    pub feed_button_pressed: bool,
    pub stopped_at_paper_end: bool,
    pub error: bool,
    pub unrecoverable_error: bool,
    pub waiting_for_slip: bool,
    pub paper_at_top: bool,
    pub paper_at_bottom: bool,
}

impl PrinterStatus {
    /// From the replies to DLE EOT 1, 2, 3 and 5, in that order.
    pub fn from_bytes(replies: [u8; 4]) -> Result<Self> {
        for (n, value) in QUERIES.iter().zip(replies) {
            if !is_status_byte(value) {
                return Err(Error::Status(format!("DLE EOT {n} returned 0x{value:02x}, which isn't a status byte")));
            }
        }
        let [printer, offline_cause, error_cause, slip] = replies;
        Ok(PrinterStatus {
            offline: bit(printer, 3),
            drawer_pin_high: bit(printer, 2),
            feed_button_pressed: bit(offline_cause, 3),
            stopped_at_paper_end: bit(offline_cause, 5),
            error: bit(offline_cause, 6),
            unrecoverable_error: bit(error_cause, 5),
            waiting_for_slip: bit(slip, 3),
            paper_at_bottom: !bit(slip, 5),
            paper_at_top: !bit(slip, 6),
        })
    }

    /// A slip is in the paper path, at either sensor.
    pub fn slip_present(&self) -> bool {
        self.paper_at_top || self.paper_at_bottom
    }

    /// Why the printer can't take a job right now, ignoring the slip.
    pub fn problems(&self) -> Vec<&'static str> {
        let mut found = Vec::new();
        if self.unrecoverable_error {
            found.push("unrecoverable error: power-cycle the printer");
        } else if self.error {
            found.push("printer error: check the ribbon and paper path, then press RELEASE");
        }
        if self.offline && !self.error {
            found.push("printer is offline (cover open or panel feed in progress)");
        }
        if self.feed_button_pressed {
            found.push("panel feed button is in use");
        }
        if self.stopped_at_paper_end {
            found.push("stopped at paper end: insert a new slip");
        }
        found
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    // Replies as measured on the printer, and as scripted in the Python tests' fakes.
    const IDLE: [u8; 4] = [0x16, 0x12, 0x12, 0x72];
    const SLIP_IN: [u8; 4] = [0x16, 0x12, 0x12, 0x12];
    const OFFLINE: [u8; 4] = [0x1E, 0x12, 0x12, 0x72];
    const ERROR: [u8; 4] = [0x1E, 0x52, 0x12, 0x72];
    const UNRECOVERABLE: [u8; 4] = [0x1E, 0x52, 0x32, 0x72];
    const JOB_QUEUED: [u8; 4] = [0x16, 0x12, 0x12, 0x7A];

    #[test]
    fn idle_has_no_slip_and_no_problems() {
        let s = PrinterStatus::from_bytes(IDLE).unwrap();
        assert!(!s.slip_present());
        assert!(s.problems().is_empty());
        assert!(s.drawer_pin_high);
    }

    #[test]
    fn slip_in_covers_both_sensors() {
        let s = PrinterStatus::from_bytes(SLIP_IN).unwrap();
        assert!(s.paper_at_top && s.paper_at_bottom && s.slip_present());
    }

    #[test]
    fn offline_and_errors() {
        let offline = PrinterStatus::from_bytes(OFFLINE).unwrap();
        assert_eq!(offline.problems(), ["printer is offline (cover open or panel feed in progress)"]);
        let error = PrinterStatus::from_bytes(ERROR).unwrap();
        assert_eq!(error.problems(), ["printer error: check the ribbon and paper path, then press RELEASE"]);
        let fatal = PrinterStatus::from_bytes(UNRECOVERABLE).unwrap();
        assert_eq!(fatal.problems(), ["unrecoverable error: power-cycle the printer"]);
    }

    #[test]
    fn job_queued_is_waiting_for_a_slip() {
        assert!(PrinterStatus::from_bytes(JOB_QUEUED).unwrap().waiting_for_slip);
    }

    #[test]
    fn rejects_bytes_that_are_not_status() {
        let err = PrinterStatus::from_bytes([0x16, 0x12, 0x12, 0x00]).unwrap_err();
        assert_eq!(err.to_string(), "DLE EOT 5 returned 0x00, which isn't a status byte");
    }
}
