import pytest
from werkzeug.datastructures import MultiDict

from app.money import compute_totals, indian_group, inr, parse_qty, parse_rupees, tax_on
from app.words import amount_in_words, number_in_words


def test_tax_is_2_5_percent_each():
    lines = [{"qty": 10, "rate": 12550}]  # 10 x 125.50
    t = compute_totals(lines, "2.5", "2.5")
    assert lines[0]["amount"] == 125500
    assert t["net_total"] == 125500
    assert t["cgst"] == 3138  # 31.375 -> 31.38 (half up)
    assert t["sgst"] == 3138
    assert t["grand_total"] == 125500 + 3138 + 3138


@pytest.mark.parametrize("net,expected", [
    (10000, 250),   # 100.00 -> 2.50
    (10010, 250),   # 100.10 -> 2.5025 -> 2.50
    (10020, 251),   # 100.20 -> 2.505 -> 2.51 (half up, not banker's rounding)
    (10060, 252),   # 100.60 -> 2.515 -> 2.52
    (1, 0), (20, 1), (0, 0),
])
def test_tax_rounding_half_up(net, expected):
    assert tax_on(net, "2.5") == expected


def test_grand_total_equals_sum_of_rounded_figures():
    for net_qty, rate in [(7, 333), (13, 1999), (1, 1), (999, 12345)]:
        t = compute_totals([{"qty": net_qty, "rate": rate}], "2.5", "2.5")
        assert t["grand_total"] == t["net_total"] + t["cgst"] + t["sgst"]


def test_rates_come_from_settings_values():
    t = compute_totals([{"qty": 1, "rate": 10000}], "6", "6")
    assert (t["cgst"], t["sgst"]) == (600, 600)


def test_parse_inputs():
    assert parse_rupees("125.5") == 12550
    assert parse_rupees("1,250.75") == 125075
    assert parse_qty("12") == 12
    for bad in ["0", "-1", "1.5", "abc", ""]:
        with pytest.raises(ValueError):
            parse_qty(bad)
    for bad in ["0", "1.234", "-5", "abc", ""]:
        with pytest.raises(ValueError):
            parse_rupees(bad)


def test_indian_grouping():
    assert indian_group(0) == "0"
    assert indian_group(999) == "999"
    assert indian_group(1000) == "1,000"
    assert indian_group(100000) == "1,00,000"
    assert indian_group(12345678) == "1,23,45,678"
    assert inr(123456789) == "₹12,34,567.89"
    assert inr(5, symbol=False) == "0.05"


@pytest.mark.parametrize("n,words", [
    (0, "Zero"),
    (1, "One"),
    (100, "One Hundred"),
    (1000, "One Thousand"),
    (100000, "One Lakh"),
    (10000000, "One Crore"),
    (12345, "Twelve Thousand Three Hundred Forty Five"),
    (110, "One Hundred Ten"),
    (2050001, "Twenty Lakh Fifty Thousand One"),
    (999999999, "Ninety Nine Crore Ninety Nine Lakh Ninety Nine Thousand Nine Hundred Ninety Nine"),
    (1234567890, "One Hundred Twenty Three Crore Forty Five Lakh Sixty Seven Thousand Eight Hundred Ninety"),
])
def test_number_in_words(n, words):
    assert number_in_words(n) == words


def test_amount_in_words_with_paise():
    assert amount_in_words(1234550) == "Rupees Twelve Thousand Three Hundred Forty Five and Paise Fifty Only"
    assert amount_in_words(0) == "Rupees Zero Only"
    assert amount_in_words(1) == "Rupees Zero and Paise One Only"
    assert amount_in_words(1_000_000_000) == "Rupees One Crore Only"
    assert amount_in_words(100) == "Rupees One Only"


def test_form_validation_messages(app):
    from app.invoices import parse_invoice_form
    form = MultiDict({"invoice_date": "2000-01-01", "customer_name": " "})
    form.add("description", "x")
    form.add("qty", "0")
    form.add("rate", "1.234")
    _, errors = parse_invoice_form(form)
    text = " ".join(errors)
    assert "Date must be between" in text
    assert "Customer name" in text
    assert "Quantity" in text
    assert "Rate" in text


def test_form_requires_an_item(app):
    from app.invoices import parse_invoice_form
    from app.db import today_ist
    _, errors = parse_invoice_form(MultiDict({"invoice_date": today_ist().isoformat(), "customer_name": "A"}))
    assert errors == ["Add at least one item"]
