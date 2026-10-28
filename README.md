# CheckPrinter

CheckPrinter is a Python utility to print checks using an ESC/POS compatible printer. The program prompts the user for the necessary details (date, payee, amount, and amount in words) and prints the check with the specified details in the correct positions. This is optimized for the EPSON TM-U295 (serial) Slip Printer but should work for most ESC/POS systems.

_*This is a work in progress, with current limited testing, please use at your own risk :-)*_

## Features

- Prompts the user for check details (date, payee, amount, amount in words)
- Prints the check with the specified details using an ESC/POS printer
- Ensures the alignment matches a predefined check template

## Requirements

- Python 3.x
- `python-escpos` library
- `pyserial` library
- ESC/POS compatible serial printer
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

1. Run the `print_check.py` script:

    ```sh
    uv run python print_check.py
    ```

2. Follow the prompts to enter the check details:

    ```plaintext
    Welcome to the Check Printer Program
    Enter the date (MM/DD/YYYY): 06/03/2024
    Enter the payee name: John Doe
    Enter the amount: 1234.56
    Enter the amount in words: One Thousand Two Hundred Thirty-Four Dollars and Fifty-Six Cents
    Check printed successfully!
    ```

## Customization

- **Printer Setup**: The USB-serial port is detected automatically; set `SLIP_PRINTER_PORT` to override it. Line settings (9600 8N1, XON/XOFF) live in `src/slipprinter/connection.py` and must match the printer's DIP switches, which the self-test prints (insert a slip, power off, hold RELEASE while powering on).
- **Positioning**: Adjust the positioning values in the `print_check` function to match the layout of your check template.

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



