# Design: open questions, structure and database

## 1. Open questions (with the default used until you answer)

| # | Question | Default used |
|---|----------|--------------|
| 1 | What is the PIN code for the address? | Left blank on print. Add it in **Settings** and it prints as "… Maharashtra - 401xxx". |
| 2 | The pad shows invoice no. **198** but the August 2026 ledger shows **133 to 150**. Which is correct for the next bill? Are they two separate series? | Next number is 198, but **nothing can be saved until the owner confirms the number** on the *Starting invoice number* screen. It can be changed freely until the first invoice is saved. |
| 3 | In the ledger, what do the three amount columns mean? | Treated as **taxable value, CGST, SGST** (tax added on top of the taxable value). The import checks that Total = Taxable + CGST + SGST and refuses the file if not. |
| 4 | Is CGST/SGST 2.5% + 2.5% on every bill? Is any party outside Maharashtra (which would need IGST)? | 2.5% + 2.5% on all invoices, changeable in Settings. **IGST is not supported yet.** |
| 5 | Print on blank A4 paper with the full design, or on the pre-printed pad (data only, lined up with the boxes)? | Prints the **whole pad design on plain A4**, plus a PDF. A "data only" mode for pre-printed pads can be added if needed. |
| 6 | One number series forever, or restart every April? | **One continuous series** across financial years. |
| 7 | Which HSN/SAC code should labour (job-work) bills carry? | Left blank. The owner can set a default in Settings (for example SAC 998821 if the CA agrees). It fills in on new rows and can still be changed per row. |
| 8 | Can a saved invoice ever be edited? | **No.** This follows GST practice: the owner cancels it (the number stays used) and makes a new one. "Copy to new invoice" saves retyping. Every edit attempt is logged. |
| 9 | If an invoice is back-dated, can it get a higher number than a bill with a later date? | Allowed within the current financial year (1 April to today). The monthly report's quick check names any number that is dated in another month. |
| 10 | Logo file? | A circle with the text "LOGO" until an image is uploaded in Settings. |
| 11 | Where will it be hosted? | PythonAnywhere is recommended (see README): cheap, keeps the database file safe, HTTPS included. |

## 2. Project structure

```
run.py                  start the app (python run.py)
seed.py                 first-time setup: owner and worker logins, customer list
wsgi.py                 entry point for hosting services
requirements.txt
app/
  __init__.py           app setup: sessions, CSRF protection, HTTPS, automatic backup
  config.py             settings read from environment variables
  schema.sql            database tables and safety triggers
  db.py                 database connection, transactions, default business details
  money.py              rupees/paise, GST maths, Indian digit grouping (1,23,456.00)
  words.py              amount in words (lakh, crore)
  invoices.py           validation, numbering, save, cancel, search
  auth.py               login, lockout, owner/worker roles
  pdf.py                A4 invoice PDF
  reports.py            monthly CA report, Excel and PDF
  importer.py           CSV import of past ledger bills
  backup.py             daily backup, keeps 30 days
  views.py              all screens
  templates/            HTML pages (_sheet.html = the printed invoice)
  static/               style.css, invoice_form.js
tests/                  automated tests (pytest)
scripts/make_sample_pdf.py
samples/sample_invoice.pdf
```

## 3. Database (SQLite, one file)

All money is stored as whole **paise** (integers), so stored amounts never pick up rounding errors.

- **settings** (key, value): business name, tagline, address, PIN, mobile, GSTIN, declaration, footer texts, CGST and SGST rates, default note, default HSN, logo file.
- **invoice_sequence** (one row): `next_number`, `confirmed`, who confirmed and when.
- **users**: username (unique, any case), password hash (scrypt), role (`owner`/`worker`), active, failed login count, locked-until.
- **customers**: name (unique, any case), address, GSTIN, phone, active.
- **invoices**: source (`live`/`imported`), number (unique per source), date, customer id **plus a copy of the name, address and GSTIN as printed**, note, total quantity, net total, CGST/SGST rates and amounts, grand total, status (`active`/`cancelled`), cancellation details, created by/at.
- **invoice_items**: invoice id, Sr. No., challan no., description, HSN, quantity, rate, amount.
- **audit_log**: time, user, action, invoice id, details.

Safety rules inside the database itself (triggers):
- Invoices, invoice lines and audit entries cannot be deleted.
- A saved invoice cannot be changed, except to move it from active to cancelled.
- A cancelled invoice cannot be changed at all.

### How numbering works
Saving runs in one `BEGIN IMMEDIATE` transaction: lock the database → read `next_number` → insert the invoice and its lines → add 1 to `next_number` → commit. If anything fails, everything is rolled back and the number is not used. If two people press Save at the same moment, the saves run one after the other, so numbers are never repeated or skipped. A hidden one-time token on the confirm screen stops a double-click from saving the same bill twice.
