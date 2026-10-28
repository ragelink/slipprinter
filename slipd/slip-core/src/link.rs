//! Talking to the slip printer: status, waiting for a slip, and guarded printing.
//!
//! A job sent with no slip inserted sits in the printer's buffer and prints onto
//! whatever goes in next, so nothing is sent until a slip is detected.

use std::io;
use std::time::{Duration, Instant};

use crate::status::{PrinterStatus, DLE_EOT, QUERIES};
use crate::{Error, Result};

pub const INIT: &[u8] = b"\x1b@";
/// ESC c 4 n: stop printing when the top (bit 4) or bottom (bit 5) sensor runs out
/// of paper. Off by default, which lets a job print into thin air past the slip.
pub const STOP_AT_PAPER_END: &[u8] = b"\x1bc4\x30";
pub const EJECT: &[u8] = b"\x0c";
/// ESC v is answered only after everything before it has printed.
const PAPER_STATUS: &[u8] = b"\x1bv";
/// The printer's flow control: it sends XOFF when its 512-byte buffer is nearly full and
/// XON when there's room. USB-serial drivers don't reliably honor these, so we do it here.
pub const XON: u8 = 0x11;
pub const XOFF: u8 = 0x13;
/// Small writes, so little is in flight when an XOFF arrives.
pub const CHUNK: usize = 16;

/// The serial port, or a scripted stand-in for it.
pub trait Transport {
    /// Bytes from the printer waiting to be read.
    fn bytes_waiting(&mut self) -> io::Result<usize>;
    /// Up to `buf.len()` bytes, waiting up to the port's timeout. 0 means nothing arrived.
    fn read(&mut self, buf: &mut [u8]) -> io::Result<usize>;
    fn write(&mut self, data: &[u8]) -> io::Result<()>;
    fn flush(&mut self) -> io::Result<()>;
    fn clear_input(&mut self) -> io::Result<()>;
}

/// Time, injected so tests don't wait.
pub trait Clock {
    /// Seconds since some fixed point.
    fn now(&mut self) -> f64;
    fn sleep(&mut self, seconds: f64);
}

pub struct SystemClock(Instant);

impl Default for SystemClock {
    fn default() -> Self {
        SystemClock(Instant::now())
    }
}

impl Clock for SystemClock {
    fn now(&mut self) -> f64 {
        self.0.elapsed().as_secs_f64()
    }

    fn sleep(&mut self, seconds: f64) {
        std::thread::sleep(Duration::from_secs_f64(seconds));
    }
}

pub struct Printer<T, C = SystemClock> {
    transport: T,
    clock: C,
    pub poll_interval: f64,
}

impl<T: Transport> Printer<T> {
    pub fn new(transport: T) -> Self {
        Printer::with_clock(transport, SystemClock::default())
    }
}

impl<T: Transport, C: Clock> Printer<T, C> {
    pub fn with_clock(transport: T, clock: C) -> Self {
        Printer { transport, clock, poll_interval: 0.25 }
    }

    pub fn transport(&self) -> &T {
        &self.transport
    }

    fn read_byte(&mut self) -> Result<Option<u8>> {
        let mut buf = [0u8; 1];
        Ok((self.transport.read(&mut buf)? == 1).then_some(buf[0]))
    }

    fn send(&mut self, data: &[u8]) -> Result<()> {
        self.transport.write(data)?;
        Ok(self.transport.flush()?)
    }

    pub fn query(&mut self, n: u8) -> Result<u8> {
        self.transport.clear_input()?;
        self.send(&[DLE_EOT[0], DLE_EOT[1], n])?;
        let mut reply = self.read_byte()?;
        while let Some(XON | XOFF) = reply {
            reply = self.read_byte()?; // flow control, not the answer
        }
        reply.ok_or_else(|| {
            Error::Status(format!(
                "No answer to DLE EOT {n}. Is the printer on, and is the null-modem adapter in place?"
            ))
        })
    }

    pub fn status(&mut self) -> Result<PrinterStatus> {
        let mut replies = [0u8; 4];
        for (reply, n) in replies.iter_mut().zip(QUERIES) {
            *reply = self.query(n)?;
        }
        PrinterStatus::from_bytes(replies)
    }

