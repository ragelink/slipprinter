import textwrap

from slipprinter.connection import get_printer


def print_check(printer, date, payee, amount, amount_words):
    # Set positioning based on measurements
    # Use ESC/POS commands to set positions (assuming 1 cm = ~8 characters and 1 cm = ~12 lines for simplicity)

    # Print Date
    printer.set(align="left", font="a", width=1, height=1)
    printer.text("\n" * 1)  # Move down 1 cm
    printer.text(" " * 15)  # Move right 15 cm
    printer.text(f"{date}\n")

    # Print Payee
    printer.text("\n" * 1)  # Move down 1 more cm
    printer.text(" " * 2)  # Move right 2 cm
    printer.text(f"{payee}\n")

    # Print Amount
    printer.text("\n" * 1)  # Move down 1 more cm
    printer.text(" " * 15)  # Move right 15 cm
    printer.text(f"${amount}\n")

    # Print Amount in Words
    printer.text("\n" * 1)  # Move down 1 more cm
    printer.text(" " * 2)  # Move right 2 cm
    amount_words_wrapped = textwrap.fill(amount_words, width=32)
    printer.text(f"{amount_words_wrapped}\n")

    # Eject the slip (the TM-U295 has no cutter)
    printer.control("FF")


def main():
    print("Welcome to the Check Printer Program")
    date = input("Enter the date (MM/DD/YYYY): ")
    payee = input("Enter the payee name: ")
    amount = input("Enter the amount: ")
    amount_words = input("Enter the amount in words: ")

    printer = get_printer()
    print_check(printer, date, payee, amount, amount_words)
    printer.close()
    print("Check printed successfully!")


if __name__ == "__main__":
    main()
