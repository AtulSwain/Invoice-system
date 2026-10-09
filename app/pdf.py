"""A4 invoice PDF drawn to match the printed Vinayak Creation pad."""
import io
from pathlib import Path

from .money import inr
from .words import amount_in_words

PAD_ROWS = 15


def register_fonts():
    """Built-in PDF fonts: always available, on every host, no files to ship."""
    return {"sans": "Helvetica", "sans_bold": "Helvetica-Bold", "serif_bi": "Times-BoldItalic",
            "serif_b": "Times-Bold"}


def dmy(iso: str) -> str:
    y, m, d = iso.split("-")
    return f"{d}/{m}/{y}"


def full_address(settings) -> str:
    addr = settings["address"].strip()
    if settings.get("pin_code", "").strip():
        addr += " - " + settings["pin_code"].strip()
    return addr


def printable_lines(inv, items):
    """Rows for the printed table (strings). Imported bills have no line items, so
    they print one summary row from the ledger figures."""
    if inv["source"] == "imported":
        return [{"sr_no": "1", "challan_no": inv["challan_no"], "description": "As per ledger (imported bill)",
                 "hsn_code": "", "qty": str(inv["total_qty"] or ""), "rate": "",
                 "amount": inr(inv["net_total"], symbol=False)}]
    return [{"sr_no": str(it["sr_no"]), "challan_no": it["challan_no"], "description": it["description"],
             "hsn_code": it["hsn_code"], "qty": str(it["qty"]), "rate": inr(it["rate"], symbol=False),
             "amount": inr(it["amount"], symbol=False)} for it in items]


def rate_label(rate: str) -> str:
    return f"{rate}%"


