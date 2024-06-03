import re
from escpos.printer import Usb

# Set up the printer (change the USB idVendor and idProduct to match your printer)
printer = Usb(0x04b8, 0x0e15)  # Example values for an Epson printer

def parse_instruction(instruction):
    # Strip comments and whitespace
    instruction = instruction.strip().split('//')[0].strip()
    
    # Check if instruction is empty or a comment
    if not instruction:
        return None
    
    # Parse command and parameters
    if instruction.startswith("ESC"):
        command = b'\x1b' + instruction[4:].encode('ascii')
    elif instruction.startswith("GS"):
        command = b'\x1d' + instruction[3:].encode('ascii')
    elif instruction.startswith("LF"):
        command = b'\x0a'
    else:
        command = instruction.encode('ascii')
    
    return command

def send_instructions(instructions):
    for instruction in instructions:
        command = parse_instruction(instruction)
        if command:
            printer._raw(command)

def main():
    # Sample instructions (replace with actual input or file read)
    instructions = [
        'ESC "@"',  # Initialize printer
        'ESC "3" 18',  # Set line spacing
        'ESC "a" 1',  # Select justification: Centering
        'GS "!" 0x11',  # Select character size: (horizontal (times 2) x vertical (times 2))
        '0xC9 0xCD 0xCD 0xCD 0xCD 0xCD 0xCD 0xCD 0xCD 0xCD 0xCD 0xCD 0xBB LF',
        '0xBA 0x20 0x20 0x20 0x45 0x50 0x53 0x4F 0x4E 0x20 0x20 0x20 0xBA LF',
        '0xBA 0x20 0x20 0x20 GS "!" 0x00 "Thank you " GS "!" 0x11 0x20 0x20 0x20 0xBA LF',
        '0xC8 0xCD 0xCD 0xCD 0xCD 0xCD 0xCD 0xCD 0xCD 0xCD 0xCD 0xCD 0xBC LF',
        'ESC "2"',  # Initialize line spacing
        'ESC "a" 0',  # Select justification: Left
        '"TM-Uxxx                            6.75" LF',
        '"TM-Hxxx                            6.00" LF',
        '"PS-xxx                             1.70" LF LF',
        'GS "!" 0x01',  # Select character size: horizontal (times 1) x vertical (times 2)
        '"TOTAL                             14.45" LF',
        'GS "!" 0x00',  # Select character size: Normal
        '"---------------------------------------" LF',
        '"PAID                              50.00" LF',
        '"CHANGE                            35.55" LF',
        'ESC "p" 0 2 20',  # Generate pulse
        'GS "V" 66 0',  # Select cut mode and cut paper
    ]

    send_instructions(instructions)

if __name__ == "__main__":
    main()
