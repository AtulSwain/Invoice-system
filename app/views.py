"""All screens."""
import base64
import json
import secrets
import time
from datetime import date
from pathlib import Path

from flask import (Blueprint, Response, abort, current_app, flash, g, redirect, render_template, request,
                   send_file, session, url_for)

from . import importer, reports
from .auth import attempt_login, create_user, login_required, owner_required, set_password
from .db import audit, get_settings, now_str, today_ist, transaction
from .invoices import (InvoiceError, NumberingNotConfirmed, allowed_date_range, cancel_invoice, clean_gstin,
                       clean_name, create_invoice, find_customer, get_invoice, get_sequence, gstin_error,
                       live_invoice_count, parse_invoice_form, record_edit_attempt, search_invoices,
                       confirm_sequence)
from .money import MAX_ITEMS, compute_totals, parse_percent, plain
from .pdf import PAD_ROWS, full_address, invoice_pdf, printable_lines

bp = Blueprint("main", __name__)


def db():
    return current_app.get_db()


def logo_path():
    name = get_settings(db()).get("logo_file")
    if not name:
        return None
    path = Path(current_app.config["DATA_DIR"]) / name
    return path if path.exists() else None


# ------------------------------------------------------------------ login

@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user, error = attempt_login(db(), request.form.get("username"), request.form.get("password"))
        if user:
            session.clear()
            session["uid"] = user["id"]
            session["csrf"] = secrets.token_urlsafe(32)
            session["last_seen"] = time.time()
            session.permanent = True
            nxt = request.args.get("next", "")
            return redirect(nxt if nxt.startswith("/") and not nxt.startswith("//") else url_for("main.dashboard"))
        flash(error, "error")
    no_users = db().execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
    return render_template("login.html", no_users=no_users)


@bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    flash("Logged out.", "info")
    return redirect(url_for("main.login"))


# ------------------------------------------------------------------ dashboard & numbering

@bp.route("/")
@login_required
def dashboard():
    today = today_ist().isoformat()
    todays = db().execute(
        "SELECT * FROM invoices WHERE invoice_date = ? OR substr(created_at, 1, 10) = ? "
        "ORDER BY source, number DESC", (today, today)).fetchall()
    return render_template("dashboard.html", seq=get_sequence(db()), todays=todays,
                           todays_total=sum(i["grand_total"] for i in todays if i["status"] == "active"))


@bp.route("/numbering", methods=["GET", "POST"])
@owner_required
def numbering():
    seq = get_sequence(db())
    locked = live_invoice_count(db()) > 0
    if request.method == "POST":
        try:
            number = int(request.form.get("next_number", ""))
            confirm_sequence(db(), g.user, number)
            flash(f"Confirmed. The next invoice will be number {number}.", "success")
            return redirect(url_for("main.dashboard"))
        except ValueError:
            flash("Enter a whole number.", "error")
        except InvoiceError as e:
            flash(str(e), "error")
    return render_template("numbering.html", seq=seq, locked=locked)


# ------------------------------------------------------------------ invoices: create

def customer_options():
    rows = db().execute("SELECT name, address, gstin FROM customers WHERE active = 1 ORDER BY name COLLATE NOCASE")
    return [dict(r) for r in rows]


def blank_form():
    s = get_settings(db())
    return {"invoice_date": today_ist().isoformat(), "customer_name": "", "customer_address": "",
            "customer_gstin": "", "note": s["default_note"],
            "lines": [{"challan_no": "", "description": "", "hsn_code": s["default_hsn"], "qty_text": "",
                       "rate_text": ""}]}


def render_form(data, errors=None):
    first, last = allowed_date_range()
    s = get_settings(db())
    return render_template(
        "invoice_form.html", data=data, errors=errors or [], customers=customer_options(),
        min_date=first.isoformat(), max_date=last.isoformat(), max_items=MAX_ITEMS, seq=get_sequence(db()),
        cgst_rate=s["cgst_rate"], sgst_rate=s["sgst_rate"], default_hsn=s["default_hsn"],
    ), (400 if errors else 200)


