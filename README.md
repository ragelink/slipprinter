# CheckPrinter

CheckPrinter is a Python utility to print checks using an ESC/POS compatible printer. The program prompts the user for the necessary details (date, payee, amount, and amount in words) and prints the check with the specified details in the correct positions. This is optimized for the EPSON TM-U295P Slip Printer but should work for most ESC/POS systems.

_*This is a work in progress, with current limited testing, please use at your own risk :-)*_

## Features

- Prompts the user for check details (date, payee, amount, amount in words)
- Prints the check with the specified details using an ESC/POS printer
- Ensures the alignment matches a predefined check template

## Requirements

- Python 3.x
- `python-escpos` library
- `pyusb` library
- ESC/POS compatible printer

## Installation

1. Clone the repository:

    ```sh
    git clone https://github.com/yourusername/checkprinter.git
    cd checkprinter
    ```

2. Create and activate a virtual environment:

    ```sh
    python -m venv venv
    source venv/bin/activate  # On Windows use `venv\Scripts\activate`
    ```

3. Install the required packages:

    ```sh
    pip install -r requirements.txt
    ```

## Usage

1. Run the `print_check.py` script:

    ```sh
    python print_check.py
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

- **Printer Setup**: Update the USB `idVendor` and `idProduct` values in `print_check.py` to match your printer model.
- **Positioning**: Adjust the positioning values in the `print_check` function to match the layout of your check template.

## Testing

Run the tests to ensure the script runs correctly:

```sh
python -m unittest test_print_check.py
```

Contributing

	1.	Fork the repository.
	2.	Create a new branch (git checkout -b feature-branch).
	3.	Commit your changes (git commit -am 'Add new feature').
	4.	Push to the branch (git push origin feature-branch).
	5.	Create a new Pull Request.

License

This project is licensed under the MIT License - see the LICENSE file for details.



