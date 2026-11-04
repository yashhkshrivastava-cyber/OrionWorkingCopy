"""PDF versions of a tax invoice and of a client's statement of unpaid bills.

The invoice follows the printed bill drawn by ``frontend/src/components/billing/BillDocument.tsx``:
same sections, same order, same fixed colours. The two are written separately, so a change to
what the bill shows has to be made in both. Figures are never calculated here; they come from
the stored bill, which ``billing.compute_bill`` already worked out.

Either can be drawn on the company letterhead (``letterhead_page.Letterhead``). The letterhead already
carries the company's name, address, contact and registration numbers, so the typed versions of those are
left off and the rest of the document is unchanged.
"""

from __future__ import annotations

import io
import logging
import re
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app import bill_fonts
from app.letterhead_page import Letterhead

logger = logging.getLogger(__name__)

NAVY = colors.HexColor("#0f2f57")
SLATE_500 = colors.HexColor("#64748b")
SLATE_600 = colors.HexColor("#475569")
SLATE_900 = colors.HexColor("#0f172a")
LINE = colors.HexColor("#e2e8f0")
PANEL = colors.HexColor("#f8fafc")
RED = colors.HexColor("#dc2626")

# On the letterhead a bill keeps this much clear of each strip, less than a letter does: a bill is a full page.
BILL_GAP_MM = 3.0

MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September",
          "October", "November", "December"]

_FONT_DIRS = (
    Path("C:/Windows/Fonts"),
    Path("/Library/Fonts"),
    Path("/System/Library/Fonts/Supplemental"),
    Path("/usr/share/fonts/truetype/dejavu"),
    Path("/usr/share/fonts/truetype/liberation"),
    Path("/usr/share/fonts/truetype/crosextra"),
    Path("/usr/share/fonts/truetype/noto"),
)
# Hindi (Devanagari) is drawn in one of these when it is installed; the bill's own typeface has no such letters.
_DEVANAGARI_FILES = ("mangal.ttf", "NotoSansDevanagari-Regular.ttf")
_DEVANAGARI = re.compile("[\u0900-\u097f\u200c\u200d]+")
_devanagari_font: list[str | None] = []
_fonts: dict[str, tuple[str, str, str] | None] = {}


def _load_family(key: str) -> tuple[str, str, str] | None:
    """Register a family's regular and bold faces with reportlab, if a pair that draws the rupee sign is installed."""
    for directory in _FONT_DIRS:
        for regular, bold in bill_fonts.FAMILIES[key]["files"]:
            if not (directory / regular).is_file() or not (directory / bold).is_file():
                continue
            try:
                face = TTFont(f"Orion-{key}", str(directory / regular))
                if 0x20B9 not in face.face.charToGlyph:
                    continue
                pdfmetrics.registerFont(face)
                pdfmetrics.registerFont(TTFont(f"Orion-{key}-Bold", str(directory / bold)))
                return f"Orion-{key}", f"Orion-{key}-Bold", "₹"
            except Exception:  # an unreadable font file is not worth failing a bill over
                logger.warning("Could not load font %s", directory / regular, exc_info=True)
    return None


def fonts(family: str = bill_fonts.DEFAULT_FAMILY) -> tuple[str, str, str]:
    """(regular, bold, rupee sign) for a family of ``bill_fonts.FAMILIES``. A TrueType face is used when one that draws the
    rupee sign is installed; a family that is not installed is drawn in Arial, and when no Arial-like face is installed
    either, the built-in Helvetica is used and the rupee is written as "Rs."."""
    if family not in bill_fonts.FAMILIES:
        family = bill_fonts.DEFAULT_FAMILY
    for key in dict.fromkeys((family, bill_fonts.DEFAULT_FAMILY)):
        if key not in _fonts:
            _fonts[key] = _load_family(key)
        if _fonts[key]:
            return _fonts[key]  # type: ignore[return-value]
    return "Helvetica", "Helvetica-Bold", "Rs."


def available_families() -> list[str]:
    """The families whose faces are installed on this computer, so the PDF can draw them."""
    out = []
    for key in bill_fonts.FAMILIES:
        if key not in _fonts:
            _fonts[key] = _load_family(key)
        if _fonts[key]:
            out.append(key)
    return out


# --------------------------------------------------------------------------- formatting


