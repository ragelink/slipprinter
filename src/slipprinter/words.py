"""Check amounts in words: 1234.56 -> "One Thousand Two Hundred Thirty-Four and 56/100"."""

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

ONES = [
    "Zero", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine",
    "Ten", "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen", "Seventeen", "Eighteen", "Nineteen",
]  # fmt: skip
TENS = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]
SCALES = [(10**9, "Billion"), (10**6, "Million"), (1000, "Thousand")]
MAX_AMOUNT = Decimal("999999999999.99")


class AmountError(ValueError):
    """Not a usable check amount."""


def parse_amount(value: str | int | float | Decimal) -> Decimal:
    """A non-negative amount rounded to cents. Accepts "1,234.56" and "$1234.56"."""
    text = str(value).strip().replace(",", "").removeprefix("$")
    try:
        amount = Decimal(text)
    except InvalidOperation:
        raise AmountError(f"{value!r} is not an amount") from None
    if not amount.is_finite() or amount < 0:
        raise AmountError(f"{value!r} must be zero or more")
    amount = amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if amount > MAX_AMOUNT:
        raise AmountError(f"{value!r} is too large")
    return amount


def _under_thousand(n: int) -> str:
    parts = []
    if n >= 100:
        parts.append(f"{ONES[n // 100]} Hundred")
        n %= 100
    if n >= 20:
        parts.append(TENS[n // 10] + (f"-{ONES[n % 10]}" if n % 10 else ""))
    elif n:
        parts.append(ONES[n])
    return " ".join(parts)


def dollars_in_words(n: int) -> str:
    if n == 0:
        return "Zero"
    parts = []
    for scale, name in SCALES:
        if n >= scale:
            parts.append(f"{_under_thousand(n // scale)} {name}")
            n %= scale
    if n:
        parts.append(_under_thousand(n))
    return " ".join(parts)


def amount_in_words(value: str | int | float | Decimal) -> str:
    amount = parse_amount(value)
    dollars = int(amount)
    cents = int((amount - dollars) * 100)
    return f"{dollars_in_words(dollars)} and {cents:02d}/100"


def format_money(value: str | int | float | Decimal, symbol: str = "$") -> str:
    return f"{symbol}{parse_amount(value):,.2f}"
