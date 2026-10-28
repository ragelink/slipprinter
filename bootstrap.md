# slipprinter conventions

This is the source of truth for how this repo is built. Agent shims (`CLAUDE.md`) point here.

## What this is

Configurable slip printing (check fronts, endorsements, anything else) for the Epson TM-U295 serial slip printer, driven from a CLI and a local web UI.

## Privacy: nothing private goes anywhere public

This repo and its issue tracker are **public**. Never put any of the following in issues, PR titles or bodies, comments, commit messages, code defaults, docs or test fixtures:

- names of real payees, payers, or account holders
- bank account numbers, routing numbers, check numbers, or amounts from real checks
- addresses, phone numbers, emails, signatures, or images of real checks
- hardware serial numbers. USB-serial device paths such as `/dev/cu.usbserial-XXXXXXXX` embed one. Detect the port at runtime; never hard-code it.
- secrets of any kind: tokens, keys, passwords

Fixtures use obviously fake data (`Jane Example`, account and routing numbers starting with `000`, `000-00-0000`, device names containing `TEST`). When describing hardware or a bug in an issue, describe it generically. The scanners enforce this, but they are a backstop, not permission to be careless:

- **gitleaks** with the default secret rules plus PII rules in `.gitleaks.toml`: routing numbers, account numbers, MICR lines, SSNs, USB-serial device paths. Fake values (above) are allowlisted.
- **pre-commit** runs gitleaks, Ruff and the `always` tests before every commit (`make hooks` to install).
- **CI** scans the full git history on every push and PR (`make scan` runs the same thing locally).
- **Issue and PR text** is scanned when posted or edited; a match gets a comment and a failed check. GitHub keeps edit history, so a real leak has to be deleted, not just edited out.

## Layout

```
src/slipprinter/
  connection.py    port detection
  status.py        decoding real-time status (DLE EOT)
  device.py        SlipPrinter: status, wait for slip, guarded print
  profile.py       TM-U295 command table (only documented commands)
  template.py      template schema, validation, render, preview
  words.py         amounts in words
  library.py       built-in + personal template lookup
  cli.py           the `slip` command
  templates/       built-in templates
tests/             pytest, one file per module; fakes.py scripts a printer
samples/           reference images and Epson command listings
```

## Toolchain

| Concern | Tool |
|---|---|
| Environment and dependencies | `uv` (`uv sync`); `uv.lock` is committed |
| Format and lint | Ruff (`make format`, `make lint`), zero warnings |
| Secrets and PII | gitleaks (`make scan`), pre-commit (`make hooks`) |
| Tests | pytest with tier markers |

Docker is deliberately not used: Docker Desktop on macOS can't pass a USB-serial device through to a container, and this tool exists to drive a serial printer on the host.

## Tests

Every test carries exactly one tier marker:

| Marker | Runs | Use for |
|---|---|---|
| `always` | `make test`, pre-commit, every CI run | fast, deterministic, no hardware |
| `sometimes` | `make test-pr`, every PR | integration (e.g. web API end to end) |
| `rarely` | nightly, before release | slow or wide matrix |
| `edge` | before release | expensive or exotic |
| `debug` | only by name: `make test-debug T=<name>` | diagnostics and tests that need the real printer |

Tests never need the printer unless they're `debug`. Use the fake transport or escpos `Dummy` to capture output. Rendering is tested byte-for-byte.

## Hardware facts

- Serial: 9600 8N1, XON/XOFF. Hardware flow control off, because common USB-serial cables leave DSR/CTS unwired.
- The printer and a USB-serial cable are both DTE, so a **null-modem adapter** is required between them.
- Slip only: no roll paper, no cutter. Eject with form feed (`0x0C`); never send `GS V`.
- A job sent with no slip inserted waits in the printer's buffer and prints onto whatever goes in next, so print only after a slip is detected.

## Git and process

- Issues on GitHub; one PR per issue; branches `feature/<n>-<slug>`, `fix/<n>-<slug>`, `chore/<n>-<slug>`.
- No rebases (`git pull --no-rebase`), no force pushes, no amends after review.
- No AI attribution in commits, PRs or comments.
- Plan comment on the issue before coding, learnings during, summary when done.