def indian(value: Any, decimals: int = 2) -> str:
    """9,19,149.00: groups of two after the first three digits, as bills are written in India."""
    number = Decimal(str(value or 0)).quantize(Decimal(1).scaleb(-decimals), rounding=ROUND_HALF_UP)
    sign = "-" if number < 0 else ""
    whole, _, fraction = f"{abs(number):f}".partition(".")
    head, tail = whole[:-3], whole[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    text = ",".join([*groups, tail]) if groups else tail
    return f"{sign}{text}.{fraction}" if decimals else f"{sign}{text}"


def day(value: Any) -> str:
    if not value:
        return ""
    parsed = value if isinstance(value, date) else datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    return f"{parsed.day:02d} {MONTHS[parsed.month - 1][:3]} {parsed.year}"


def month(value: Any) -> str:
    if not value:
        return ""
    parsed = value if isinstance(value, date) else datetime.strptime(str(value)[:7], "%Y-%m").date()
    return f"{MONTHS[parsed.month - 1]} {parsed.year}"


_ONES = ["Zero", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten", "Eleven", "Twelve",
         "Thirteen", "Fourteen", "Fifteen", "Sixteen", "Seventeen", "Eighteen", "Nineteen"]
_TENS = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]


def _under_hundred(n: int) -> str:
    if n < 20:
        return _ONES[n]
    return _TENS[n // 10] + (f" {_ONES[n % 10]}" if n % 10 else "")


def _under_thousand(n: int) -> str:
    hundreds, rest = divmod(n, 100)
    return " ".join(part for part in (f"{_ONES[hundreds]} Hundred" if hundreds else "", _under_hundred(rest) if rest else "") if part)


def rupees_in_words(amount: Any) -> str:
    """Whole rupees in lakh and crore. The same words as frontend/src/billing/rupeeWords.ts."""
    rupees = int(Decimal(str(amount or 0)).quantize(Decimal(1), rounding=ROUND_HALF_UP))
    if rupees == 0:
        return "Zero Rupees Only"
    if rupees == 1:
        return "One Rupee Only"
    parts: list[str] = []
    crore, rest = divmod(rupees, 10_000_000)
    lakh, rest = divmod(rest, 100_000)
    thousand, rest = divmod(rest, 1000)
    if crore:
        words = rupees_in_words(crore).replace(" Rupees Only", "").replace(" Rupee Only", "") if crore >= 100 else _under_hundred(crore)
        parts.append(f"{words} Crore")
    if lakh:
        parts.append(f"{_under_hundred(lakh)} Lakh")
    if thousand:
        parts.append(f"{_under_hundred(thousand)} Thousand")
    if rest:
        parts.append(_under_thousand(rest))
    return f"{' '.join(parts)} Rupees Only"


def _trim(value: Any) -> str:
    text = f"{float(value):.2f}".rstrip("0").rstrip(".")
    return text or "0"


def _devanagari() -> str | None:
    """The name of a registered face that draws Hindi, or None when none is installed. Reportlab joins the letters correctly
    when ``uharfbuzz`` is installed (it is in requirements.txt)."""
    if not _devanagari_font:
        name = None
        for directory in _FONT_DIRS:
            for file in _DEVANAGARI_FILES:
                if name is None and (directory / file).is_file():
                    try:
                        pdfmetrics.registerFont(TTFont("Orion-Devanagari", str(directory / file)))
                        name = "Orion-Devanagari"
                    except Exception:  # an unreadable font file is not worth failing a bill over
                        logger.warning("Could not load font %s", directory / file, exc_info=True)
        _devanagari_font.append(name)
    return _devanagari_font[0]


def _esc(value: Any) -> str:
    """Text made safe to put in a Paragraph, with any Hindi in it set in a face that has the letters."""
    text = str(value or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    face = _devanagari() if _DEVANAGARI.search(text) else None
    return _DEVANAGARI.sub(lambda run: f"<font name='{face}'>{run.group(0)}</font>", text) if face else text


# --------------------------------------------------------------------------- styles


def _styles(family: str = bill_fonts.DEFAULT_FAMILY, k: float = 1.0) -> dict[str, ParagraphStyle]:
    """The paragraph styles of a bill drawn in ``family`` at ``k`` times the usual size (k = size / 9)."""
    regular, bold, _ = fonts(family)

    def style(name: str, **kw: Any) -> ParagraphStyle:
        base = {"fontName": regular, "fontSize": 9 * k, "leading": 12 * k, "textColor": SLATE_900}
        return ParagraphStyle(name, **{**base, **kw})

    return {
        "body": style("body"),
        "bold": style("bold", fontName=bold),
        "small": style("small", fontSize=8 * k, leading=10.5 * k, textColor=SLATE_600),
        "label": style("label", fontName=bold, fontSize=6.8 * k, leading=9 * k, textColor=SLATE_500),
        "title": style("title", fontName=bold, fontSize=15 * k, leading=18 * k, textColor=NAVY),
        "party": style("party", fontName=bold, fontSize=11 * k, leading=14 * k),
        "head": style("head", fontName=bold, fontSize=7.5 * k, leading=10 * k, textColor=colors.white),
        "head_r": style("head_r", fontName=bold, fontSize=7.5 * k, leading=10 * k, textColor=colors.white, alignment=TA_RIGHT),
        "right": style("right", alignment=TA_RIGHT),
        "right_bold": style("right_bold", fontName=bold, alignment=TA_RIGHT),
        "badge": style("badge", fontName=bold, fontSize=8 * k, leading=10 * k, textColor=colors.white, alignment=TA_RIGHT),
    }


def _label(text: str, st: dict[str, ParagraphStyle]) -> Paragraph:
    return Paragraph(_esc(text).upper(), st["label"])


# --------------------------------------------------------------------------- invoice


def total_lines(bill: dict[str, Any]) -> list[tuple[str, Any, bool]]:
    """The rows above the grand total as (label, amount, strong): what the bill charges, minus what it leaves off.

    Mirrors the ``totals`` list in BillDocument.tsx. A charge at 0% is not on the bill unless its amount was entered by hand, and a
    part named in the bill's ``hidden`` list is not printed (the grand total always is). The bill may name the rows of its totals
    (``line_setup.labels``: lines_total, sub_total, taxable_total, epf, esic, service).
    """
    rates = bill.get("rates") or {}
    hidden = set(bill.get("hidden") or [])
    names = (bill.get("line_setup") or {}).get("labels") or {}
    entered = bill.get("manual_figures") or {}

    def pct(key: str) -> float:
        return float(rates.get(key) or 0)

    def charge(name: str | None, rate_key: str, amount_key: str, standard: str) -> tuple[str, Any, bool] | None:
        """A percentage charge, or one entered by hand (then it prints even at 0%, without a rate if it has none)."""
        if pct(rate_key) <= 0 and amount_key not in entered:
            return None
        label = (names.get(name) if name else None) or standard
        return (f"{label} @ {_trim(pct(rate_key))}%" if pct(rate_key) > 0 else label, bill.get(amount_key), False)

    rows: list[tuple[str, Any, bool]] = []
    if "lines_total" not in hidden:
        rows.append((names.get("lines_total") or "Total of lines", bill.get("lines_total"), False))
    for row in (charge("epf", "epf_pct", "epf_amount", "EPFO"), charge("esic", "esic_pct", "esic_amount", "ESIC")):
        if row:
            rows.append(row)
    has_sub = any(pct(key) > 0 or amount in entered for key, amount in (("epf_pct", "epf_amount"), ("esic_pct", "esic_amount")))
    if has_sub and "sub_total" not in hidden:
        rows.append((names.get("sub_total") or "Sub total", bill.get("sub_total"), False))
    service = charge("service", "service_pct", "service_amount", "Service charges")
    if service:
        rows.append(service)
    for extra in bill.get("extra_charges") or []:
        if float(extra.get("amount") or 0) == 0:
            continue
        label = f"{extra['label']} @ {_trim(extra['value'])}%" if extra.get("kind") == "pct" else extra["label"]
        rows.append((label, extra["amount"], False))
    if "taxable_total" not in hidden:
        rows.append((names.get("taxable_total") or "Taxable value", bill.get("taxable_total"), True))
    for name, key, amount in (("CGST", "cgst_pct", "cgst_amount"), ("SGST", "sgst_pct", "sgst_amount")):
        row = charge(None, key, amount, name)
        if row:
            rows.append(row)
    if abs(float(bill.get("round_off") or 0)) >= 0.005 and "round_off" not in hidden:
        rows.append(("Round off", bill.get("round_off"), False))
    return rows


def line_columns(bill: dict[str, Any]) -> list[tuple[str, str]]:
    """The columns of the lines table as (id, heading), left to right, after the running number: the particulars, the bill's
    own columns (id ``field:<key>``), then quantity, rate, days (a day-based bill only) and the amount. The quantity, rate and
    days go when the bill hides ``qty_rate``. Headings are the ones the bill names, else the standard ones.

    Mirrors ``lineColumns`` in frontend/src/billing/billLayout.ts."""
    setup = bill.get("line_setup") or {}
    basis = setup.get("basis") or "unit"
    names = setup.get("labels") or {}
    standard = {"particulars": "Particulars", "qty": "Qty", "days": "Days", "amount": "Amount",
                "rate": {"unit": "Rate", "daily": "Rate per day", "monthly": "Rate per month"}[basis]}

    def name(key: str) -> str:
        return names.get(key) or standard[key]

    columns = [("particulars", name("particulars"))]
    columns += [(f"field:{column['key']}", column["label"]) for column in setup.get("columns") or []]
    if "qty_rate" not in (bill.get("hidden") or []):
        columns += [("qty", name("qty")), ("rate", name("rate"))]
        if basis != "unit":
            columns.append(("days", name("days")))
    columns.append(("amount", name("amount")))
    return columns


def _sum(values: list[Any], places: int) -> str:
    return _trim(round(sum(float(value) for value in values if value is not None), places))


def invoice_pdf(bill: dict[str, Any], letterhead: Letterhead | None = None) -> bytes:
    """The tax invoice for a bill as returned by ``billing.get_bill``, on the letterhead when one is given."""
    choice = bill.get("font") or bill_fonts.effective(bill)  # get_bill adds the effective choice; a stored version has only its own
    k = float(choice["size"]) / bill_fonts.BASE_SIZE
    regular, bold, rupee = fonts(choice["family"])
    st = _styles(choice["family"], k)
    wide = min(k, 1.3)  # columns of figures grow with the text, but not so much that the particulars are squeezed
    profile = bill.get("profile") or {}
    cancelled = bill.get("status") == "Cancelled"
    width = A4[0] - 22 * mm
    head_w = 38 * mm * wide
    hidden = set(bill.get("hidden") or [])  # parts of the bill this one leaves off (billing.HIDEABLE)

    def money(value: Any) -> str:
        return indian(value)

    story: list[Any] = []

    on_letterhead = letterhead is not None
    ids = [] if on_letterhead else [
        (label, profile.get(key)) for label, key in
        (("GSTIN", "gstin"), ("PAN", "pan"), ("PF No.", "pf_no"), ("ESI No.", "esi_no"), ("Reg. No.", "reg_no"))
        if profile.get(key) and key not in hidden]
    ids += [(field["label"], field["value"]) for field in bill.get("header_fields") or []]  # this bill's own details

    def ident_table(total: float, most: int) -> Table | None:
        """The registration numbers and this bill's own details, ``most`` to a row so a long list wraps."""
        if not ids:
            return None
        per_row = min(len(ids), max(2, most - (2 if k >= 1.45 else 1 if k >= 1.2 else 0)))  # larger text, fewer to a row
        rows: list[list[Any]] = []
        for start in range(0, len(ids), per_row):
            chunk = ids[start:start + per_row]
            pad = [""] * (per_row - len(chunk))
            rows.append([_label(label, st) for label, _ in chunk] + pad)
            rows.append([Paragraph(_esc(value), st["bold"]) for _, value in chunk] + pad)
        table = Table(rows, colWidths=[total / per_row] * per_row)
        table.setStyle(TableStyle([("LINEABOVE", (0, 0), (-1, 0), 0.6, LINE), ("LINEBELOW", (0, -1), (-1, -1), 0.6, LINE),
                                   ("LEFTPADDING", (0, 0), (-1, -1), 0), ("TOPPADDING", (0, 0), (-1, -1), 2),
                                   ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]))
        return table

    badge = Table([[Paragraph("TAX INVOICE", st["badge"])]], colWidths=[34 * mm * wide])
    badge.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), NAVY), ("TOPPADDING", (0, 0), (-1, -1), 5),
                               ("BOTTOMPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 8)]))
    head_style = TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                             ("RIGHTPADDING", (0, 0), (-1, -1), 0), ("ALIGN", (1, 0), (1, 0), "RIGHT")])
    if on_letterhead:
        # The letterhead already carries the company's name, address, contact and registration numbers, and it
        # leaves less room, so only this bill's own details are drawn, beside the title.
        head = Table([[ident_table(width - head_w - 6 * mm, 4) or "", badge]], colWidths=[width - head_w, head_w])
        head.setStyle(head_style)
        story += [head, Spacer(1, 7)]
    else:
        head_left = [Paragraph(_esc(profile.get("company_name")).upper(), st["title"])]
        if profile.get("address") and "address" not in hidden:
            head_left.append(Paragraph(_esc(profile["address"]), st["small"]))
        if profile.get("phone") and "phone" not in hidden:
            head_left.append(Paragraph(f"Contact: {_esc(profile['phone'])}", st["small"]))
        head = Table([[head_left, badge]], colWidths=[width - head_w, head_w])
        head.setStyle(head_style)
        story += [head, Spacer(1, 6)]
        ident = ident_table(width, 5)
        if ident:
            story.append(ident)
        story.append(Spacer(1, 10))

    # Billed to, and the invoice facts
    party = [_label("Billed to", st), Paragraph(_esc(bill.get("party_name")) or "-", st["party"])]
    if bill.get("party_address") and "party_address" not in hidden:
        party.append(Paragraph(_esc(bill["party_address"]), st["small"]))
    if bill.get("party_state") and "party_state" not in hidden:
        party.append(Paragraph(_esc(bill["party_state"]), st["small"]))
    if bill.get("party_gstin") and "party_gstin" not in hidden:
        party.append(Paragraph(f"GSTIN <font name='{bold}'>{_esc(bill['party_gstin'])}</font>", st["body"]))
    for field in bill.get("party_fields") or []:  # this bill's own details of the client
        party.append(Paragraph(f"{_esc(field['label'])} <font name='{bold}'>{_esc(field['value'])}</font>", st["body"]))

    facts = [
        ("Invoice no.", f"<font name='{bold}' color='#0f2f57' size='{10 * k:.1f}'>{_esc(bill.get('bill_number'))}</font>"),
        ("Invoice date", _esc(day(bill.get("bill_date")))),
    ]
    if "for_month" not in hidden:
        facts.append(("For the month", _esc(month(bill.get("service_month")))))
    if (bill.get("ref_no") or bill.get("ref_date")) and "ref" not in hidden:
        ref = _esc(bill.get("ref_no"))
        if bill.get("ref_date"):
            ref += f"<br/><font size='{7.5 * k:.1f}' color='#475569'>dated {_esc(day(bill['ref_date']))}</font>"
        facts.append(("Your ref.", ref))
    if bill.get("tender_id") and "tender_id" not in hidden:
        facts.append(("Tender ID", _esc(bill["tender_id"])))
    if bill.get("tender_start_date") and "tender_date" not in hidden:
        facts.append(("Tender start", _esc(day(bill["tender_start_date"]))))
    fact_table = Table([[Paragraph(label, st["small"]), Paragraph(value, st["bold"])] for label, value in facts],
                       colWidths=[24 * mm * wide, None])
    fact_table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), PANEL), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                                    ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]))
    meta = Table([[party, fact_table]], colWidths=[width * 0.58, width * 0.42])
    meta.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (0, 0), 0),
                              ("RIGHTPADDING", (1, 0), (1, 0), 0)]))
    story.append(meta)
    story.append(Spacer(1, 10))

    where = bill.get("location") if "location" not in hidden else None
    what = bill.get("service_description") if "service_description" not in hidden else None
    if where or what:
        rows = []
        if where:
            rows.append([Paragraph(f"<font color='#64748b'>Location </font><font name='{bold}'>{_esc(where)}</font>", st["body"])])
        if what:
            rows.append([Paragraph(f"{_esc(month(bill.get('service_month')))} &middot; {_esc(what)}", st["body"])])
        box = Table(rows, colWidths=[width])
        box.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.6, LINE), ("TOPPADDING", (0, 0), (-1, -1), 3),
                                 ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
        story.append(box)
        story.append(Spacer(1, 8))

    # Lines: the columns this bill has (line_columns). Hiding the quantity and rate leaves the particulars and amounts.
    columns = line_columns(bill)
    column_ids = [column_id for column_id, _ in columns]
    rows_in = bill.get("lines") or []
    line_rows = [[Paragraph("NO.", st["head"]),
                  *[Paragraph(_esc(heading).upper(), st["head_r"] if column_id in ("qty", "rate", "days", "amount") else st["head"])
                    for column_id, heading in columns]]]
    for index, line in enumerate(rows_in, start=1):
        cells = []
        for column_id in column_ids:
            if column_id == "particulars":
                cells.append(Paragraph(_esc(line.get("particulars")), st["bold"]))
            elif column_id.startswith("field:"):
                cells.append(Paragraph(_esc((line.get("fields") or {}).get(column_id[6:])), st["body"]))
            elif column_id == "qty":
                cells.append(Paragraph(_trim(line.get("qty")) if line.get("qty") is not None else "", st["right"]))
            elif column_id == "rate":
                cells.append(Paragraph(money(line.get("rate")) if line.get("rate") is not None else "", st["right"]))
            elif column_id == "days":
                cells.append(Paragraph(_trim(line.get("days")) if line.get("days") is not None else "", st["right"]))
            else:
                cells.append(Paragraph(money(line.get("amount")), st["right_bold"]))
        line_rows.append([Paragraph(str(index), st["small"]), *cells])
    setup = bill.get("line_setup") or {}
    if setup.get("totals_row") and rows_in:
        # The sums of the columns that can be added up: how many, how many days and the amount.
        sums = {"particulars": "Total", "amount": money(sum(float(line.get("amount") or 0) for line in rows_in)),
                "qty": _sum([line.get("qty") for line in rows_in], 3), "days": _sum([line.get("days") for line in rows_in], 2)}
        line_rows.append([Paragraph("", st["body"]),
                          *[Paragraph(sums.get(column_id, ""), st["right_bold"] if column_id != "particulars" else st["bold"]) for column_id in column_ids]])
    own = sum(1 for column_id in column_ids if column_id.startswith("field:"))
    fixed = {"qty": 18, "rate": 26, "days": 20, "amount": 32}
    taken = 10 + sum(fixed.get(column_id, 0) for column_id in column_ids)
    # The bill's own columns share what is left after a particulars column of at least 45 mm.
    own_mm = max(14.0, min(26.0, (width / mm - taken * wide - 45) / own / wide)) if own else 0
    widths = [10 * mm * wide]
    for column_id in column_ids:
        widths.append(None if column_id == "particulars" else own_mm * mm * wide if column_id.startswith("field:") else fixed[column_id] * mm * wide)
    lines = Table(line_rows, colWidths=widths, repeatRows=1)
    total_row = bool(setup.get("totals_row") and rows_in)
    lines.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), NAVY), ("LINEBELOW", (0, 1), (-1, -1), 0.5, LINE),
                               ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 4),
                               ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                               *([("LINEABOVE", (0, -1), (-1, -1), 0.9, SLATE_900), ("BACKGROUND", (0, -1), (-1, -1), PANEL)] if total_row else [])]))
    story.append(lines)
    story.append(Spacer(1, 8))

    # Amount in words and totals
    total_rows = []
    for label, value, strong in total_lines(bill):
        number = float(value or 0)
        shown = ("\u2212" if number < 0 else "") + money(abs(number))
        total_rows.append([Paragraph(label, st["bold"] if strong else st["body"]),
                           Paragraph(shown, st["right_bold"] if strong else st["right"])])
    total_rows.append([Paragraph(f"<font color='white' name='{bold}' size='{7.5 * k:.1f}'>GRAND TOTAL</font>", st["body"]),
                       Paragraph(f"<font color='white' name='{bold}' size='{11 * k:.1f}'>{rupee} {money(bill.get('grand_total'))}</font>", st["right"])])
    total_table = Table(total_rows, colWidths=[42 * mm * wide, 34 * mm * wide])
    total_table.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, -2), 0.4, LINE), ("BACKGROUND", (0, -1), (-1, -1), NAVY),
                                     ("TOPPADDING", (0, 0), (-1, -1), 2.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
                                     ("VALIGN", (0, -1), (-1, -1), "MIDDLE")]))
    words = ("" if "amount_in_words" in hidden else
             [_label("Amount in words", st), Paragraph(rupees_in_words(bill.get("grand_total")), st["bold"])])
    summary = Table([[words, total_table]], colWidths=[width - 76 * mm * wide, 76 * mm * wide])
    summary.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (0, 0), 0),
                                 ("LEFTPADDING", (1, 0), (1, 0), 0), ("RIGHTPADDING", (1, 0), (1, 0), 0)]))
    story.append(KeepTogether(summary))
    story.append(Spacer(1, 10 if on_letterhead else 18))

    # Bank, terms, signature
    left: list[Any] = []
    if (profile.get("bank_name") or profile.get("bank_account")) and "bank" not in hidden:
        left.append(_label("Bank details", st))
        if profile.get("bank_name"):
            left.append(Paragraph(_esc(profile["bank_name"]), st["bold"]))
        if profile.get("bank_account"):
            left.append(Paragraph(f"A/c No. <font name='{bold}'>{_esc(profile['bank_account'])}</font>", st["small"]))
        if profile.get("bank_ifsc"):
            left.append(Paragraph(f"IFSC <font name='{bold}'>{_esc(profile['bank_ifsc'])}</font>", st["small"]))
        left.append(Spacer(1, 5))
    terms = [] if "terms" in hidden else (profile.get("terms") or [])
    if terms:
        left.append(_label("Terms", st))
        for number, term in enumerate(terms, start=1):
            left.append(Paragraph(f"{number}. {_esc(term)}", st["small"]))
    right: list[Any] = []
    if "signatory" not in hidden:
        right += [Paragraph(_esc(profile.get("signatory")), ParagraphStyle("sig", parent=st["right_bold"])), Spacer(1, 34)]
    else:
        right.append(Spacer(1, 34))
    sign_cells = ([] if "customer_signature" in hidden else [Paragraph("Customer's signature", st["small"])]) + \
                 ([] if "signatory" in hidden else
                  [Paragraph(_esc(profile.get("signatory_title")), ParagraphStyle("t", parent=st["small"], alignment=TA_RIGHT))])
    if sign_cells:
        sign = Table([sign_cells], colWidths=[(width / 2 - 4) / 2] * len(sign_cells))
        sign.setStyle(TableStyle([("LINEABOVE", (0, 0), (-1, 0), 0.5, colors.HexColor("#cbd5e1")), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                                  ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
        right.append(sign)
    footer = Table([[left or "", right or ""]], colWidths=[width / 2, width / 2])
    footer.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEABOVE", (0, 0), (-1, 0), 0.6, LINE),
                                ("TOPPADDING", (0, 0), (-1, -1), 8), ("LEFTPADDING", (0, 0), (0, 0), 0),
                                ("RIGHTPADDING", (1, 0), (1, 0), 0)]))
    story.append(KeepTogether(footer))

    def decorate(canvas, doc):  # noqa: ANN001
        if not cancelled:
            return
        canvas.saveState()
        canvas.setFont(bold, 90)
        canvas.setFillColor(colors.Color(0.86, 0.15, 0.15, alpha=0.15))
        canvas.translate(A4[0] / 2, A4[1] / 2)
        canvas.rotate(28)
        canvas.drawCentredString(0, 0, "CANCELLED")
        canvas.restoreState()

    title, author = f"Invoice {bill.get('bill_number')}", str(profile.get("company_name") or "")
    if letterhead is not None:
        return letterhead.build(story, title=title, author=author, side_mm=11, gap_mm=BILL_GAP_MM, decorate=decorate)
    out = io.BytesIO()
    doc = SimpleDocTemplate(out, pagesize=A4, leftMargin=11 * mm, rightMargin=11 * mm, topMargin=10 * mm,
                            bottomMargin=10 * mm, title=title, author=author)
    doc.build(story, onFirstPage=decorate, onLaterPages=decorate)
    return out.getvalue()


