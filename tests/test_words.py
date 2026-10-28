from decimal import Decimal

import pytest

from slipprinter.words import AmountError, amount_in_words, format_money, parse_amount

pytestmark = pytest.mark.always


@pytest.mark.parametrize(
    ("amount", "words"),
    [
        ("0", "Zero and 00/100"),
        ("0.07", "Zero and 07/100"),
        ("1", "One and 00/100"),
        ("13.50", "Thirteen and 50/100"),
        ("20", "Twenty and 00/100"),
        ("21.01", "Twenty-One and 01/100"),
        ("100", "One Hundred and 00/100"),
        ("110", "One Hundred Ten and 00/100"),
        ("999.99", "Nine Hundred Ninety-Nine and 99/100"),
        ("1000", "One Thousand and 00/100"),
        ("1234.56", "One Thousand Two Hundred Thirty-Four and 56/100"),
        ("10019", "Ten Thousand Nineteen and 00/100"),
        ("1000001", "One Million One and 00/100"),
        ("2500000000", "Two Billion Five Hundred Million and 00/100"),
        ("999999999999.99",
         "Nine Hundred Ninety-Nine Billion Nine Hundred Ninety-Nine Million "
         "Nine Hundred Ninety-Nine Thousand Nine Hundred Ninety-Nine and 99/100"),
    ],
)  # fmt: skip
def test_amount_in_words(amount, words):
    assert amount_in_words(amount) == words


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("1,234.56", "1234.56"), ("$12", "12.00"), (" 7.005 ", "7.01"), ("0.004", "0.00"), (5, "5.00")],
)
def test_parse_amount_normalizes_and_rounds_half_up(raw, expected):
    assert parse_amount(raw) == Decimal(expected)


@pytest.mark.parametrize("raw", ["", "abc", "-1", "NaN", "inf", "1e15", "12.3.4"])
def test_parse_amount_rejects_bad_input(raw):
    with pytest.raises(AmountError):
        parse_amount(raw)


def test_format_money_groups_thousands():
    assert format_money("1234567.8") == "$1,234,567.80"
    assert format_money("5", symbol="") == "5.00"
