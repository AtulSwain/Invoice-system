"""Invoice rules: validation, numbering, saving, cancelling and searching."""
import re
from datetime import date

from .db import audit, get_settings, now_str, today_ist, transaction
from .money import MAX_ITEMS, compute_totals, parse_qty, parse_rupees

GSTIN_RE = re.compile(r"^\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")


class NumberingNotConfirmed(Exception):
    pass


class InvoiceError(Exception):
    pass


def clean_name(text) -> str:
    return " ".join(str(text or "").split())


def clean_gstin(text) -> str:
    return re.sub(r"\s", "", str(text or "")).upper()


def gstin_error(gstin: str):
    if gstin and not GSTIN_RE.match(gstin):
        return "GSTIN must be 15 characters, like 27ABCDE1234F1Z5"
    return None


def financial_year_start(d: date) -> date:
    return date(d.year if d.month >= 4 else d.year - 1, 4, 1)


def allowed_date_range(today: date = None):
    today = today or today_ist()
    return financial_year_start(today), today


# ---------------------------------------------------------------- numbering

def get_sequence(conn):
    return conn.execute("SELECT * FROM invoice_sequence WHERE id = 1").fetchone()


def live_invoice_count(conn) -> int:
    return conn.execute("SELECT COUNT(*) FROM invoices WHERE source = 'live'").fetchone()[0]


def confirm_sequence(conn, user, number: int):
    """Owner confirms (and may change) the next number. The number can only be
    changed while no live invoice exists; afterwards it is fixed forever."""
    if number < 1:
        raise InvoiceError("Invoice number must be 1 or more")
    with transaction(conn):
        seq = get_sequence(conn)
        if live_invoice_count(conn) and number != seq["next_number"]:
            raise InvoiceError("Invoices already exist, so the number sequence can no longer be changed.")
        conn.execute(
            "UPDATE invoice_sequence SET next_number = ?, confirmed = 1, confirmed_by = ?, confirmed_at = ? WHERE id = 1",
            (number, user["username"], now_str()),
        )
        audit(conn, user, "numbering_confirmed", details=f"Next invoice number confirmed as {number}")


# ---------------------------------------------------------------- validation

def parse_invoice_form(form, today: date = None):
    """Turn submitted form fields into clean invoice data.
    Returns (data, errors). `form` behaves like a werkzeug MultiDict."""
    errors = []
    first, last = allowed_date_range(today)

    raw_date = (form.get("invoice_date") or "").strip()
    inv_date = None
    try:
        inv_date = date.fromisoformat(raw_date)
    except ValueError:
        errors.append("Choose a valid date")
    if inv_date and not (first <= inv_date <= last):
        errors.append(
            f"Date must be between {first:%d/%m/%Y} and {last:%d/%m/%Y} (this financial year, not in the future)"
        )

    name = clean_name(form.get("customer_name"))
    if not name:
        errors.append("Customer name (M/s) is required")
    address = (form.get("customer_address") or "").strip()
    gstin = clean_gstin(form.get("customer_gstin"))
    if gstin_error(gstin):
        errors.append("Party's " + gstin_error(gstin))

    columns = {k: form.getlist(k) for k in ("challan_no", "description", "hsn_code", "qty", "rate")}
    rows = max((len(v) for v in columns.values()), default=0)
    lines = []
    for i in range(rows):
        cell = {k: (v[i].strip() if i < len(v) else "") for k, v in columns.items()}
        if not any(cell.values()):
            continue  # completely empty row is ignored
        row_no = len(lines) + 1
        line = {"challan_no": cell["challan_no"], "description": cell["description"], "hsn_code": cell["hsn_code"],
                "qty_text": cell["qty"], "rate_text": cell["rate"]}
        if not cell["description"]:
            errors.append(f"Item {row_no}: description is required")
        try:
            line["qty"] = parse_qty(cell["qty"])
        except ValueError as e:
            errors.append(f"Item {row_no}: {e}")
        try:
            line["rate"] = parse_rupees(cell["rate"])
        except ValueError as e:
            errors.append(f"Item {row_no}: Rate - {e}")
        lines.append(line)

    if not lines:
        errors.append("Add at least one item")
    if len(lines) > MAX_ITEMS:
        errors.append(f"An invoice can have at most {MAX_ITEMS} items")

    data = {
        "invoice_date": inv_date.isoformat() if inv_date else raw_date,
        "customer_name": name,
        "customer_address": address,
        "customer_gstin": gstin,
        "note": (form.get("note") or "").strip(),
        "lines": lines,
    }
    return data, errors


# ---------------------------------------------------------------- customers

def find_customer(conn, name):
    return conn.execute("SELECT * FROM customers WHERE name = ? COLLATE NOCASE", (clean_name(name),)).fetchone()


def get_or_create_customer(conn, name, address="", gstin="", phone=""):
    """Must be called inside a transaction. Fills blank address/GSTIN on an existing customer."""
    existing = find_customer(conn, name)
    if existing:
        if address and not existing["address"]:
            conn.execute("UPDATE customers SET address = ? WHERE id = ?", (address, existing["id"]))
        if gstin and not existing["gstin"]:
            conn.execute("UPDATE customers SET gstin = ? WHERE id = ?", (gstin, existing["id"]))
        return existing["id"]
    cur = conn.execute(
        "INSERT INTO customers (name, address, gstin, phone, created_at) VALUES (?,?,?,?,?)",
        (clean_name(name), address, gstin, phone, now_str()),
    )
    return cur.lastrowid


