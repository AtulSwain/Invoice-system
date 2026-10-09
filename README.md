# Vinayak Creation – Invoicing and Monthly Reports

A simple web app for making GST tax invoices (laid out like the paper pad) and downloading a monthly report for the CA.
It works in any browser on a phone or a laptop.

- **Worker**: makes invoices, views, prints or downloads them as PDF, and adds customers.
- **Owner**: everything above, plus cancelling invoices, the monthly report, settings, customer edits and user accounts.

Open questions, the project layout and the database design are in [docs/DESIGN.md](docs/DESIGN.md).
A sample printed invoice made from test data is in [samples/sample_invoice.pdf](samples/sample_invoice.pdf).

## Why Python + Flask + SQLite
- **SQLite** keeps all data in one file. There is no database server to install or pay for, and backing up means copying that file.
- **Flask** is a small, well-known Python web framework, and Python runs on Windows, Mac, Linux and cheap hosts such as PythonAnywhere.
- Only five packages are needed: Flask, openpyxl (Excel), reportlab (PDF), waitress (web server) and tzdata (Indian time zone on Windows). PDFs are made in pure Python, so no extra system software is required.

---

## 1. Run it on your own computer

You need Python 3.10 or newer (from python.org; on Windows, tick "Add Python to PATH").

```bash
# one time
python -m venv .venv
# Windows:  .venv\Scripts\activate      Mac/Linux:  source .venv/bin/activate
pip install -r requirements.txt
python seed.py          # asks for the owner and worker usernames and passwords

# every day
python run.py
```

Open **http://localhost:8000** and log in as the owner.

**First thing to do:** the home screen asks you to **confirm the starting invoice number** (set to 198).
Check it against the last number used on the paper pad and in the ledger. Nobody can save an invoice until you confirm it,
and the number can no longer be changed once the first invoice is saved.

To use it from phones on the same Wi-Fi, start it with `HOST=0.0.0.0 python run.py`
(on Windows: `set HOST=0.0.0.0` then `python run.py`), then open `http://<computer's IP address>:8000` on the phone.
For use outside the shop, put it online (section 2).

### Settings (environment variables)
| Variable | Meaning | Default |
|---|---|---|
| `SECRET_KEY` | Long random text used to sign logins. **Required online.** | Made automatically in `data/secret_key.txt` |
| `DATA_DIR` | Folder for the database and logo | `./data` |
| `DATABASE_PATH` | Database file | `DATA_DIR/invoices.db` |
| `BACKUP_DIR` | Folder for daily backups | `./backups` |
| `APP_ENV` | Set to `production` online: forces HTTPS and secure cookies | `development` |
| `PORT`, `HOST` | Where `run.py` listens | `8000`, `127.0.0.1` |

Make a secret key with: `python -c "import secrets; print(secrets.token_hex(32))"`

## 2. Put it online

The app needs a host that **keeps files between restarts**, because the database is a file.

### Recommended: PythonAnywhere (free tier to start, then about $5/month; HTTPS included)
1. Create an account at pythonanywhere.com and open a **Bash console**.
2. `git clone <this repository URL> invoice-system && cd invoice-system`
3. `python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt`
4. `python seed.py` (type the owner and worker passwords).
5. **Web** tab → *Add a new web app* → *Manual configuration* → choose the same Python version.
   - Virtualenv: `/home/<you>/invoice-system/.venv`
   - Edit the WSGI file so it contains only:
     ```python
     import os, sys
     sys.path.insert(0, "/home/<you>/invoice-system")
     os.environ["APP_ENV"] = "production"
     os.environ["SECRET_KEY"] = "<paste your long random key>"
     from wsgi import application
     ```
     (Only you can see this file on your account. It is not stored in the code.)
   - Turn on **Force HTTPS**, then press **Reload**.
6. Optional extra backup: **Tasks** tab → daily task:
   `/home/<you>/invoice-system/.venv/bin/python -m app.backup` (run from the project folder).

### Railway or Render
Both work if you **attach a persistent volume/disk** (paid add-on; their free disks are wiped on every restart).
- Start command: `waitress-serve --port=$PORT wsgi:app`
- Environment: `APP_ENV=production`, `SECRET_KEY=…`, `DATA_DIR=/data`, `BACKUP_DIR=/data/backups` (with the volume mounted at `/data`).
- These hosts have no console for typing passwords, so for **one** deploy also set `OWNER_USERNAME`, `OWNER_PASSWORD`,
  `WORKER_USERNAME`, `WORKER_PASSWORD`, use the start command `python seed.py && waitress-serve --port=$PORT wsgi:app`,
  then delete those four variables and change the start command back.

## 3. Backup and restore
- **Automatic:** while the app is used, it makes one copy a day in `BACKUP_DIR`, named `invoices-YYYY-MM-DD.db`,
  and deletes copies older than 30 days. You can also run `python -m app.backup` at any time.
- **Keep an outside copy:** once a week, download the newest backup file to Google Drive or a pen drive.
  The backup folder is on the same machine, so it does not protect against losing that machine.
