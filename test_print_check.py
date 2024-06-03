import unittest
from print_check import print_check

class TestPrintCheck(unittest.TestCase):
    def test_print_check(self):
        # Since we cannot test the actual printing, we can check if the function runs without errors
        date = "06/03/2024"
        payee = "John Doe"
        amount = "1234.56"
        amount_words = "One Thousand Two Hundred Thirty-Four Dollars and Fifty-Six Cents"
        
        try:
            print_check(date, payee, amount, amount_words)
        except Exception as e:
            self.fail(f"print_check() raised {type(e).__name__} unexpectedly: {e}")

if __name__ == "__main__":
    unittest.main()
