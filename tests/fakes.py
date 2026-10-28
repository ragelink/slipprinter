"""A scripted stand-in for the printer's serial port."""

# Real-time status replies (DLE EOT n), decoded per Epson's TM-U295 spec.
IDLE = {1: 0x16, 2: 0x12, 3: 0x12, 5: 0x72}  # online, no error, no slip (as measured)
SLIP_IN = {**IDLE, 5: 0x12}  # paper at both sensors
OFFLINE = {**IDLE, 1: 0x1E}
ERROR = {**IDLE, 1: 0x1E, 2: 0x52}
UNRECOVERABLE = {**IDLE, 1: 0x1E, 2: 0x52, 3: 0x32}
JOB_QUEUED = {**IDLE, 5: 0x7A}  # waiting for a slip, with data in the buffer


class FakeTransport:
    """Answers DLE EOT n from a script of states; each full status() advances one state."""

    def __init__(self, *states, silent=False, stuck=False):
        self.states = list(states) or [IDLE]
        self.silent = silent
        self.stuck = stuck  # while True the job doesn't finish, so ESC v goes unanswered
        self.job_pending = False
        self.written = bytearray()
        self.pending = b""
        self.queries = 0
        self.closed = False

    @property
    def state(self):
        return self.states[min(self.queries // 4, len(self.states) - 1)]

    def write(self, data):
        if data[:2] == b"\x10\x04" and len(data) == 3:
            self.pending = b"" if self.silent else bytes([self.state[data[2]]])
            self.queries += 1
        elif data == b"\x1bv":
            self.job_pending = not self.silent
        else:
            self.written += data
        return len(data)

    def read(self, size=1):
        if not self.pending and self.job_pending and not self.stuck:
            self.pending, self.job_pending = b"\x00", False  # ESC v answer: the job is done
        reply, self.pending = self.pending[:size], self.pending[size:]
        return reply

    def flush(self):
        pass

    def reset_input_buffer(self):
        self.pending = b""

    def close(self):
        self.closed = True


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds
