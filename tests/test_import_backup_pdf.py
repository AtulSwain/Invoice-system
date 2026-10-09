from datetime import date, timedelta

from app import importer, reports
from app.backup import run_backup
from app.db import get_settings
from app.invoices import create_invoice, get_invoice, get_sequence
from app.pdf import invoice_pdf
from tests.conftest import invoice_data

CSV = """Date,Bill No.,Challan No.,Party Name,Quantity,Taxable Value,CGST,SGST,Total
01/08/2026,133,C1,Jainam Creation,100,10000,250,250,10500
02/08/2026,134,,Brand New Party,50,5000.50,,,
"""


def test_import_parses_and_keeps_numbering_separate(conn, owner, confirmed):
    rows, errors = importer.parse_csv(conn, CSV)
    assert errors == []
    assert rows[1]["cgst"] == 12501 and rows[1]["total"] == 500050 + 2 * 12501
    importer.import_rows(conn, owner, rows)
    assert get_sequence(conn)["next_number"] == 198
    create_invoice(conn, owner, invoice_data())
    assert get_sequence(conn)["next_number"] == 199
    rep = reports.monthly_report(conn, 2026, 8)
    assert rep["bill_count"] == 2 and rep["imported_count"] == 2
    assert rep["rows"][0]["status"] == "Active (Imported)"
    assert rep["totals"]["net_total"] == 1000000 + 500050
    # re-import is refused
    _, errors = importer.parse_csv(conn, CSV)
    assert any("already imported" in e for e in errors)


def test_import_rejects_mismatched_totals(conn):
    bad = CSV.splitlines()[0] + "\n01/08/2026,140,,X,1,1000,25,25,9999\n"
    _, errors = importer.parse_csv(conn, bad)
    assert errors and "does not equal" in errors[0]


def test_backup_keeps_30_days(app, tmp_path):
    bdir = tmp_path / "bk"
    bdir.mkdir()
    today = date(2026, 10, 9)
    for days in (0, 10, 29, 30, 45):
        (bdir / f"invoices-{(today - timedelta(days=days)).isoformat()}.db").write_text("old")
    (bdir / "notes.txt").write_text("keep me")
    run_backup(app.config["DATABASE_PATH"], bdir, today)
    names = sorted(p.name for p in bdir.iterdir())
    assert names == ["invoices-2026-09-10.db", "invoices-2026-09-29.db", "invoices-2026-10-09.db", "notes.txt"]
    # today's backup already existed, so it was not overwritten
    assert (bdir / "invoices-2026-10-09.db").read_text() == "old"


def test_backup_is_a_real_database(app, tmp_path):
    import sqlite3
    path = run_backup(app.config["DATABASE_PATH"], tmp_path / "b2", date(2026, 10, 9))
    c = sqlite3.connect(path)
    assert c.execute("SELECT next_number FROM invoice_sequence").fetchone()[0] == 198
    c.close()


def test_invoice_pdf(conn, owner, confirmed):
    inv_id = create_invoice(conn, owner, invoice_data(lines=[(i + 1, "10") for i in range(15)]))
    inv, items = get_invoice(conn, inv_id)
    pdf = invoice_pdf(inv, items, get_settings(conn))
    assert pdf.startswith(b"%PDF") and b"/Count 1" in pdf
