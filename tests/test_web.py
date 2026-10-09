"""Screens, roles, login lockout and the full invoice flow through the browser forms."""
import base64
import re
import time
import zlib

from app.db import today_ist
from tests.conftest import Client


def pdf_text(pdf: bytes) -> bytes:
    out = b""
    for raw in re.findall(rb"stream\r?\n(.*?)endstream", pdf, re.S):
        data = raw.strip()
        if data.endswith(b"~>"):  # ReportLab streams: ASCII85 then Flate
            data = base64.a85decode(data[:-2])
        try:
            out += zlib.decompress(data)
        except zlib.error:
            out += data
    return out


def save_via_forms(client, name="Swastik Enterprises", qty="12", rate="150"):
    base = {"invoice_date": today_ist().isoformat(), "customer_name": name, "customer_address": "Vasai",
            "customer_gstin": "", "note": "LABOUR CHARGES ONLY", "challan_no": "C-1",
            "description": "Trouser stitching", "hsn_code": "998821", "qty": qty, "rate": rate}
    r = client.post("/invoices/review", base)
    assert r.status_code == 200 and b"Please check before saving" in r.data
    token = r.data.split(b'name="token" value="')[1].split(b'"')[0].decode()
    return client.post("/invoices/save", {**base, "token": token, "action": "save"}, follow_redirects=True)


def test_login_required(app):
    c = Client(app)
    r = c.get("/")
    assert r.status_code == 302 and "/login" in r.headers["Location"]


def test_worker_full_invoice_flow(app, worker_client, confirmed, conn):
    r = save_via_forms(worker_client, name="New Party Pvt Ltd")
    assert b"Invoice 198 saved" in r.data
    assert b"TAX INVOICE" in r.data and b"27CDXPS0112F2ZE" in r.data
    assert b"Rupees One Thousand Eight Hundred Ninety and Paise" not in r.data  # 12*150=1800 -> 1890.00
    assert b"Rupees One Thousand Eight Hundred Ninety Only" in r.data
    # new customer saved for next time
    assert conn.execute("SELECT 1 FROM customers WHERE name = 'New Party Pvt Ltd'").fetchone()
    inv = conn.execute("SELECT * FROM invoices").fetchone()
    assert (inv["net_total"], inv["cgst"], inv["sgst"], inv["grand_total"]) == (180000, 4500, 4500, 189000)
    # print and PDF
    assert worker_client.get(f"/invoices/{inv['id']}/print").status_code == 200
    pdf = worker_client.get(f"/invoices/{inv['id']}/pdf")
    assert pdf.status_code == 200 and pdf.data.startswith(b"%PDF")
    # list and search
    assert b"New Party Pvt Ltd" in worker_client.get("/invoices?number=198").data
    # audit
    assert conn.execute("SELECT COUNT(*) FROM audit_log WHERE action = 'invoice_created'").fetchone()[0] == 1


def test_worker_cannot_save_until_confirmed(app, worker_client, conn):
    r = save_via_forms(worker_client)
    assert b"must confirm" in r.data
    assert conn.execute("SELECT COUNT(*) FROM invoices").fetchone()[0] == 0


def test_invalid_form_shows_errors(app, worker_client, confirmed):
    r = worker_client.post("/invoices/review", {"invoice_date": today_ist().isoformat(), "customer_name": ""})
    assert r.status_code == 400
    assert b"Customer name" in r.data and b"Add at least one item" in r.data


def test_worker_blocked_from_owner_pages(app, worker_client, confirmed, conn):
    save_via_forms(worker_client)
    inv_id = conn.execute("SELECT id FROM invoices").fetchone()[0]
    for url in ["/reports/monthly", "/reports/monthly.xlsx", "/reports/monthly.pdf", "/settings", "/import",
                "/audit", "/numbering", f"/invoices/{inv_id}/cancel", "/customers/1/edit"]:
        assert worker_client.get(url).status_code == 403, url
    assert worker_client.post(f"/invoices/{inv_id}/cancel", {"reason": "x"}).status_code == 403
    assert worker_client.post("/settings", {"cgst_rate": "9"}).status_code == 403
    assert worker_client.post("/users", {"username": "x", "password": "12345678", "role": "owner"}).status_code == 403
    assert worker_client.post("/customers/1/active").status_code == 403
    assert conn.execute("SELECT status FROM invoices").fetchone()[0] == "active"


