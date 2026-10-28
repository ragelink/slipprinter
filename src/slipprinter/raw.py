"""Raw commands in Epson manual notation, checked against the TM-U295 command table.

    ESC "@"            ESC p 0 25 250         "Hello" LF          0x1B 0x40

Names (ESC, GS, DLE, LF, FF, HT, CR, CAN, NUL), numbers (decimal or 0x hex) and
quoted text become bytes. The result must be a sequence of commands the
printer supports, with in-range parameters, plus printable text.
"""

import shlex

from slipprinter.profile import COMMANDS, UNSUPPORTED, Command

NAMES = {"NUL": 0x00, "HT": 0x09, "LF": 0x0A, "FF": 0x0C, "CR": 0x0D, "CAN": 0x18, "DLE": 0x10, "ESC": 0x1B,
         "GS": 0x1D, "EOT": 0x04, "SP": 0x20}  # fmt: skip
BY_LENGTH = sorted(COMMANDS, key=lambda c: -len(c.prefix))
# Commands that print or move the slip; sending them with no slip queues them in the buffer.
MOVES_PAPER = {"LF", "FF", "ESC *", "ESC J", "ESC K", "ESC d", "ESC e", "ESC q"}


class RawCommandError(ValueError):
    """Unparseable notation, or a command or parameter the printer doesn't support."""


MNEMONICS = sorted(
    [(c.mnemonic.split(), c.prefix) for c in COMMANDS]
    + [(mnemonic.split(), None) for mnemonic, _ in UNSUPPORTED.values()],
    key=lambda m: -len(m[0]),
)
PREFIXES = {tuple(words): prefix for words, prefix in MNEMONICS}
REASONS = {tuple(mnemonic.split()): reason for mnemonic, reason in UNSUPPORTED.values()}


def parse(text: str) -> bytes:
    try:
        tokens = shlex.split(text, posix=True)
    except ValueError as e:
        raise RawCommandError(f"can't parse: {e}") from None
    quoted = _quoted_spans(text)
    out = bytearray()
    i = 0
    while i < len(tokens):
        if i in quoted:
            out += tokens[i].encode("cp437")
            i += 1
            continue
        words = next((w for w, _ in MNEMONICS if _unquoted_match(tokens, quoted, i, w)), None)
        if words is not None:
            prefix = PREFIXES[tuple(words)]
            if prefix is None:
                reason = REASONS[tuple(words)]
                raise RawCommandError(f"{' '.join(words)} isn't supported by the TM-U295: {reason}")
            out += prefix
            i += len(words)
            continue
        token = tokens[i]
        if token.upper() in NAMES:
            out.append(NAMES[token.upper()])
        elif len(token) == 1 and not token.isdigit():
            out += token.encode("ascii")
        else:
            try:
                value = int(token, 0)
            except ValueError:
                raise RawCommandError(f"'{token}' isn't a command, name, number or \"quoted text\"") from None
            if not 0 <= value <= 255:
                raise RawCommandError(f"{token} doesn't fit in a byte")
            out.append(value)
        i += 1
    validate(bytes(out))
    return bytes(out)


def _unquoted_match(tokens: list[str], quoted: set[int], i: int, words: list[str]) -> bool:
    return tokens[i : i + len(words)] == words and not quoted & set(range(i, i + len(words)))


def _quoted_spans(text: str) -> set[int]:
    """Indexes of tokens that were quoted, so "10" stays text instead of a number."""
    lexer = shlex.shlex(text, posix=False)
    lexer.whitespace_split = True
    return {i for i, tok in enumerate(lexer) if tok[:1] in "\"'"}


def _match(data: bytes, i: int) -> Command | None:
    return next((c for c in BY_LENGTH if data.startswith(c.prefix, i)), None)


def validate(data: bytes) -> bool:
    """Raise unless every byte is printable text or a supported command. Returns whether it uses paper."""
    uses_paper = False
    i = 0
    while i < len(data):
        byte = data[i]
        if byte >= 0x20:  # printable text
            uses_paper = True
            i += 1
            continue
        command = _match(data, i)
        if command is None:
            for prefix, (mnemonic, reason) in UNSUPPORTED.items():
                if data.startswith(prefix, i):
                    raise RawCommandError(f"{mnemonic} isn't supported by the TM-U295: {reason}")
            raise RawCommandError(f"unknown command at byte {i}: 0x{byte:02x}")
        uses_paper |= command.mnemonic in MOVES_PAPER
        i = _check(command, data, i + len(command.prefix))
    return uses_paper


def _need(data: bytes, i: int, count: int, command: Command) -> None:
    if i + count > len(data):
        raise RawCommandError(f"{command.mnemonic} is missing parameters")


def _check(command: Command, data: bytes, i: int) -> int:
    for name, allowed in command.params:
        _need(data, i, 1, command)
        if data[i] not in allowed:
            raise RawCommandError(f"{command.mnemonic}: {name}={data[i]} is out of range")
        i += 1
    if command.variable == "tabs":
        stops = []
        while True:
            _need(data, i, 1, command)
            if data[i] == 0:
                break
            stops.append(data[i])
            i += 1
        if len(stops) > 32 or stops != sorted(set(stops)):
            raise RawCommandError("ESC D: up to 32 tab stops, in increasing order")
        return i + 1
    if command.variable == "characters":
        _need(data, i, 3, command)
        y, c1, c2 = data[i : i + 3]
        if y != 1 or not 32 <= c1 <= c2 <= 126:
            raise RawCommandError("ESC &: needs y=1 and 32 <= c1 <= c2 <= 126")
        i += 3
        for _ in range(c2 - c1 + 1):
            _need(data, i, 1, command)
            x = data[i]
            if x > 10:
                raise RawCommandError(f"ESC &: x={x} is wider than 10 columns")
            _need(data, i + 1, x, command)
            i += 1 + x
        return i
    if command.variable == "image":
        _need(data, i, 3, command)
        m, n_low, n_high = data[i : i + 3]
        width = n_low + n_high * 256
        if m not in (0, 1) or width > (210 if m == 0 else 420):
            raise RawCommandError("ESC *: m is 0 (up to 210 dots) or 1 (up to 420 dots)")
        _need(data, i + 3, width, command)
        return i + 3 + width
    return i
