"""CSV import of historical (ledger) bills.

Imported bills are stored with source='imported'. They appear in reports but
are kept apart from the live numbering sequence, so they never move it.
"""
import csv
import io
import re
from datetime import datetime

from .db import audit, get_settings, now_str, transaction
from .invoices import clean_name, get_or_create_customer
from .money import parse_rupees, tax_on

COLUMNS = ["date", "bill no.", "challan no.", "party name", "quantity", "taxable value", "cgst", "sgst", "total"]
_ALIASES = {
    "date": "date", "billdate": "date",
    "billno": "bill_no", "billnumber": "bill_no", "invoiceno": "bill_no", "no": "bill_no",
    "challanno": "challan_no", "challan": "challan_no",
    "partyname": "party", "party": "party", "customer": "party", "name": "party",
    "quantity": "qty", "qty": "qty", "qtypcs": "qty", "pcs": "qty",
    "taxablevalue": "taxable", "taxable": "taxable", "amount": "taxable", "nettotal": "taxable",
    "cgst": "cgst", "sgst": "sgst",
    "total": "total", "grandtotal": "total",
}
REQUIRED = ["date", "bill_no", "party", "taxable"]


def template_csv() -> str:
    return ",".join(c.title() if c not in ("cgst", "sgst") else c.upper() for c in COLUMNS) + "\n"


def _parse_date(text):
    text = text.strip()
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%Y-%m-%d", "%d/%m/%y", "%d-%m-%y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    raise ValueError(f"date '{text}' is not like dd/mm/yyyy")


def _money(text, label, allow_zero=True):
    try:
        return parse_rupees(text, allow_zero=allow_zero)
    except ValueError:
        raise ValueError(f"{label} '{text}' is not a valid amount")


def parse_csv(conn, raw: str):
    """Returns (rows, errors). Nothing is written."""
    settings = get_settings(conn)
    reader = csv.reader(io.StringIO(raw.lstrip("﻿")))
    lines = [r for r in reader if any(cell.strip() for cell in r)]
    if not lines:
        return [], ["The file is empty"]
    header = [_ALIASES.get(re.sub(r"[^a-z]", "", h.lower())) for h in lines[0]]
    missing = [c for c in REQUIRED if c not in header]
    if missing:
        return [], [f"Missing column(s): {', '.join(missing)}. Expected: {', '.join(COLUMNS)}"]

    rows, errors, seen = [], [], set()
    for line_no, cells in enumerate(lines[1:], start=2):
        rec = {}
        for key, cell in zip(header, cells):
            if key:
                rec[key] = cell.strip()
        try:
            d = _parse_date(rec.get("date", ""))
            if not rec.get("bill_no", "").isdigit():
                raise ValueError(f"bill no. '{rec.get('bill_no', '')}' must be a whole number")
            number = int(rec["bill_no"])
            party = clean_name(rec.get("party"))
            if not party:
                raise ValueError("party name is empty")
            qty_text = rec.get("qty", "").replace(",", "")
            if qty_text and not qty_text.isdigit():
                raise ValueError(f"quantity '{qty_text}' must be a whole number")
            qty = int(qty_text or 0)
            taxable = _money(rec.get("taxable", ""), "taxable value")
            cgst = _money(rec["cgst"], "CGST") if rec.get("cgst") else tax_on(taxable, settings["cgst_rate"])
            sgst = _money(rec["sgst"], "SGST") if rec.get("sgst") else tax_on(taxable, settings["sgst_rate"])
            total = _money(rec["total"], "total") if rec.get("total") else taxable + cgst + sgst
            if abs(total - (taxable + cgst + sgst)) > 1:
                raise ValueError(
                    f"total {total / 100:.2f} does not equal taxable + CGST + SGST "
                    f"({(taxable + cgst + sgst) / 100:.2f}). Check the column meanings."
                )
            if number in seen:
                raise ValueError(f"bill no. {number} appears twice in the file")
            if conn.execute("SELECT 1 FROM invoices WHERE source='imported' AND number=?", (number,)).fetchone():
                raise ValueError(f"bill no. {number} was already imported")
            seen.add(number)
            rows.append({"date": d.isoformat(), "number": number, "challan_no": rec.get("challan_no", ""),
                         "party": party, "qty": qty, "taxable": taxable, "cgst": cgst, "sgst": sgst,
                         "total": total})
        except ValueError as e:
            errors.append(f"Line {line_no}: {e}")
    return rows, errors


def import_rows(conn, user, rows):
    settings = get_settings(conn)
    with transaction(conn):
        for r in rows:
            customer_id = get_or_create_customer(conn, r["party"])
            cust = conn.execute("SELECT * FROM customers WHERE id = ?", (customer_id,)).fetchone()
            cur = conn.execute(
                """INSERT INTO invoices (source, number, invoice_date, customer_id, customer_name, customer_address,
                       customer_gstin, note, challan_no, total_qty, net_total, cgst_rate, sgst_rate, cgst, sgst,
                       grand_total, created_by, created_at)
                   VALUES ('imported',?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (r["number"], r["date"], customer_id, cust["name"], cust["address"], cust["gstin"],
                 settings["default_note"], r["challan_no"], r["qty"], r["taxable"], settings["cgst_rate"],
                 settings["sgst_rate"], r["cgst"], r["sgst"], r["total"], user["username"], now_str()),
            )
            audit(conn, user, "invoice_imported", cur.lastrowid, f"Ledger bill {r['number']} for {r['party']}")
    return len(rows)
