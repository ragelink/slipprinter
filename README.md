# CheckPrinter

CheckPrinter prints checks, endorsements, and any other slip layout on an EPSON TM-U295 (serial) slip printer. Layouts are YAML templates, so a new kind of slip is a file, not code.

_*This is a work in progress, with current limited testing, please use at your own risk :-)*_

## Features

- Templates for check fronts, endorsements and free-text notes, plus your own
- Amount in words generated from the amount, with `*` fill for check protection
- Refuses to print unless the printer is ready and a slip is actually inserted
- Validates everything first: overflowing values are errors, never silently cut off

## Requirements

- Python 3.x
- EPSON TM-U295, serial (RS-232) model
- USB-to-RS232 cable plus a null-modem adapter (the printer and the cable are both DTE, so TX/RX must be crossed)

## Installation

Requires [uv](https://docs.astral.sh/uv/).

```sh
git clone https://github.com/ragelink/slipprinter.git
cd slipprinter
uv sync
```

Check that the printer's USB-serial port is detected (`*` marks the one that will be used):

```sh
uv run slip ports
```

## Usage

```sh
uv run slip status                      # is the printer ready, is a slip in?
uv run slip templates                   # templates and their fields
uv run slip preview check --set payee="Jane Example" --set amount=1234.56
uv run slip print check --set payee="Jane Example" --set amount=1234.56 --set memo=Rent
uv run slip print endorse --set name="Jane Example"
uv run slip ruler                       # column/line ruler for measuring a layout
uv run slip serve --open                # web UI on http://localhost:8295
```

The web UI does the same with a form and a live preview; Print is enabled only once a slip is detected. It listens on 127.0.0.1 only and refuses cross-site requests.

`slip print` validates the values, shows a preview, asks to confirm, then waits for you to insert the slip. Missing required fields are prompted for. The date defaults to today, and `amount_words` is filled in from `amount`.

## Templates

Built-in templates are in `src/slipprinter/templates/`. Put your own in `~/.config/slipprinter/templates/` (or `$SLIP_TEMPLATES`); one with the same name as a built-in replaces it. Keep anything personal there, not in the repo.

```yaml
name: receipt
description: Simple receipt
insert: Insert the slip face up.
orientation: normal        # or rotated (page mode, text along the slip)
font: 5x7                  # 35 columns; 7x7 gives 42
fields:
  date:   {line: 0, col: 0, width: 10, type: date, default: today}
  amount: {line: 2, col: 20, width: 15, type: money, fill: "*"}
  words:  {line: 3, col: 0, width: 35, type: words, source: amount}
text:
  - {line: 0, col: 25, text: RECEIPT, style: bold}
```

Field types: `text`, `multiline` (with `height`), `date`, `money`, `words`. Styles: `bold`, `underline`, `double_width`, `double_height`. Fields that overlap or run off the slip are rejected when the template loads.

## Printer setup

- Connect a USB-to-RS232 cable through a **null-modem adapter** (the printer and the cable are both DTE, so TX/RX must be crossed).
- The USB-serial port is detected automatically (`slip ports`); set `SLIP_PRINTER_PORT` to override it.
- Line settings are 9600 8N1, XON/XOFF. They must match the printer's DIP switches, which the self-test prints: insert a slip, power off, then hold RELEASE while powering on.

## Testing

```sh
make lint   # ruff format + check
make test   # fast tests, no printer needed
```

See [bootstrap.md](bootstrap.md) for test tiers and repo conventions.

Contributing

	1.	Fork the repository.
	2.	Create a new branch (git checkout -b feature-branch).
	3.	Commit your changes (git commit -am 'Add new feature').
	4.	Push to the branch (git push origin feature-branch).
	5.	Create a new Pull Request.

License

This project is licensed under the MIT License - see the LICENSE file for details.