- **Restore:**
  1. Stop the app (on PythonAnywhere, press *Disable* on the Web tab).
  2. Copy the chosen backup over the database, for example
     `cp backups/invoices-2026-10-08.db data/invoices.db`, and delete any `data/invoices.db-wal` and `data/invoices.db-shm` files.
  3. Start the app again.
  Anything entered after that backup was made will be missing, so re-enter it from the paper copies.

## 4. Logo and PIN code
Log in as the owner → **Settings**.
- **Logo:** under *Logo*, choose a square PNG or JPG and press *Upload logo*. It appears in the circle on screen, in print and in PDFs.
- **PIN code:** type the 6 digits in *PIN code* and press *Save settings*. It prints after the address.

All business details (name, address, mobile, GSTIN, declaration, footer) can be changed in the same place.

## 5. Changing CGST / SGST rates
Settings → *Tax rates* → change **CGST %** and **SGST %** → *Save settings*.
The new rates apply to invoices saved **from then on**. Old invoices keep the rate they were saved with.
Every change is recorded in the audit log (Settings → Audit log).

## 6. Day-to-day use
- **New invoice:** pick or type the customer (a new name is saved for next time), check the date, and fill in the items
  (up to 15; on a phone each item is a card). Then press *Check & Save Invoice*, check the totals and press **Save Invoice**.
  The number is given only at that moment.
- **Print:** on the invoice press *Print*. It prints one clean A4 page.
  If Chrome still shows a date or web address at the edges, choose *More settings → Margins: None* and untick *Headers and footers*.
  **Download PDF** gives the same layout as a file to send on WhatsApp or email.
- **Mistake on a saved invoice:** the owner opens it → *Cancel invoice* (a reason is required).
  The number stays used and is stamped CANCELLED. Then use *Copy to new invoice*.
- **Monthly report:** Monthly Report → choose the month → *Download Excel* (sheets "Invoices" and "Summary by Customer")
  or *Download PDF* (one page). The quick-check line warns if any invoice number is missing from the month.
- **Past ledger bills:** Monthly Report → *Import past bills* → download the template, fill it in, upload it, check the preview,
  tick both confirmations, import. Imported bills are marked "Imported", appear in reports and never change the invoice numbering.
  **The August 2026 ledger has not been imported.** It is waiting for answers to open questions 2 and 3.

## 7. Tests
```bash
pip install -r requirements.txt
python -m pytest
```
The 58 tests cover:
- **Numbering:** starts at 198, no gaps, no repeats, including 40 saves running at the same time.
- **Tax:** 2.5% each, half-up rounding, and the grand total always equals the sum of the rounded figures.
- **Amount in words:** 0, 1, 100, 1,000, 1,00,000, 1,00,00,000, paise and very large amounts.
- **Cancellation:** the number is kept, the invoice is left out of report totals, and it cannot be edited.
- **Roles:** workers are blocked from reports, settings and cancelling.
- **Reports:** report totals equal the sum of the invoices; the Excel and one-page PDF exports work.
- **Other:** import, backup rotation, lockout, the 8-hour session timeout and protection against forged form submissions.

To rebuild the sample PDF: `python scripts/make_sample_pdf.py`

## 8. Defaults chosen
- Invoice numbers start at **198**, form **one continuous series**, and need owner confirmation before the first invoice.
- CGST 2.5% + SGST 2.5% on every invoice. Tax is rounded half-up to the paisa on the Net Total, and Grand Total = Net + CGST + SGST.
- Amounts in words use the Indian system and title case, singular "Lakh"/"Crore", for example "Rupees One Lakh Twenty Thousand and Paise Five Only".
- Invoice date: today by default; may be back-dated within the current financial year (1 April – 31 March), never in the future.
- Saved invoices are never edited or deleted, only cancelled. The customer's name, address and GSTIN are stored on each invoice as printed,
  so later customer edits do not change old bills.
- Quantity is a whole number above 0. Rate is above 0 with up to 2 decimals. Each item needs a description; Challan No. and HSN are optional.
- Party GSTIN, if typed, must be a valid 15-character GSTIN.
- Passwords: at least 8 characters, stored with scrypt (a slow, salted hash like bcrypt). After 5 wrong attempts the account is locked for 15 minutes.
  A session ends after 8 hours without use.
- Seed customers: Jainam Creation, JSON Lifestyle LLP, Swastik Enterprises, Hareesh Enterprises (address and GSTIN blank for you to fill in).
  When a worker fills a blank address or GSTIN on an invoice, it is saved to that customer.
- Dates are shown dd/mm/yyyy, amounts with lakh grouping (₹1,23,456.00), and the time zone is Asia/Kolkata.
  The date picker itself follows the phone's or browser's language setting.
- PDFs use standard built-in fonts. Names in Devanagari or other non-English scripts will not print in the PDF; use English names.

## 9. Open questions
See the full list in [docs/DESIGN.md](docs/DESIGN.md#1-open-questions-with-the-default-used-until-you-answer). The most important:
1. Which invoice number comes next: **198** (pad) or after **150** (ledger)? Confirm it on the numbering screen before the first live bill.
2. What do the three amount columns in the August ledger mean? Until this is answered, **do not import it**.
3. What is the PIN code?
4. Which HSN/SAC code should appear on labour bills?
5. Will you print on plain A4 (current setting) or on the pre-printed pads?
6. Are there any customers outside Maharashtra who would need IGST?