# --------------------------------------------------------------------------- statement


def statement_pdf(statement: dict[str, Any], profile: dict[str, Any], letterhead: Letterhead | None = None) -> bytes:
    """A client's unpaid bills, oldest first, with the ageing of what is owed.

    ``statement`` is one client entry of ``receivables.build_receivables`` plus ``as_of`` and the
    bucket labels; ``profile`` is the company's details (``billing.get_profile``). On the letterhead the
    typed company name, address and contact are left off.
    """
    regular, bold, rupee = fonts()
    st = _styles()
    width = A4[0] - 22 * mm
    story: list[Any] = []
    if letterhead is None:
        story.append(Paragraph(_esc(profile.get("company_name")).upper(), st["title"]))
        if profile.get("address"):
            story.append(Paragraph(_esc(profile["address"]), st["small"]))
        if profile.get("phone"):
            story.append(Paragraph(f"Contact: {_esc(profile['phone'])}", st["small"]))
        story.append(Spacer(1, 12))
    story.append(Paragraph("STATEMENT OF OUTSTANDING BILLS", ParagraphStyle("h", parent=st["bold"], fontSize=11, textColor=NAVY)))
    story.append(Spacer(1, 6))
    story.append(Paragraph(_esc(statement.get("billing_name") or statement.get("client_name")), st["party"]))
    story.append(Paragraph(f"As on {_esc(day(statement.get('as_of')))}", st["small"]))
    story.append(Spacer(1, 10))

    rows = [[Paragraph(text, st["head_r" if right else "head"]) for text, right in
             (("BILL NO.", False), ("BILL DATE", False), ("FOR THE MONTH", False), ("CASE / SITE", False),
              ("BILL TOTAL", True), ("RECEIVED", True), ("TO RECEIVE", True), ("DAYS", True))]]
    for bill in statement.get("bills") or []:
        rows.append([
            Paragraph(_esc(bill["bill_number"]), st["bold"]), Paragraph(_esc(day(bill["bill_date"])), st["body"]),
            Paragraph(_esc(month(bill["service_month"])), st["body"]),
            Paragraph(_esc(bill.get("location") or bill.get("case_name")), st["small"]),
            Paragraph(indian(bill["grand_total"]), st["right"]), Paragraph(indian(bill["received"]), st["right"]),
            Paragraph(indian(bill["balance"]), st["right_bold"]), Paragraph(str(bill["days"]), st["right"]),
        ])
    rows.append([Paragraph("TOTAL TO RECEIVE", ParagraphStyle("tt", parent=st["bold"], textColor=colors.white)), "", "", "", "", "",
                 Paragraph(f"<font color='white' name='{bold}'>{rupee} {indian(statement.get('total'))}</font>", st["right"]), ""])
    table = Table(rows, colWidths=[24 * mm, 22 * mm, 26 * mm, None, 24 * mm, 22 * mm, 26 * mm, 11 * mm], repeatRows=1)
    table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), NAVY), ("BACKGROUND", (0, -1), (-1, -1), NAVY),
                               ("SPAN", (0, -1), (5, -1)), ("LINEBELOW", (0, 1), (-1, -2), 0.5, LINE),
                               ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 4),
                               ("BOTTOMPADDING", (0, 0), (-1, -1), 4), ("LEFTPADDING", (0, 0), (-1, -1), 4),
                               ("RIGHTPADDING", (0, 0), (-1, -1), 4)]))
    story.append(table)
    story.append(Spacer(1, 12))

    labels = statement.get("bucket_labels") or []
    amounts = statement.get("buckets") or []
    if labels and amounts:
        age = Table([[_label(label, st) for label in labels],
                     [Paragraph(f"{rupee} {indian(value)}", st["bold"]) for value in amounts]],
                    colWidths=[width / len(labels)] * len(labels))
        age.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), PANEL), ("TOPPADDING", (0, 0), (-1, -1), 4),
                                 ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
        story.append(_label("Age of what is owed, from the bill date", st))
        story.append(Spacer(1, 3))
        story.append(age)
        story.append(Spacer(1, 14))

    pay: list[Any] = []
    if profile.get("bank_name") or profile.get("bank_account"):
        pay.append(_label("Please pay to", st))
        pay.append(Paragraph(f"{_esc(profile.get('bank_name'))} &middot; A/c No. <font name='{bold}'>{_esc(profile.get('bank_account'))}</font>"
                             f" &middot; IFSC <font name='{bold}'>{_esc(profile.get('bank_ifsc'))}</font>", st["body"]))
    pay.append(Spacer(1, 6))
    pay.append(Paragraph("Please ignore this statement if payment has already been made, and let us have the details so we can "
                         "update our records.", st["small"]))
    story.append(KeepTogether(pay))

    title, author = f"Statement {statement.get('client_name')}", str(profile.get("company_name") or "")
    if letterhead is not None:
        return letterhead.build(story, title=title, author=author, side_mm=11, gap_mm=BILL_GAP_MM)
    out = io.BytesIO()
    SimpleDocTemplate(out, pagesize=A4, leftMargin=11 * mm, rightMargin=11 * mm, topMargin=10 * mm, bottomMargin=10 * mm,
                      title=title, author=author).build(story)
    return out.getvalue()
