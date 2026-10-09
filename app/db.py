"""SQLite connection handling, schema setup and small time helpers."""
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
FIRST_INVOICE_NUMBER = 198

DEFAULT_SETTINGS = {
    "company_name": "VINAYAK CREATION",
    "tagline": "TROUSERS SPECIALIST",
    "address": "Room No. 202, JRT Estate 2, Golani Naka, Vasai-Virar, Maharashtra",
    "pin_code": "",
    "mobile": "9819442322",
    "gstin": "27CDXPS0112F2ZE",
    "declaration": (
        "I/We hereby certify that my/our registration certificate under the GST 2017 is in force "
        "on the date on which the sale of the goods specified in this bill is made by me/us and that "
        "the transaction of sales covered by this bill has been specified by me/us in the regular "
        "course of my our business, SUBJECT TO MUMBAI JURISDICTION."
    ),
    "footer_left": "E. & O. E.",
    "signatory_title": "Proprietor",
    "cgst_rate": "2.5",
    "sgst_rate": "2.5",
    "default_note": "LABOUR CHARGES ONLY",
    "default_hsn": "",
    "logo_file": "",
    "invoice_watermark": "1",   # faint Ganpati artwork behind the item table
}

SEED_CUSTOMERS = ["Jainam Creation", "JSON Lifestyle LLP", "Swastik Enterprises", "Hareesh Enterprises"]


def now_ist() -> datetime:
    return datetime.now(IST)


def today_ist() -> date:
    return now_ist().date()


def now_str() -> str:
    return now_ist().strftime("%Y-%m-%d %H:%M:%S")


def connect(path) -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    # isolation_level=None: we issue BEGIN IMMEDIATE ourselves for every write.
    conn = sqlite3.connect(str(path), timeout=30, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection):
    """Write transaction. BEGIN IMMEDIATE takes the database write lock up front,
    so two simultaneous saves are processed strictly one after the other."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


def init_db(conn: sqlite3.Connection, seed_customers: bool = True) -> None:
    schema = (Path(__file__).parent / "schema.sql").read_text(encoding="utf-8")
    conn.executescript(schema)
    with transaction(conn):
        for key, value in DEFAULT_SETTINGS.items():
            conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (key, value))
        conn.execute(
            "INSERT OR IGNORE INTO invoice_sequence (id, next_number, confirmed) VALUES (1, ?, 0)",
            (FIRST_INVOICE_NUMBER,),
        )
        if seed_customers:
            for name in SEED_CUSTOMERS:
                conn.execute(
                    "INSERT OR IGNORE INTO customers (name, created_at) VALUES (?, ?)", (name, now_str())
                )


def get_settings(conn) -> dict:
    values = dict(DEFAULT_SETTINGS)
    values.update({r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM settings")})
    return values


def audit(conn, user, action, invoice_id=None, details=""):
    """Append to the audit log. `user` is a users row/dict or None."""
    conn.execute(
        "INSERT INTO audit_log (ts, user_id, username, action, invoice_id, details) VALUES (?,?,?,?,?,?)",
        (now_str(), user["id"] if user else None, user["username"] if user else None, action, invoice_id, details),
    )
