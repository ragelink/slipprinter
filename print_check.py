from escpos.printer import Usb
import textwrap

# Set up the printer (change the USB idVendor and idProduct to match your printer)
printer = Usb(0x04b8, 0x0e15)  # Example values for an Epson printer

def print_check(date, payee, amount, amount_words):
    # Date
    printer.set(align='left')
    printer.text(f"Date: {date}\n")

    # Pay to the Order of
    printer.text(f"Pay to the Order of: {payee}\n")

    # Amount
    printer.set(align='right')
    printer.text(f"${amount}\n")
    
    # Amount in Words
    printer.set(align='left')
    amount_words_wrapped = textwrap.fill(amount_words, width=32)
    printer.text(f"Amount in Words: {amount_words_wrapped}\n")

    # Cut the receipt
    printer.cut()

# Example usage
date = "06/03/2024"
payee = "John Doe"
amount = "1234.56"
amount_words = "One Thousand Two Hundred Thirty-Four Dollars and Fifty-Six Cents"
print_check(date, payee, amount, amount_words)