def invoice_pdf(inv, items, settings, logo_path=None) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib.utils import simpleSplit
    from reportlab.pdfgen import canvas

    f = register_fonts()
    W, H = A4
    M = 10 * mm
    X0, X1 = M, W - M
    CW = X1 - X0
    out = io.BytesIO()
    c = canvas.Canvas(out, pagesize=A4)
    c.setTitle(f"Invoice {inv['number']} - {inv['customer_name']}")
    c.setAuthor(settings["company_name"])
    c.setLineWidth(0.8)
    y = H - M  # current top edge, moving down

    def text(x, yy, s, font, size, align="left", color=colors.black):
        c.setFont(font, size)
        c.setFillColor(color)
        if align == "center":
            c.drawCentredString(x, yy, s)
        elif align == "right":
            c.drawRightString(x, yy, s)
        else:
            c.drawString(x, yy, s)
        c.setFillColor(colors.black)

    def fit(s, font, size, width):
        """Shrink font size until text fits the width."""
        while size > 5 and c.stringWidth(s, font, size) > width:
            size -= 0.5
        return size

    # 1. TAX INVOICE bar
    bar_h = 8 * mm
    c.setFillColor(colors.black)
    c.rect(X0, y - bar_h, CW, bar_h, stroke=1, fill=1)
    text(X0 + CW / 2, y - bar_h + 2.4 * mm, "TAX INVOICE", f["sans_bold"], 12, "center", colors.white)
    y -= bar_h

    # 2. Header box: logo + company
    head_h = 36 * mm
    c.rect(X0, y - head_h, CW, head_h)
    r = 14 * mm
    cx, cy = X0 + 5 * mm + r, y - head_h / 2
    if logo_path and Path(logo_path).exists():
        p = c.beginPath()
        p.circle(cx, cy, r)
        c.saveState()
        c.clipPath(p, stroke=0, fill=0)
        c.drawImage(str(logo_path), cx - r, cy - r, 2 * r, 2 * r, preserveAspectRatio=True, anchor="c", mask="auto")
        c.restoreState()
        c.circle(cx, cy, r)
    else:
        c.circle(cx, cy, r)
        text(cx, cy - 2 * mm, "LOGO", f["sans_bold"], 11, "center", colors.grey)
    tx = X0 + 2 * r + 10 * mm
    tw = X1 - tx - 4 * mm
    mid = tx + tw / 2
    name_size = fit(settings["company_name"], f["serif_bi"], 34, tw)
    text(mid, y - 14 * mm, settings["company_name"], f["serif_bi"], name_size, "center")
    text(mid, y - 20.5 * mm, settings["tagline"], f["sans_bold"], 11, "center")
    addr = full_address(settings)
    text(mid, y - 26.5 * mm, addr, f["sans"], fit(addr, f["sans"], 9.5, tw), "center")
    text(mid, y - 32 * mm, f"Mob.: {settings['mobile']}", f["sans_bold"], 10, "center")
    y -= head_h

    # 3. GSTIN row
    g_h = 7 * mm
    c.rect(X0, y - g_h, CW, g_h)
    text(X0 + 3 * mm, y - g_h + 2.2 * mm, f"GSTIN : {settings['gstin']}", f["sans_bold"], 11)
    y -= g_h

    # 4. Party (left) and invoice no./date (right)
    p_h = 28 * mm
    right_w = 62 * mm
    split_x = X1 - right_w
    c.rect(X0, y - p_h, CW, p_h)
    c.line(split_x, y, split_x, y - p_h)
    c.line(split_x, y - p_h / 2, X1, y - p_h / 2)
    lw = split_x - X0 - 22 * mm
    text(X0 + 3 * mm, y - 6 * mm, "M/s.", f["sans_bold"], 10)
    text(X0 + 18 * mm, y - 6 * mm, inv["customer_name"], f["sans_bold"],
         fit(inv["customer_name"], f["sans_bold"], 12, lw), "left")
    text(X0 + 3 * mm, y - 12 * mm, "Add.", f["sans_bold"], 10)
    addr_lines = simpleSplit(" ".join(inv["customer_address"].split()), f["sans"], 9.5, lw)[:3]
    for i, line in enumerate(addr_lines):
        text(X0 + 18 * mm, y - 12 * mm - i * 4.2 * mm, line, f["sans"], 9.5)
    text(X0 + 3 * mm, y - p_h + 2.5 * mm, "Party's GSTIN :", f["sans_bold"], 10)
    text(X0 + 31 * mm, y - p_h + 2.5 * mm, inv["customer_gstin"], f["sans_bold"], 10.5)
    text(split_x + 3 * mm, y - 9 * mm, "Invoice No.", f["sans_bold"], 10)
    text(X1 - 4 * mm, y - 9.5 * mm, str(inv["number"]), f["sans_bold"], 16, "right", colors.HexColor("#B00000"))
    text(split_x + 3 * mm, y - p_h / 2 - 9 * mm, "Date", f["sans_bold"], 10)
    text(X1 - 4 * mm, y - p_h / 2 - 9 * mm, dmy(inv["invoice_date"]), f["sans_bold"], 12, "right")
    y -= p_h

    # 5. Item table
    cols = [("Sr.\nNo.", 12), ("Challan\nNo.", 22), ("Description", 68), ("HSN\nCode", 20),
            ("Qnty\nPcs.", 20), ("Rate", 20), ("Amount", 28)]
    xs = [X0]
    for _, w in cols:
        xs.append(xs[-1] + w * mm)
    xs[-1] = X1
    hdr_h, row_h = 10 * mm, 7.5 * mm
    table_h = hdr_h + PAD_ROWS * row_h
    c.rect(X0, y - table_h, CW, table_h)
    c.line(X0, y - hdr_h, X1, y - hdr_h)
    for x in xs[1:-1]:
        c.line(x, y, x, y - table_h)
    for i, (label, _) in enumerate(cols):
        parts = label.split("\n")
        mx = (xs[i] + xs[i + 1]) / 2
        for j, part in enumerate(parts):
            off = (len(parts) - 1) * 1.8 * mm
            text(mx, y - hdr_h / 2 - 1.3 * mm + off - j * 3.6 * mm, part, f["sans_bold"], 9, "center")
    c.setStrokeColor(colors.HexColor("#BBBBBB"))
    c.setLineWidth(0.3)
    for i in range(1, PAD_ROWS):
        yy = y - hdr_h - i * row_h
        c.line(X0, yy, X1, yy)
    c.setStrokeColor(colors.black)
    c.setLineWidth(0.8)
    pad = 1.5 * mm
    for i, line in enumerate(printable_lines(inv, items)[:PAD_ROWS]):
        base = y - hdr_h - (i + 1) * row_h + 2.4 * mm
        vals = [line["sr_no"], line["challan_no"], line["description"], line["hsn_code"], line["qty"],
                line["rate"], line["amount"]]
        for k, v in enumerate(vals):
            if not v:
                continue
            width = xs[k + 1] - xs[k] - 2 * pad
            size = fit(v, f["sans"], 9.5, width)
            if k in (0, 3):
                text((xs[k] + xs[k + 1]) / 2, base, v, f["sans"], size, "center")
            elif k >= 4:
                text(xs[k + 1] - pad, base, v, f["sans"], size, "right")
            else:
                text(xs[k] + pad, base, v, f["sans"], size)
    y -= table_h

    # 6. Totals (right) + note and words (left)
    t_rows = [("Net Total", inv["net_total"]), (f"CGST {rate_label(inv['cgst_rate'])}", inv["cgst"]),
              (f"SGST {rate_label(inv['sgst_rate'])}", inv["sgst"]), ("Grand Total", inv["grand_total"])]
    tr_h = 7.5 * mm
    tot_x = xs[4]
    tot_h = tr_h * len(t_rows)
    c.rect(X0, y - tot_h, CW, tot_h)
    c.line(tot_x, y, tot_x, y - tot_h)
    c.line(xs[6], y, xs[6], y - tot_h)
    for i, (label, amount) in enumerate(t_rows):
        yy = y - (i + 1) * tr_h
        if i < len(t_rows) - 1:
            c.line(tot_x, yy, X1, yy)
        bold = f["sans_bold"] if i == len(t_rows) - 1 else f["sans"]
        text(tot_x + 2 * mm, yy + 2.4 * mm, label, f["sans_bold"], 9.5)
        text(X1 - pad, yy + 2.4 * mm, inr(amount, symbol=False), bold, 10.5 if bold == f["sans_bold"] else 9.5,
             "right")
    left_w = tot_x - X0 - 6 * mm
    note = inv["note"] or ""
    if note:
        text(X0 + 3 * mm, y - 6 * mm, note, f["sans_bold"], fit(note, f["sans_bold"], 11, left_w))
    text(X0 + 3 * mm, y - 13 * mm, "Rupees in Words :", f["sans_bold"], 9)
    words = amount_in_words(inv["grand_total"])
    for i, line in enumerate(simpleSplit(words, f["sans"], 9, left_w)[:3]):
        text(X0 + 3 * mm, y - 17.5 * mm - i * 4 * mm, line, f["sans"], 9)
    y -= tot_h

    # 7. Declaration + signature
    dec_h = 34 * mm
    c.rect(X0, y - dec_h, CW, dec_h)
    sig_x = X1 - 70 * mm
    c.line(sig_x, y, sig_x, y - dec_h)
    dec_lines = simpleSplit(settings["declaration"], f["sans"], 7.5, sig_x - X0 - 6 * mm)
    for i, line in enumerate(dec_lines[:7]):
        text(X0 + 3 * mm, y - 5 * mm - i * 3.4 * mm, line, f["sans"], 7.5)
    text(X0 + 3 * mm, y - dec_h + 3 * mm, settings["footer_left"], f["sans_bold"], 10)
    sig_mid = (sig_x + X1) / 2
    text(sig_mid, y - 6 * mm, f"For {settings['company_name']}", f["serif_b"], 12, "center")
    c.setLineWidth(0.5)
    c.line(sig_x + 8 * mm, y - dec_h + 9 * mm, X1 - 8 * mm, y - dec_h + 9 * mm)
    text(sig_mid, y - dec_h + 4 * mm, settings["signatory_title"], f["sans_bold"], 10, "center")

    # Cancelled stamp
    if inv["status"] == "cancelled":
        c.saveState()
        c.translate(W / 2, H / 2)
        c.rotate(35)
        c.setFillColor(colors.HexColor("#C00000"))
        c.setStrokeColor(colors.HexColor("#C00000"))
        c.setFillAlpha(0.35)
        c.setStrokeAlpha(0.6)
        c.setLineWidth(4)
        c.roundRect(-95 * mm, -16 * mm, 190 * mm, 32 * mm, 6 * mm, stroke=1, fill=0)
        c.setFont(f["sans_bold"], 64)
        c.drawCentredString(0, -8 * mm, "CANCELLED")
        c.restoreState()

    c.showPage()
    c.save()
    return out.getvalue()