def test_worker_can_add_customer_but_not_duplicate(app, worker_client, conn):
    r = worker_client.post("/customers/new", {"name": "Fresh Traders", "address": "", "gstin": "", "phone": ""},
                           follow_redirects=True)
    assert b"Fresh Traders" in r.data
    r = worker_client.post("/customers/new", {"name": "jainam CREATION", "address": "", "gstin": "", "phone": ""})
    assert b"already exists" in r.data


def test_owner_cancel_and_edit_attempt_logged(app, owner_client, confirmed, conn):
    save_via_forms(owner_client)
    inv_id = conn.execute("SELECT id FROM invoices").fetchone()[0]
    r = owner_client.get(f"/invoices/{inv_id}/edit", follow_redirects=True)
    assert b"cannot be changed" in r.data
    r = owner_client.post(f"/invoices/{inv_id}/cancel", {"reason": "party returned goods"}, follow_redirects=True)
    assert b"CANCELLED" in r.data
    actions = [r[0] for r in conn.execute("SELECT action FROM audit_log WHERE invoice_id = ? ORDER BY id", (inv_id,))]
    assert actions == ["invoice_created", "invoice_edit_attempt", "invoice_cancelled"]
    pdf = owner_client.get(f"/invoices/{inv_id}/pdf").data
    assert b"CANCELLED" in pdf_text(pdf)


def test_owner_pages_load(app, owner_client, confirmed):
    save_via_forms(owner_client)
    for url in ["/", "/invoices/new", "/invoices", "/customers", "/reports/monthly", "/settings", "/import", "/audit",
                "/numbering"]:
        assert owner_client.get(url).status_code == 200, url
    x = owner_client.get("/reports/monthly.xlsx")
    assert x.status_code == 200 and x.data[:2] == b"PK"


def test_deactivated_customer_hidden_from_picker(app, owner_client, conn):
    cid = conn.execute("SELECT id FROM customers WHERE name = 'Hareesh Enterprises'").fetchone()[0]
    owner_client.post(f"/customers/{cid}/active")
    page = owner_client.get("/invoices/new").data
    assert b'"Hareesh Enterprises"' not in page and b"Swastik Enterprises" in page


def test_settings_change_rates_for_new_invoices_only(app, owner_client, confirmed, conn):
    save_via_forms(owner_client)
    s = {r["key"]: r["value"] for r in conn.execute("SELECT * FROM settings")}
    s.update(cgst_rate="6", sgst_rate="6", pin_code="401209")
    r = owner_client.post("/settings", s, follow_redirects=True)
    assert b"Settings saved" in r.data
    save_via_forms(owner_client)
    rows = conn.execute("SELECT cgst_rate, cgst FROM invoices ORDER BY number").fetchall()
    assert [(r[0], r[1]) for r in rows] == [("2.5", 4500), ("6", 10800)]


def test_lockout_after_five_failures(app):
    c = Client(app)
    for _ in range(5):
        c.login("worker", "wrong-password")
    r = c.login("worker", "worker-pass-1")
    assert b"locked" in r.data
    assert c.get("/").status_code == 302


def test_session_expires_after_8_hours_idle(app, worker_client):
    assert worker_client.get("/").status_code == 200
    with worker_client.c.session_transaction() as s:
        s["last_seen"] = time.time() - 8 * 3600 - 5
    assert worker_client.get("/").status_code == 302


def test_post_without_csrf_rejected(app, worker_client):
    r = worker_client.c.post("/customers/new", data={"name": "Sneaky"})
    assert r.status_code == 400
