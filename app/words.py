"""Amounts in words using the Indian numbering system (thousand, lakh, crore)."""

_ONES = [
    "Zero", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten",
    "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen", "Seventeen", "Eighteen", "Nineteen",
]
_TENS = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]


def _below_100(n: int) -> str:
    if n < 20:
        return _ONES[n]
    tens, ones = divmod(n, 10)
    return _TENS[tens] + (" " + _ONES[ones] if ones else "")


def _below_1000(n: int) -> str:
    hundreds, rest = divmod(n, 100)
    parts = []
    if hundreds:
        parts.append(_ONES[hundreds] + " Hundred")
    if rest:
        parts.append(_below_100(rest))
    return " ".join(parts)


def number_in_words(n: int) -> str:
    """12345 -> 'Twelve Thousand Three Hundred Forty Five'."""
    if n < 0:
        raise ValueError("negative amounts are not supported")
    if n == 0:
        return "Zero"
    parts = []
    crores, n = divmod(n, 10_000_000)
    lakhs, n = divmod(n, 100_000)
    thousands, n = divmod(n, 1000)
    if crores:
        # Above 99 crore the crore count itself is spelled out in the Indian system
        parts.append(number_in_words(crores) + " Crore")
    if lakhs:
        parts.append(_below_100(lakhs) + " Lakh")
    if thousands:
        parts.append(_below_100(thousands) + " Thousand")
    if n:
        parts.append(_below_1000(n))
    return " ".join(parts)


def amount_in_words(paise: int) -> str:
    """1234550 -> 'Rupees Twelve Thousand Three Hundred Forty Five and Paise Fifty Only'."""
    rupees, p = divmod(int(paise), 100)
    text = "Rupees " + number_in_words(rupees)
    if p:
        text += " and Paise " + _below_100(p)
    return text + " Only"