# ---------------------------------------------------------------- saving

def create_invoice(conn, user, data, client_token=None):
    """Save a validated invoice and give it the next number. Returns the invoice id.

    Everything happens in one BEGIN IMMEDIATE transaction: read the next number,
    insert the invoice, advance the counter. If anything fails nothing is saved
    and the number is not used, so numbers are never skipped or repeated."""
    if not data["lines"]:
        raise InvoiceError("Add at least one item")
    with transaction(conn):
        if client_token:
            dup = conn.execute("SELECT id FROM invoices WHERE client_token = ?", (client_token,)).fetchone()
            if dup:
                return dup["id"]  # same form submitted twice (double-click / back button)
        seq = get_sequence(conn)
        if not seq["confirmed"]:
            raise NumberingNotConfirmed("The owner must confirm the starting invoice number first.")
        number = seq["next_number"]
        settings = get_settings(conn)
        lines = [dict(line) for line in data["lines"]]
        totals = compute_totals(lines, settings["cgst_rate"], settings["sgst_rate"])
        customer_id = get_or_create_customer(conn, data["customer_name"], data["customer_address"],
                                             data["customer_gstin"])
        cur = conn.execute(
            """INSERT INTO invoices (source, number, invoice_date, customer_id, customer_name, customer_address,
                   customer_gstin, note, total_qty, net_total, cgst_rate, sgst_rate, cgst, sgst, grand_total,
                   client_token, created_by, created_at)
               VALUES ('live',?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (number, data["invoice_date"], customer_id, data["customer_name"], data["customer_address"],
             data["customer_gstin"], data["note"], totals["total_qty"], totals["net_total"],
             settings["cgst_rate"], settings["sgst_rate"], totals["cgst"], totals["sgst"],
             totals["grand_total"], client_token, user["username"], now_str()),
        )
        invoice_id = cur.lastrowid
        for sr_no, line in enumerate(lines, start=1):
            conn.execute(
                """INSERT INTO invoice_items (invoice_id, sr_no, challan_no, description, hsn_code, qty, rate, amount)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (invoice_id, sr_no, line["challan_no"], line["description"], line["hsn_code"],
                 line["qty"], line["rate"], line["amount"]),
            )
        updated = conn.execute(
            "UPDATE invoice_sequence SET next_number = next_number + 1 WHERE id = 1 AND next_number = ?", (number,)
        ).rowcount
        if updated != 1:  # cannot happen under the write lock; refuse rather than risk a duplicate
            raise InvoiceError("Invoice number changed while saving. Please try again.")
        audit(conn, user, "invoice_created", invoice_id,
              f"Invoice {number} for {data['customer_name']}, grand total {totals['grand_total']} paise")
    return invoice_id


def cancel_invoice(conn, user, invoice_id, reason):
    reason = (reason or "").strip()
    if not reason:
        raise InvoiceError("Please give a reason for cancelling")
    with transaction(conn):
        inv = conn.execute("SELECT * FROM invoices WHERE id = ?", (invoice_id,)).fetchone()
        if not inv:
            raise InvoiceError("Invoice not found")
        if inv["status"] == "cancelled":
            raise InvoiceError("This invoice is already cancelled")
        conn.execute(
            "UPDATE invoices SET status = 'cancelled', cancelled_at = ?, cancelled_by = ?, cancel_reason = ? WHERE id = ?",
            (now_str(), user["username"], reason, invoice_id),
        )
        audit(conn, user, "invoice_cancelled", invoice_id, f"Invoice {inv['number']} cancelled: {reason}")


def record_edit_attempt(conn, user, invoice_id):
    with transaction(conn):
        audit(conn, user, "invoice_edit_attempt", invoice_id, "Edit refused: saved invoices cannot be changed")


# ---------------------------------------------------------------- reading

def get_invoice(conn, invoice_id):
    inv = conn.execute("SELECT * FROM invoices WHERE id = ?", (invoice_id,)).fetchone()
    if not inv:
        return None, []
    items = conn.execute("SELECT * FROM invoice_items WHERE invoice_id = ? ORDER BY sr_no", (invoice_id,)).fetchall()
    return inv, items


def search_invoices(conn, date_from=None, date_to=None, customer=None, number=None, limit=500):
    sql = "SELECT * FROM invoices WHERE 1=1"
    args = []
    if date_from:
        sql += " AND invoice_date >= ?"
        args.append(date_from)
    if date_to:
        sql += " AND invoice_date <= ?"
        args.append(date_to)
    if customer:
        sql += " AND customer_name LIKE ?"
        args.append(f"%{customer.strip()}%")
    if number:
        sql += " AND number = ?"
        args.append(int(number))
    sql += " ORDER BY invoice_date DESC, source, number DESC LIMIT ?"
    args.append(limit)
    return conn.execute(sql, args).fetchall()
