//! Driving the Epson TM-U295 slip printer: the serial link, real-time status,
//! and pages turned into bit images.
//!
//! This mirrors the Python package's `device.py`, `status.py` and `images.py`,
//! and shared fixtures pin both to the same bytes.

use std::fmt;
use std::io;

pub mod link;
pub mod raster;
pub mod serial;
pub mod status;

pub use link::{Clock, Printer, SystemClock, Transport};
pub use status::PrinterStatus;

#[derive(Debug)]
pub enum Error {
    /// The printer didn't answer, or answered with something that isn't a status byte.
    Status(String),
    /// The printer is offline, in error, or busy with another job.
    NotReady(String),
    /// No slip was inserted in time.
    NoSlip(String),
    /// No usable serial port, or more than one to choose from.
    Port(String),
    Io(io::Error),
}

impl fmt::Display for Error {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Error::Status(m) | Error::NotReady(m) | Error::NoSlip(m) | Error::Port(m) => f.write_str(m),
            Error::Io(e) => write!(f, "{e}"),
        }
    }
}

impl std::error::Error for Error {}

impl From<io::Error> for Error {
    fn from(e: io::Error) -> Self {
        Error::Io(e)
    }
}

pub type Result<T> = std::result::Result<T, Error>;