    pub fn check_ready(&self, status: &PrinterStatus) -> Result<()> {
        let mut problems = status.problems();
        if status.waiting_for_slip {
            problems.push("another job is waiting in the printer's buffer: power-cycle the printer to clear it");
        }
        if problems.is_empty() {
            Ok(())
        } else {
            Err(Error::NotReady(problems.join("; ")))
        }
    }

    /// Poll until a slip is inserted. Fails at once if the printer isn't ready.
    pub fn wait_for_slip(&mut self, timeout: f64) -> Result<PrinterStatus> {
        let deadline = self.clock.now() + timeout;
        loop {
            let status = self.status()?;
            self.check_ready(&status)?;
            if status.slip_present() {
                return Ok(status);
            }
            if self.clock.now() >= deadline {
                return Err(Error::NoSlip(format!("No slip inserted within {timeout} s")));
            }
            let interval = self.poll_interval;
            self.clock.sleep(interval);
        }
    }

    /// Wait until everything sent so far has printed.
    ///
    /// ESC v (paper sensor status) is processed in order with the print data, so
    /// its reply only arrives once the job ahead of it is done. Slip sensors can't
    /// tell us that: a long sheet still covers them after it's ejected.
    pub fn wait_for_job(&mut self, timeout: f64) -> Result<()> {
        self.transport.clear_input()?;
        self.send(PAPER_STATUS)?;
        let deadline = self.clock.now() + timeout;
        while self.clock.now() < deadline {
            match self.read_byte()? {
                Some(reply) if reply & 0x90 == 0 => return Ok(()), // ESC v replies look like 0xx0xxxx
                Some(_) => {}
                None => {
                    let interval = self.poll_interval;
                    self.clock.sleep(interval);
                }
            }
        }
        let status = self.status()?;
        let problems = status.problems();
        let detail = if problems.is_empty() { String::new() } else { format!(": {}", problems.join("; ")) };
        Err(Error::NotReady(format!("Job didn't finish within {timeout} s{detail}")))
    }

    /// Send `data` in small chunks, pausing whenever the printer sends XOFF until it sends XON.
    pub fn write_paced(&mut self, data: &[u8], stall_timeout: f64) -> Result<()> {
        let mut paused = false;
        let mut stalled_since: Option<f64> = None;
        let mut chunks = data.chunks(CHUNK);
        loop {
            let waiting = self.transport.bytes_waiting()?;
            if waiting > 0 {
                let mut buf = vec![0u8; waiting];
                let n = self.transport.read(&mut buf)?;
                for &byte in &buf[..n] {
                    match byte {
                        XOFF => paused = true,
                        XON => paused = false,
                        _ => {}
                    }
                }
            }
            if paused {
                let now = self.clock.now();
                let since = *stalled_since.get_or_insert(now);
                if now - since >= stall_timeout {
                    return Err(Error::NotReady(format!("Printer stopped accepting data for {stall_timeout} s")));
                }
                let interval = self.poll_interval / 10.0;
                self.clock.sleep(interval);
                continue;
            }
            stalled_since = None;
            match chunks.next() {
                Some(chunk) => self.send(chunk)?,
                None => return Ok(()),
            }
        }
    }

    /// Print `job` on the inserted slip, then `finish` (usually [`EJECT`]), and wait until the printer is done.
    ///
    /// With `slip_timeout` > 0, wait that long for a slip; otherwise one must already be in.
    pub fn print_job(&mut self, job: &[u8], finish: &[u8], slip_timeout: f64, job_timeout: f64) -> Result<()> {
        if slip_timeout > 0.0 {
            self.wait_for_slip(slip_timeout)?;
        } else {
            let status = self.status()?;
            self.check_ready(&status)?;
            if !status.slip_present() {
                return Err(Error::NoSlip("No slip inserted".into()));
            }
        }
        self.transport.clear_input()?;
        let data = [INIT, STOP_AT_PAPER_END, job, finish].concat();
        self.write_paced(&data, 60.0)?;
        self.wait_for_job(job_timeout)
    }
}

/// Scripted stand-ins for the serial port and the clock, for tests here and in dependent crates.
pub mod fake {
    use std::cell::Cell;
    use std::collections::VecDeque;
    use std::io;
    use std::rc::Rc;

    use super::{Clock, Transport, XOFF, XON};

