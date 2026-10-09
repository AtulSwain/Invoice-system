import pytest

from app import create_app
from app.auth import create_user
from app.db import connect, init_db, today_ist


@pytest.fixture
def app(tmp_path):
    app = create_app({
        "DATA_DIR": tmp_path,
        "DATABASE_PATH": tmp_path / "test.db",
        "BACKUP_DIR": tmp_path / "backups",
        "SECRET_KEY": "test-secret",
        "AUTO_BACKUP": False,
        "TESTING": True,
    })
    conn = connect(app.config["DATABASE_PATH"])
    init_db(conn, seed_customers=True)
    create_user(conn, "owner", "owner-pass-1", "owner")
    create_user(conn, "worker", "worker-pass-1", "worker")
    conn.close()
    return app


@pytest.fixture
def conn(app):
    c = connect(app.config["DATABASE_PATH"])
    yield c
    c.close()


@pytest.fixture
def owner(conn):
    return conn.execute("SELECT * FROM users WHERE username = 'owner'").fetchone()


@pytest.fixture
def confirmed(conn, owner):
    from app.invoices import confirm_sequence
    confirm_sequence(conn, owner, 198)


class Client:
    """Test client that logs in and adds the CSRF token to every POST."""

    def __init__(self, app):
        self.c = app.test_client()

    def login(self, username, password):
        self.c.get("/login")
        return self.post("/login", {"username": username, "password": password})

    def token(self):
        with self.c.session_transaction() as s:
            if "csrf" not in s:
                s["csrf"] = "tok"
            return s["csrf"]

    def get(self, url, **kw):
        return self.c.get(url, **kw)

    def post(self, url, data=None, **kw):
        data = dict(data or {})
        data["csrf_token"] = self.token()
        return self.c.post(url, data=data, **kw)


@pytest.fixture
def owner_client(app):
    c = Client(app)
    c.login("owner", "owner-pass-1")
    return c


@pytest.fixture
def worker_client(app):
    c = Client(app)
    c.login("worker", "worker-pass-1")
    return c


def invoice_data(name="Jainam Creation", lines=((10, "125.50"),), inv_date=None):
    return {
        "invoice_date": (inv_date or today_ist()).isoformat(),
        "customer_name": name, "customer_address": "", "customer_gstin": "", "note": "LABOUR CHARGES ONLY",
        "lines": [{"challan_no": str(i + 1), "description": "Trouser stitching", "hsn_code": "",
                   "qty": q, "rate": int(round(float(r) * 100)), "qty_text": str(q), "rate_text": r}
                  for i, (q, r) in enumerate(lines)],
    }


def form_data(name="Jainam Creation", lines=((10, "125.50"),), inv_date=None):
    from werkzeug.datastructures import MultiDict
    md = MultiDict({"invoice_date": (inv_date or today_ist()).isoformat(), "customer_name": name,
                    "customer_address": "", "customer_gstin": "", "note": "LABOUR CHARGES ONLY"})
    for i, (q, r) in enumerate(lines):
        md.add("challan_no", str(i + 1))
        md.add("description", "Trouser stitching")
        md.add("hsn_code", "")
        md.add("qty", str(q))
        md.add("rate", r)
    return md
