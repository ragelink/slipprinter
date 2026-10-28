import unittest

import pytest
from escpos.printer import Dummy

from print_check import print_check


@pytest.mark.always
class TestPrintCheck(unittest.TestCase):
    def test_print_check(self):
        # A Dummy printer captures the output instead of sending it to the slip printer
        printer = Dummy()
        date = "06/03/2024"
        payee = "John Doe"
        amount = "1234.56"
        amount_words = "One Thousand Two Hundred Thirty-Four Dollars and Fifty-Six Cents"

        print_check(printer, date, payee, amount, amount_words)

        output = printer.output
        for field in (date, payee, f"${amount}"):
            self.assertIn(field.encode(), output)
        self.assertTrue(output.endswith(b"\x0c"))  # slip is ejected


if __name__ == "__main__":
    unittest.main()