@bp.route("/invoices/new")
@login_required
def new_invoice():
    data = blank_form()
    copy_id = request.args.get("copy", type=int)
    if copy_id:
        inv, items = get_invoice(db(), copy_id)
        if inv and inv["source"] == "live":
            data.update(customer_name=inv["customer_name"], customer_address=inv["customer_address"],
                        customer_gstin=inv["customer_gstin"], note=inv["note"])
            data["lines"] = [{"challan_no": it["challan_no"], "description": it["description"],
                              "hsn_code": it["hsn_code"], "qty_text": str(it["qty"]), "rate_text": plain(it["rate"])}
                             for it in items]
    return render_form(data)


@bp.route("/invoices/review", methods=["POST"])
@login_required
def review_invoice():
    data, errors = parse_invoice_form(request.form)
    if errors:
        return render_form(data, errors)
    s = get_settings(db())
    lines = [dict(l) for l in data["lines"]]
    totals = compute_totals(lines, s["cgst_rate"], s["sgst_rate"])
    existing = find_customer(db(), data["customer_name"])
    return render_template("invoice_confirm.html", data=data, lines=lines, totals=totals,
                           cgst_rate=s["cgst_rate"], sgst_rate=s["sgst_rate"], seq=get_sequence(db()),
                           new_customer=existing is None, token=secrets.token_urlsafe(16))


@bp.route("/invoices/save", methods=["POST"])
@login_required
def save_invoice():
    data, errors = parse_invoice_form(request.form)
    if request.form.get("action") == "edit" or errors:
        return render_form(data, errors)
    try:
        invoice_id = create_invoice(db(), g.user, data, client_token=request.form.get("token"))
    except NumberingNotConfirmed as e:
        flash(str(e), "error")
        return render_form(data)
    except InvoiceError as e:
        return render_form(data, [str(e)])
    inv, _ = get_invoice(db(), invoice_id)
    flash(f"Invoice {inv['number']} saved.", "success")
    return redirect(url_for("main.view_invoice", invoice_id=invoice_id))


# ------------------------------------------------------------------ invoices: list / view / print

@bp.route("/invoices")
@login_required
def list_invoices():
    f = {k: request.args.get(k, "").strip() for k in ("from", "to", "customer", "number")}
    number = f["number"] if f["number"].isdigit() else None
    if f["number"] and not number:
        flash("Invoice number must be digits only.", "error")
    rows = search_invoices(db(), f["from"] or None, f["to"] or None, f["customer"] or None, number)
    return render_template("invoice_list.html", rows=rows, f=f, customers=customer_options())


def load_invoice_or_404(invoice_id):
    inv, items = get_invoice(db(), invoice_id)
    if not inv:
        abort(404)
    return inv, items


def invoice_context(inv, items):
    s = get_settings(db())
    lines = printable_lines(inv, items)
    return {"inv": inv, "lines": lines, "blank_rows": max(0, PAD_ROWS - len(lines)), "s": s,
            "address": full_address(s), "has_logo": logo_path() is not None}


@bp.route("/invoices/<int:invoice_id>")
@login_required
def view_invoice(invoice_id):
    inv, items = load_invoice_or_404(invoice_id)
    return render_template("invoice_view.html", **invoice_context(inv, items))


@bp.route("/invoices/<int:invoice_id>/print")
@login_required
def print_invoice(invoice_id):
    inv, items = load_invoice_or_404(invoice_id)
    return render_template("invoice_print.html", autoprint=True, **invoice_context(inv, items))


@bp.route("/invoices/<int:invoice_id>/pdf")
@login_required
def invoice_pdf_view(invoice_id):
    inv, items = load_invoice_or_404(invoice_id)
    pdf = invoice_pdf(inv, items, get_settings(db()), logo_path())
    name = f"Invoice-{inv['number']}{'-imported' if inv['source'] == 'imported' else ''}.pdf"
    disposition = "inline" if request.args.get("inline") else "attachment"
    return Response(pdf, mimetype="application/pdf",
                    headers={"Content-Disposition": f'{disposition}; filename="{name}"'})


