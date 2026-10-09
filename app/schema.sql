-- Vinayak Creation invoicing database.
-- All money is stored as whole paise (INTEGER) so there is never any floating-point rounding.

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL DEFAULT ''
);

-- Exactly one row (id = 1). next_number is only advanced inside the same
-- transaction that inserts the invoice, so numbers can never be skipped.
CREATE TABLE IF NOT EXISTS invoice_sequence (
    id           INTEGER PRIMARY KEY CHECK (id = 1),
    next_number  INTEGER NOT NULL,
    confirmed    INTEGER NOT NULL DEFAULT 0,   -- owner must confirm before the first live invoice
    confirmed_by TEXT,
    confirmed_at TEXT
);

CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY,
    username      TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL CHECK (role IN ('owner', 'worker')),
    active        INTEGER NOT NULL DEFAULT 1,
    failed_logins INTEGER NOT NULL DEFAULT 0,
    locked_until  TEXT,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS customers (
    id         INTEGER PRIMARY KEY,
    name       TEXT NOT NULL UNIQUE COLLATE NOCASE,
    address    TEXT NOT NULL DEFAULT '',
    gstin      TEXT NOT NULL DEFAULT '',
    phone      TEXT NOT NULL DEFAULT '',
    active     INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS invoices (
    id               INTEGER PRIMARY KEY,
    source           TEXT NOT NULL DEFAULT 'live' CHECK (source IN ('live', 'imported')),
    number           INTEGER NOT NULL,
    invoice_date     TEXT NOT NULL,              -- ISO yyyy-mm-dd
    customer_id      INTEGER NOT NULL REFERENCES customers(id),
    -- Snapshot of the party as printed, so later customer edits never change old bills
    customer_name    TEXT NOT NULL,
    customer_address TEXT NOT NULL DEFAULT '',
    customer_gstin   TEXT NOT NULL DEFAULT '',
    note             TEXT NOT NULL DEFAULT '',
    challan_no       TEXT NOT NULL DEFAULT '',   -- used by imported bills (live bills keep it per line)
    total_qty        INTEGER NOT NULL DEFAULT 0,
    net_total        INTEGER NOT NULL,           -- paise
    cgst_rate        TEXT NOT NULL,              -- e.g. '2.5'
    sgst_rate        TEXT NOT NULL,
    cgst             INTEGER NOT NULL,           -- paise
    sgst             INTEGER NOT NULL,           -- paise
    grand_total      INTEGER NOT NULL,           -- paise
    status           TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'cancelled')),
    cancelled_at     TEXT,
    cancelled_by     TEXT,
    cancel_reason    TEXT,
    client_token     TEXT UNIQUE,                -- stops a double-click from saving twice
    created_by       TEXT NOT NULL,
    created_at       TEXT NOT NULL,
    UNIQUE (source, number)
);
CREATE INDEX IF NOT EXISTS idx_invoices_date ON invoices(invoice_date);
CREATE INDEX IF NOT EXISTS idx_invoices_customer ON invoices(customer_id);

CREATE TABLE IF NOT EXISTS invoice_items (
    id          INTEGER PRIMARY KEY,
    invoice_id  INTEGER NOT NULL REFERENCES invoices(id),
    sr_no       INTEGER NOT NULL,
    challan_no  TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    hsn_code    TEXT NOT NULL DEFAULT '',
    qty         INTEGER NOT NULL CHECK (qty > 0),
    rate        INTEGER NOT NULL CHECK (rate > 0),   -- paise
    amount      INTEGER NOT NULL                     -- paise
);
CREATE INDEX IF NOT EXISTS idx_items_invoice ON invoice_items(invoice_id);

CREATE TABLE IF NOT EXISTS audit_log (
    id         INTEGER PRIMARY KEY,
    ts         TEXT NOT NULL,           -- Asia/Kolkata local time, ISO format
    user_id    INTEGER,
    username   TEXT,
    action     TEXT NOT NULL,
    invoice_id INTEGER,
    details    TEXT NOT NULL DEFAULT ''
);

-- Invoices and audit entries are never deleted or rewritten.
CREATE TRIGGER IF NOT EXISTS no_invoice_delete BEFORE DELETE ON invoices
BEGIN SELECT RAISE(ABORT, 'Invoices cannot be deleted. Cancel instead.'); END;

CREATE TRIGGER IF NOT EXISTS no_item_delete BEFORE DELETE ON invoice_items
BEGIN SELECT RAISE(ABORT, 'Invoice lines cannot be deleted.'); END;

CREATE TRIGGER IF NOT EXISTS no_item_update BEFORE UPDATE ON invoice_items
BEGIN SELECT RAISE(ABORT, 'Invoice lines cannot be changed.'); END;

CREATE TRIGGER IF NOT EXISTS invoice_update_guard BEFORE UPDATE ON invoices
WHEN OLD.status = 'cancelled'
  OR NEW.number IS NOT OLD.number OR NEW.source IS NOT OLD.source
  OR NEW.invoice_date IS NOT OLD.invoice_date OR NEW.customer_name IS NOT OLD.customer_name
  OR NEW.customer_address IS NOT OLD.customer_address OR NEW.customer_gstin IS NOT OLD.customer_gstin
  OR NEW.net_total IS NOT OLD.net_total OR NEW.cgst IS NOT OLD.cgst OR NEW.sgst IS NOT OLD.sgst
  OR NEW.grand_total IS NOT OLD.grand_total OR NEW.total_qty IS NOT OLD.total_qty
  OR NEW.note IS NOT OLD.note
BEGIN SELECT RAISE(ABORT, 'Saved invoices cannot be changed. Only an active invoice can be cancelled.'); END;

CREATE TRIGGER IF NOT EXISTS no_audit_delete BEFORE DELETE ON audit_log
BEGIN SELECT RAISE(ABORT, 'Audit log is append-only.'); END;

CREATE TRIGGER IF NOT EXISTS no_audit_update BEFORE UPDATE ON audit_log
BEGIN SELECT RAISE(ABORT, 'Audit log is append-only.'); END;
