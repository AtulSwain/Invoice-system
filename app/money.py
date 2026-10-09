"""Money parsing, GST calculation and Indian-style formatting.

Every amount is an int number of paise. Decimal is used only for the tax
percentage step, rounded half-up to the nearest paisa.
"""
import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

MAX_ITEMS = 15
_RATE_RE = re.compile(r"^\d+(\.\d{1,2})?$")


def parse_qty(text) -> int:
    text = str(text).strip().replace(",", "")
    if not text.isdigit() or int(text) <= 0:
        raise ValueError("Quantity must be a whole number above 0")
    return int(text)


def parse_rupees(text, *, allow_zero=False) -> int:
    """'12.5' -> 1250 paise. Up to 2 decimals, positive."""
    text = str(text).strip().replace(",", "").replace("₹", "")
    if not _RATE_RE.match(text):
        raise ValueError("Enter an amount like 125 or 125.50 (up to 2 decimals)")
    paise = int((Decimal(text) * 100).to_integral_value())
    if paise <= 0 and not allow_zero:
        raise ValueError("Amount must be more than 0")
    return paise


def parse_percent(text) -> str:
    text = str(text).strip()
    try:
        value = Decimal(text)
    except InvalidOperation:
        raise ValueError("Rate must be a number such as 2.5")
    if value < 0 or value > 50 or value.as_tuple().exponent < -3:
        raise ValueError("Rate must be between 0 and 50, up to 3 decimals")
    return format(value.normalize(), "f")


def tax_on(net_paise: int, rate_percent: str) -> int:
    value = Decimal(net_paise) * Decimal(rate_percent) / Decimal(100)
    return int(value.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def compute_totals(lines, cgst_rate: str, sgst_rate: str) -> dict:
    """lines: iterable of dicts with int 'qty' and int 'rate' (paise). Adds 'amount' to each."""
    net = 0
    qty = 0
    for line in lines:
        line["amount"] = line["qty"] * line["rate"]
        net += line["amount"]
        qty += line["qty"]
    cgst = tax_on(net, cgst_rate)
    sgst = tax_on(net, sgst_rate)
    return {"total_qty": qty, "net_total": net, "cgst": cgst, "sgst": sgst, "grand_total": net + cgst + sgst}


def indian_group(n: int) -> str:
    """1234567 -> '12,34,567'."""
    s = str(abs(n))
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        s = ",".join(parts) + "," + tail
    return ("-" if n < 0 else "") + s


def inr(paise: int, symbol: bool = True) -> str:
    """123456789 paise -> '₹12,34,567.89'."""
    paise = int(paise or 0)
    sign = "-" if paise < 0 else ""
    rupees, p = divmod(abs(paise), 100)
    return f"{sign}{'₹' if symbol else ''}{indian_group(rupees)}.{p:02d}"


def plain(paise: int) -> str:
    """Amount without grouping, for form fields: 1250 -> '12.50'."""
    paise = int(paise or 0)
    sign = "-" if paise < 0 else ""
    rupees, p = divmod(abs(paise), 100)
    return f"{sign}{rupees}.{p:02d}"


def rupees_decimal(paise: int) -> Decimal:
    return (Decimal(int(paise or 0)) / 100).quantize(Decimal("0.01"))