@bp.route("/invoices/<int:invoice_id>/edit", methods=["GET", "POST"])
@login_required
def edit_invoice(invoice_id):
    load_invoice_or_404(invoice_id)
    record_edit_attempt(db(), g.user, invoice_id)
    flash("Saved invoices cannot be changed. The owner can cancel it, then use “Copy to new invoice”.", "error")
    return redirect(url_for("main.view_invoice", invoice_id=invoice_id))


@bp.route("/invoices/<int:invoice_id>/cancel", methods=["GET", "POST"])
@owner_required
def cancel(invoice_id):
    inv, _ = load_invoice_or_404(invoice_id)
    if request.method == "POST":
        try:
            cancel_invoice(db(), g.user, invoice_id, request.form.get("reason"))
            flash(f"Invoice {inv['number']} is now CANCELLED. Its number stays used.", "success")
            return redirect(url_for("main.view_invoice", invoice_id=invoice_id))
        except InvoiceError as e:
            flash(str(e), "error")
    return render_template("invoice_cancel.html", inv=inv)


# ------------------------------------------------------------------ customers

@bp.route("/customers")
@login_required
def customers():
    q = request.args.get("q", "").strip()
    sql = "SELECT * FROM customers"
    args = []
    if q:
        sql += " WHERE name LIKE ?"
        args.append(f"%{q}%")
    sql += " ORDER BY active DESC, name COLLATE NOCASE"
    return render_template("customers.html", rows=db().execute(sql, args).fetchall(), q=q)


def customer_form_data():
    return {"name": clean_name(request.form.get("name")), "address": (request.form.get("address") or "").strip(),
            "gstin": clean_gstin(request.form.get("gstin")), "phone": (request.form.get("phone") or "").strip()}


def customer_errors(data, exclude_id=None):
    errors = []
    if not data["name"]:
        errors.append("Party name is required")
    other = find_customer(db(), data["name"]) if data["name"] else None
    if other and other["id"] != exclude_id:
        errors.append(f"A customer named “{other['name']}” already exists")
    if gstin_error(data["gstin"]):
        errors.append(gstin_error(data["gstin"]))
    return errors


@bp.route("/customers/new", methods=["GET", "POST"])
@login_required
def new_customer():
    data = {"name": "", "address": "", "gstin": "", "phone": ""}
    errors = []
    if request.method == "POST":
        data = customer_form_data()
        errors = customer_errors(data)
        if not errors:
            with transaction(db()):
                db().execute("INSERT INTO customers (name, address, gstin, phone, created_at) VALUES (?,?,?,?,?)",
                             (data["name"], data["address"], data["gstin"], data["phone"], now_str()))
                audit(db(), g.user, "customer_created", details=data["name"])
            flash(f"Customer “{data['name']}” added.", "success")
            return redirect(url_for("main.customers"))
    return render_template("customer_form.html", data=data, errors=errors, editing=False)


@bp.route("/customers/<int:customer_id>/edit", methods=["GET", "POST"])
@owner_required
def edit_customer(customer_id):
    row = db().execute("SELECT * FROM customers WHERE id = ?", (customer_id,)).fetchone()
    if not row:
        abort(404)
    data, errors = dict(row), []
    if request.method == "POST":
        data = customer_form_data()
        errors = customer_errors(data, exclude_id=customer_id)
        if not errors:
            with transaction(db()):
                db().execute("UPDATE customers SET name=?, address=?, gstin=?, phone=? WHERE id=?",
                             (data["name"], data["address"], data["gstin"], data["phone"], customer_id))
                audit(db(), g.user, "customer_edited", details=f"{row['name']} -> {data['name']}")
            flash("Customer saved. Old invoices keep the details they were printed with.", "success")
            return redirect(url_for("main.customers"))
    return render_template("customer_form.html", data=data, errors=errors, editing=True, row=row)