    pub const IDLE: [u8; 4] = [0x16, 0x12, 0x12, 0x72]; // online, no error, no slip (as measured)
    pub const SLIP_IN: [u8; 4] = [0x16, 0x12, 0x12, 0x12]; // paper at both sensors
    pub const OFFLINE: [u8; 4] = [0x1E, 0x12, 0x12, 0x72];
    pub const JOB_QUEUED: [u8; 4] = [0x16, 0x12, 0x12, 0x7A]; // waiting for a slip, data in the buffer

    /// Answers DLE EOT n from a script of states; each full status() advances one state.
    #[derive(Default)]
    pub struct FakeTransport {
        pub states: Vec<[u8; 4]>,
        /// Never answer anything.
        pub silent: bool,
        /// The job never finishes, so ESC v goes unanswered.
        pub stuck: bool,
        /// Send XOFF once this many print bytes have arrived...
        pub xoff_after: Option<usize>,
        /// ...and XON after this many polls while paused.
        pub xon_after_polls: usize,
        /// A flow-control byte sent ahead of every status reply.
        pub flow_byte_before_reply: Option<u8>,
        pub written: Vec<u8>,
        /// The size of every print-data write.
        pub writes: Vec<usize>,
        pub queries: usize,
        pending: VecDeque<u8>,
        job_pending: bool,
        polls_paused: Option<usize>,
    }

    impl FakeTransport {
        pub fn new(states: &[[u8; 4]]) -> Self {
            FakeTransport { states: states.to_vec(), ..Default::default() }
        }

        fn state(&self) -> [u8; 4] {
            let states = if self.states.is_empty() { &[IDLE][..] } else { &self.states };
            states[(self.queries / 4).min(states.len() - 1)]
        }
    }

    impl Transport for FakeTransport {
        fn bytes_waiting(&mut self) -> io::Result<usize> {
            if let Some(polls) = self.polls_paused.as_mut() {
                *polls += 1;
                if *polls >= self.xon_after_polls {
                    self.pending.push_back(XON);
                    self.polls_paused = None;
                }
            }
            Ok(self.pending.len())
        }

        fn read(&mut self, buf: &mut [u8]) -> io::Result<usize> {
            if self.pending.is_empty() && self.job_pending && !self.stuck {
                self.pending.push_back(0x00); // ESC v answer: the job is done
                self.job_pending = false;
            }
            let n = buf.len().min(self.pending.len());
            for slot in &mut buf[..n] {
                *slot = self.pending.pop_front().unwrap();
            }
            Ok(n)
        }

        fn write(&mut self, data: &[u8]) -> io::Result<()> {
            if data.len() == 3 && data[..2] == [0x10, 0x04] {
                if !self.silent {
                    self.pending.extend(self.flow_byte_before_reply);
                    let index = [1, 2, 3, 5].iter().position(|&n| n == data[2]).unwrap();
                    self.pending.push_back(self.state()[index]);
                }
                self.queries += 1;
            } else if data == b"\x1bv" {
                self.job_pending = !self.silent;
            } else {
                let before = self.written.len();
                self.written.extend_from_slice(data);
                self.writes.push(data.len());
                if let Some(limit) = self.xoff_after {
                    if before < limit && self.written.len() >= limit {
                        self.pending.push_back(XOFF);
                        self.polls_paused = Some(0);
                    }
                }
            }
            Ok(())
        }

        fn flush(&mut self) -> io::Result<()> {
            Ok(())
        }

        fn clear_input(&mut self) -> io::Result<()> {
            self.pending.clear();
            Ok(())
        }
    }

    /// A clock that only moves when slept; clones share the same time.
    #[derive(Clone, Default)]
    pub struct FakeClock(pub Rc<Cell<f64>>);

    impl Clock for FakeClock {
        fn now(&mut self) -> f64 {
            self.0.get()
        }

