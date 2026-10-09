"""Builds samples/sample_invoice.pdf from made-up test data in a throwaway database,
for comparing with the paper pad.   python scripts/make_sample_pdf.py"""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.db import connect, get_settings, init_db, today_ist  # noqa: E402
from app.invoices import confirm_sequence, create_invoice, get_invoice  # noqa: E402
from app.pdf import invoice_pdf  # noqa: E402

LINES = [("1021", "Trouser stitching - formal", "998821", 120, "45.00"),
         ("1022", "Trouser stitching - cargo", "998821", 80, "52.50"),
         ("1023", "Trouser alteration", "998821", 35, "18.75")]


def main():
    with tempfile.TemporaryDirectory() as tmp:
        conn = connect(Path(tmp) / "sample.db")
        init_db(conn)
        user = {"id": None, "username": "sample"}
        confirm_sequence(conn, user, 198)
        data = {"invoice_date": today_ist().isoformat(), "customer_name": "Jainam Creation",
                "customer_address": "Shop No. 5, Sample Market, Bhiwandi, Maharashtra",
                "customer_gstin": "27ABCDE1234F1Z5", "note": "LABOUR CHARGES ONLY",
                "lines": [{"challan_no": c, "description": d, "hsn_code": h, "qty": q,
                           "rate": int(round(float(r) * 100))} for c, d, h, q, r in LINES]}
        inv, items = get_invoice(conn, create_invoice(conn, user, data))
        out = ROOT / "samples" / "sample_invoice.pdf"
        out.parent.mkdir(exist_ok=True)
        static = ROOT / "app" / "static"
        out.write_bytes(invoice_pdf(inv, items, get_settings(conn), static / "ganesh.png", static / "ganesh-watermark.png"))
        conn.close()
    print("Written", out)


if __name__ == "__main__":
    main()