@bp.route("/customers/<int:customer_id>/active", methods=["POST"])
@owner_required
def toggle_customer(customer_id):
    row = db().execute("SELECT * FROM customers WHERE id = ?", (customer_id,)).fetchone()
    if not row:
        abort(404)
    with transaction(db()):
        db().execute("UPDATE customers SET active = ? WHERE id = ?", (0 if row["active"] else 1, customer_id))
        audit(db(), g.user, "customer_deactivated" if row["active"] else "customer_reactivated", details=row["name"])
    flash(f"“{row['name']}” {'hidden from the customer list' if row['active'] else 'is active again'}.", "success")
    return redirect(url_for("main.customers"))


# ------------------------------------------------------------------ monthly report

def report_month():
    raw = request.args.get("month", "")
    try:
        y, m = (int(x) for x in raw.split("-"))
        date(y, m, 1)
    except ValueError:
        t = today_ist()
        y, m = t.year, t.month
    return y, m


@bp.route("/reports/monthly")
@owner_required
def monthly_report():
    y, m = report_month()
    rep = reports.monthly_report(db(), y, m)
    return render_template("report.html", rep=rep, month_value=f"{y:04d}-{m:02d}",
                           check=reports.quick_check_text(rep))


@bp.route("/reports/monthly.xlsx")
@owner_required
def monthly_report_xlsx():
    y, m = report_month()
    data = reports.to_xlsx(reports.monthly_report(db(), y, m), get_settings(db()))
    return Response(data, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="Vinayak-Sales-{y:04d}-{m:02d}.xlsx"'})


@bp.route("/reports/monthly.pdf")
@owner_required
def monthly_report_pdf():
    y, m = report_month()
    data = reports.to_pdf(reports.monthly_report(db(), y, m), get_settings(db()))
    return Response(data, mimetype="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="Vinayak-Sales-{y:04d}-{m:02d}.pdf"'})


# ------------------------------------------------------------------ historical import

@bp.route("/import", methods=["GET", "POST"])
@owner_required
def import_bills():
    if request.method == "GET":
        return render_template("import.html", rows=None, errors=[])
    if request.form.get("step") == "confirm":
        raw = base64.b64decode(request.form.get("payload", "")).decode("utf-8")
        rows, errors = importer.parse_csv(db(), raw)
        if errors or not rows:
            return render_template("import.html", rows=rows, errors=errors or ["Nothing to import"]), 400
        if not request.form.get("confirm_columns") or not request.form.get("confirm_numbering"):
            flash("Tick both boxes to confirm before importing.", "error")
            return render_template("import.html", rows=rows, errors=[],
                                   payload=request.form.get("payload")), 400
        count = importer.import_rows(db(), g.user, rows)
        flash(f"{count} past bills imported. They show as “Imported” and do not change invoice numbering.",
              "success")
        return redirect(url_for("main.monthly_report", month=rows[0]["date"][:7]))
    upload = request.files.get("file")
    if not upload or not upload.filename:
        flash("Choose a CSV file first.", "error")
        return render_template("import.html", rows=None, errors=[]), 400
    try:
        raw = upload.read().decode("utf-8-sig")
    except UnicodeDecodeError:
        flash("The file is not a UTF-8 CSV. In Excel use “Save As → CSV UTF-8”.", "error")
        return render_template("import.html", rows=None, errors=[]), 400
    rows, errors = importer.parse_csv(db(), raw)
    return render_template("import.html", rows=rows, errors=errors,
                           payload=base64.b64encode(raw.encode("utf-8")).decode("ascii"))


@bp.route("/import/template.csv")
@owner_required
def import_template():
    return Response(importer.template_csv(), mimetype="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="past-bills-template.csv"'})


# ------------------------------------------------------------------ settings & users

EDITABLE_SETTINGS = ["company_name", "tagline", "address", "pin_code", "mobile", "gstin", "declaration",
                     "footer_left", "signatory_title", "default_note", "default_hsn"]


@bp.route("/settings", methods=["GET", "POST"])
@owner_required
def settings():
    s = get_settings(db())
    errors = []
    if request.method == "POST":
        new = {k: (request.form.get(k) or "").strip() for k in EDITABLE_SETTINGS}
        new["gstin"] = clean_gstin(new["gstin"])
        if gstin_error(new["gstin"]):
            errors.append("Business " + gstin_error(new["gstin"]))
        if new["pin_code"] and not (new["pin_code"].isdigit() and len(new["pin_code"]) == 6):
            errors.append("PIN code must be 6 digits")
        for key in ("company_name", "gstin", "declaration"):
            if not new[key]:
                errors.append(f"{key.replace('_', ' ').capitalize()} cannot be empty")
        try:
            new["cgst_rate"] = parse_percent(request.form.get("cgst_rate", ""))
            new["sgst_rate"] = parse_percent(request.form.get("sgst_rate", ""))
        except ValueError as e:
            errors.append(str(e))
        if not errors:
            changed = {k: v for k, v in new.items() if s.get(k) != v}
            with transaction(db()):
                for k, v in changed.items():
                    db().execute("INSERT INTO settings (key, value) VALUES (?, ?) "
                                 "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (k, v))
                if changed:
                    audit(db(), g.user, "settings_changed",
                          details=json.dumps({k: [s.get(k), v] for k, v in changed.items()}, ensure_ascii=False))
            flash("Settings saved." if changed else "Nothing changed.", "success")
            return redirect(url_for("main.settings"))
        s.update(new)
    users = db().execute("SELECT * FROM users ORDER BY role, username").fetchall()
    return render_template("settings.html", s=s, errors=errors, users=users, has_logo=logo_path() is not None,
                           seq=get_sequence(db()))


@bp.route("/settings/logo", methods=["POST"])
@owner_required
def upload_logo():
    f = request.files.get("logo")
    data_dir = Path(current_app.config["DATA_DIR"])
    if request.form.get("remove"):
        name = ""
    else:
        if not f or not f.filename:
            flash("Choose a PNG or JPG image.", "error")
            return redirect(url_for("main.settings"))
        head = f.read(8)
        f.seek(0)
        if head.startswith(b"\x89PNG"):
            ext = "png"
        elif head.startswith(b"\xff\xd8"):
            ext = "jpg"
        else:
            flash("The logo must be a PNG or JPG image.", "error")
            return redirect(url_for("main.settings"))
        name = f"logo.{ext}"
        data_dir.mkdir(parents=True, exist_ok=True)
        f.save(data_dir / name)
    with transaction(db()):
        db().execute("INSERT INTO settings (key, value) VALUES ('logo_file', ?) "
                     "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (name,))
        audit(db(), g.user, "logo_changed", details=name or "removed")
    flash("Logo updated." if name else "Logo removed.", "success")
    return redirect(url_for("main.settings"))


@bp.route("/logo")
@login_required
def logo():
    path = logo_path()
    if not path:
        abort(404)
    return send_file(path, max_age=300)


@bp.route("/users", methods=["POST"])
@owner_required
def add_user():
    try:
        create_user(db(), request.form.get("username"), request.form.get("password"),
                    request.form.get("role"), by_user=g.user)
        flash("User added.", "success")
    except ValueError as e:
        flash(str(e), "error")
    return redirect(url_for("main.settings") + "#users")


@bp.route("/users/<int:user_id>/password", methods=["POST"])
@owner_required
def reset_password(user_id):
    try:
        set_password(db(), user_id, request.form.get("password"), by_user=g.user)
        flash("Password changed and account unlocked.", "success")
    except ValueError as e:
        flash(str(e), "error")
    return redirect(url_for("main.settings") + "#users")


@bp.route("/users/<int:user_id>/active", methods=["POST"])
@owner_required
def toggle_user(user_id):
    row = db().execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if not row:
        abort(404)
    if row["id"] == g.user["id"]:
        flash("You cannot switch off your own account.", "error")
    else:
        with transaction(db()):
            db().execute("UPDATE users SET active = ?, failed_logins = 0, locked_until = NULL WHERE id = ?",
                         (0 if row["active"] else 1, user_id))
            audit(db(), g.user, "user_disabled" if row["active"] else "user_enabled", details=row["username"])
        flash("User updated.", "success")
    return redirect(url_for("main.settings") + "#users")


@bp.route("/audit")
@owner_required
def audit_log():
    rows = db().execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT 500").fetchall()
    return render_template("audit.html", rows=rows)