        fn sleep(&mut self, seconds: f64) {
            self.0.set(self.0.get() + seconds);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::fake::*;
    use super::*;

    fn printer(transport: FakeTransport) -> (Printer<FakeTransport, FakeClock>, FakeClock) {
        let clock = FakeClock::default();
        (Printer::with_clock(transport, clock.clone()), clock)
    }

    #[test]
    fn status_reads_all_four_queries() {
        let (mut p, _) = printer(FakeTransport::new(&[SLIP_IN]));
        assert!(p.status().unwrap().slip_present());
        assert_eq!(p.transport().queries, 4);
    }

    #[test]
    fn query_skips_flow_control_bytes() {
        for flow in [XON, XOFF] {
            let mut t = FakeTransport::new(&[IDLE]);
            t.flow_byte_before_reply = Some(flow);
            let (mut p, _) = printer(t);
            assert_eq!(p.query(1).unwrap(), 0x16);
        }
    }

    #[test]
    fn silent_printer_is_a_status_error() {
        let mut t = FakeTransport::new(&[IDLE]);
        t.silent = true;
        let (mut p, _) = printer(t);
        assert!(matches!(p.status(), Err(Error::Status(m)) if m.contains("null-modem")));
    }

    #[test]
    fn print_refuses_without_a_slip() {
        let (mut p, _) = printer(FakeTransport::new(&[IDLE]));
        assert!(matches!(p.print_job(b"hi", EJECT, 0.0, 10.0), Err(Error::NoSlip(_))));
        assert!(p.transport().written.is_empty());
    }

    #[test]
    fn print_refuses_when_a_job_is_queued() {
        let (mut p, _) = printer(FakeTransport::new(&[JOB_QUEUED]));
        assert!(matches!(p.print_job(b"hi", EJECT, 0.0, 10.0), Err(Error::NotReady(m)) if m.contains("power-cycle")));
    }

    #[test]
    fn print_frames_the_job() {
        let (mut p, _) = printer(FakeTransport::new(&[SLIP_IN]));
        p.print_job(b"hello\n", EJECT, 0.0, 10.0).unwrap();
        assert_eq!(p.transport().written, b"\x1b@\x1bc4\x30hello\n\x0c");
    }

    #[test]
    fn waits_for_a_slip() {
        let (mut p, clock) = printer(FakeTransport::new(&[IDLE, IDLE, SLIP_IN]));
        p.print_job(b"x", EJECT, 30.0, 10.0).unwrap();
        assert_eq!(clock.0.get(), 0.5);
    }

    #[test]
    fn slip_wait_times_out() {
        let (mut p, _) = printer(FakeTransport::new(&[IDLE]));
        assert_eq!(p.wait_for_slip(1.0).unwrap_err().to_string(), "No slip inserted within 1 s");
    }

    #[test]
    fn slip_wait_stops_when_the_printer_goes_offline() {
        let (mut p, _) = printer(FakeTransport::new(&[IDLE, OFFLINE]));
        assert!(matches!(p.wait_for_slip(30.0), Err(Error::NotReady(_))));
    }

    #[test]
    fn writes_in_small_chunks() {
        let (mut p, _) = printer(FakeTransport::new(&[SLIP_IN]));
        p.write_paced(&[0x41; 40], 60.0).unwrap();
        assert_eq!(p.transport().writes, [16, 16, 8]);
    }

    #[test]
    fn pauses_on_xoff_until_xon() {
        let mut t = FakeTransport::new(&[SLIP_IN]);
        t.xoff_after = Some(32);
        t.xon_after_polls = 5;
        let (mut p, clock) = printer(t);
        p.write_paced(&[0x41; 64], 60.0).unwrap();
        assert_eq!(p.transport().written.len(), 64);
        assert!(clock.0.get() > 0.0, "paused while XOFF was in effect");
    }

    #[test]
    fn gives_up_when_xon_never_comes() {
        let mut t = FakeTransport::new(&[SLIP_IN]);
        t.xoff_after = Some(16);
        t.xon_after_polls = usize::MAX;
        let (mut p, _) = printer(t);
        let err = p.write_paced(&[0x41; 64], 1.0).unwrap_err();
        assert_eq!(err.to_string(), "Printer stopped accepting data for 1 s");
        assert_eq!(p.transport().written.len(), 16);
    }

    #[test]
    fn job_that_never_finishes_times_out() {
        let mut t = FakeTransport::new(&[SLIP_IN]);
        t.stuck = true;
        let (mut p, _) = printer(t);
        let err = p.print_job(b"x", EJECT, 0.0, 2.0).unwrap_err();
        assert_eq!(err.to_string(), "Job didn't finish within 2 s");
    }
}
