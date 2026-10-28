//! The serial port.
//!
//! The TM-U295 ships with DIP switches set to 9600 8N1 and XON/XOFF. USB-serial
//! cables often leave DSR/CTS unwired, so hardware flow control stays off, and
//! XON/XOFF is handled in [`Printer::write_paced`](crate::Printer::write_paced).

use std::io::{self, Read, Write};
use std::time::Duration;

use serialport::{ClearBuffer, FlowControl, SerialPort, SerialPortType};

use crate::link::Transport;
use crate::{Error, Result};

pub const PORT_ENV: &str = "SLIP_PRINTER_PORT";
pub const BAUDRATE: u32 = 9600;

/// USB-serial ports, as macOS call-out devices (/dev/cu.*) where available.
pub fn candidate_ports() -> Result<Vec<String>> {
    let ports = serialport::available_ports().map_err(|e| Error::Port(e.to_string()))?;
    let mut names: Vec<String> = ports
        .into_iter()
        .filter(|p| matches!(p.port_type, SerialPortType::UsbPort(_)))
        .map(|p| p.port_name.replacen("/dev/tty.", "/dev/cu.", 1))
        .collect();
    names.sort();
    names.dedup();
    Ok(names)
}

/// The port to use: $SLIP_PRINTER_PORT if set, else the single USB-serial port.
pub fn find_port() -> Result<String> {
    if let Some(port) = std::env::var(PORT_ENV).ok().filter(|p| !p.is_empty()) {
        return Ok(port);
    }
    let ports = candidate_ports()?;
    match ports.as_slice() {
        [port] => Ok(port.clone()),
        [] => Err(Error::Port(format!(
            "No USB-serial port found. Is the printer cable connected? Set {PORT_ENV} to override."
        ))),
        _ => Err(Error::Port(format!(
            "Several USB-serial ports found ({}). Set {PORT_ENV} to pick one.",
            ports.join(", ")
        ))),
    }
}

pub struct SerialTransport(Box<dyn SerialPort>);

impl SerialTransport {
    /// Open `port`, or the detected one.
    pub fn open(port: Option<&str>) -> Result<Self> {
        let name = match port {
            Some(p) => p.to_string(),
            None => find_port()?,
        };
        let port = serialport::new(&name, BAUDRATE)
            .flow_control(FlowControl::None)
            .timeout(Duration::from_secs(1))
            .open()
            .map_err(|e| Error::Port(format!("can't open {name}: {e}")))?;
        Ok(SerialTransport(port))
    }
}

impl Transport for SerialTransport {
    fn bytes_waiting(&mut self) -> io::Result<usize> {
        Ok(self.0.bytes_to_read()? as usize)
    }

    fn read(&mut self, buf: &mut [u8]) -> io::Result<usize> {
        match self.0.read(buf) {
            Err(e) if e.kind() == io::ErrorKind::TimedOut => Ok(0),
            other => other,
        }
    }

    fn write(&mut self, data: &[u8]) -> io::Result<()> {
        self.0.write_all(data)
    }

    fn flush(&mut self) -> io::Result<()> {
        self.0.flush()
    }

    fn clear_input(&mut self) -> io::Result<()> {
        Ok(self.0.clear(ClearBuffer::Input)?)
    }
}
