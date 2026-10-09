import threading

import pytest

from app.db import connect
from app.invoices import (InvoiceError, NumberingNotConfirmed, confirm_sequence, create_invoice,
                          get_sequence)
from tests.conftest import invoice_data


def numbers(conn):
    return [r[0] for r in conn.execute("SELECT number FROM invoices WHERE source='live' ORDER BY number")]


def test_cannot_save_before_owner_confirms(conn, owner):
    assert get_sequence(conn)["next_number"] == 198
    with pytest.raises(NumberingNotConfirmed):
        create_invoice(conn, owner, invoice_data())
    assert numbers(conn) == []
    assert get_sequence(conn)["next_number"] == 198


def test_starts_at_198_and_increments(conn, owner, confirmed):
    for _ in range(3):
        create_invoice(conn, owner, invoice_data())
    assert numbers(conn) == [198, 199, 200]
    assert get_sequence(conn)["next_number"] == 201


def test_failed_save_does_not_use_a_number(conn, owner, confirmed):
    create_invoice(conn, owner, invoice_data())
    bad = invoice_data()
    bad["lines"][0]["qty"] = 0  # violates the CHECK constraint inside the transaction
    with pytest.raises(Exception):
        create_invoice(conn, owner, bad)
    create_invoice(conn, owner, invoice_data())
    assert numbers(conn) == [198, 199]


def test_double_submit_saves_once(conn, owner, confirmed):
    a = create_invoice(conn, owner, invoice_data(), client_token="abc")
    b = create_invoice(conn, owner, invoice_data(), client_token="abc")
    assert a == b
    assert numbers(conn) == [198]


def test_number_locked_after_first_invoice(conn, owner, confirmed):
    create_invoice(conn, owner, invoice_data())
    with pytest.raises(InvoiceError):
        confirm_sequence(conn, owner, 500)
    confirm_sequence(conn, owner, 199)  # re-confirming the same number is harmless


def test_owner_may_change_start_before_first_invoice(conn, owner):
    confirm_sequence(conn, owner, 151)
    create_invoice(conn, owner, invoice_data())
    assert numbers(conn) == [151]


def test_concurrent_saves_get_unique_consecutive_numbers(app, owner, confirmed):
    n_threads, per_thread = 8, 5
    errors = []
    barrier = threading.Barrier(n_threads)

    def worker():
        c = connect(app.config["DATABASE_PATH"])
        try:
            barrier.wait()
            for _ in range(per_thread):
                create_invoice(c, owner, invoice_data())
        except Exception as e:  # pragma: no cover - reported below
            errors.append(e)
        finally:
            c.close()

    threads = [threading.Thread(target=worker) for _ in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    c = connect(app.config["DATABASE_PATH"])
    got = numbers(c)
    total = n_threads * per_thread
    assert got == list(range(198, 198 + total))  # no gaps, no duplicates
    assert get_sequence(c)["next_number"] == 198 + total
    c.close()


def test_invoice_rows_cannot_be_deleted(conn, owner, confirmed):
    inv_id = create_invoice(conn, owner, invoice_data())
    with pytest.raises(Exception, match="cannot be deleted"):
        conn.execute("DELETE FROM invoices WHERE id = ?", (inv_id,))
