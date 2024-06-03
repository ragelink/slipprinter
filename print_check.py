from escpos.printer import Usb
import textwrap

# Set up the printer (change the USB idVendor and idProduct to match your printer)
printer = Usb(0x04b8, 0x0e15)  # Example values for an Epson printer

def print_check(date, payee, amount, amount_words):
    # Set positioning based on measurements
    # Use ESC/POS commands to set positions (assuming 1 cm = ~8 characters and 1 cm = ~12 lines for simplicity)
    
    # Print Date
    printer.set(align='left', font='a', width=1, height=1)
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

    # Cut the receipt
    printer.cut()

def main():
    print("Welcome to the Check Printer Program")
    date = input("Enter the date (MM/DD/YYYY): ")
    payee = input("Enter the payee name: ")
    amount = input("Enter the amount: ")
    amount_words = input("Enter the amount in words: ")
    
    print_check(date, payee, amount, amount_words)
    print("Check printed successfully!")

if __name__ == "__main__":
    main()