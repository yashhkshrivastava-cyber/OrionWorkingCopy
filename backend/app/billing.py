"""Bills raised in the application.

Issued bills are stored in ``orion_ods.bill``, created by ``.cursor/db/migrate_bill.sql``.
A bill is tagged to a case, and its client is the case's client. The party details that
are printed are a copy held on the bill, so changing a client later never alters a bill.

An issued bill can be edited. The row is always the current version; each version it
replaces is kept whole in ``orion_ods.bill_version``. Cancelling a bill and marking its
GST as paid are tracking changes, not edits, and do not create a version.

Raising a bill also writes its revenue into ``orion_ods.case_transaction``, and recording
a payment moves that revenue from Prospective to Committed. See "revenue entries" below.

Money is calculated with Decimal, in whole paise, and the rules are the ones the Excel
bill already follows:

* every line is quantity x rate, to the paisa;
* EPFO and ESIC are a percentage of the lines total, and so are service charges;
* a bill can carry extra charges the user names, each a percentage of the lines total or a fixed amount;
* GST is a percentage of everything before it (lines + EPFO + ESIC + service charges + extra charges);
* a charge left off a bill is simply 0%, and the bill's ``hidden`` list names parts of the printed bill to leave off;
* a bill can carry extra header details (``header_fields``), printed with the GSTIN and PAN, and extra details
  of the client (``party_fields``), printed under the client's GSTIN;
* the grand total is rounded to the nearest rupee and the difference is shown as round-off.

The same rules are implemented in ``frontend/src/billing/billCalc.ts`` for the live
preview. The server recalculates on save, so what is stored never depends on the browser.
"""

from __future__ import annotations

import calendar
import json
import logging
import re
import uuid
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from app import bill_fonts
from app.database import db_cursor, get_connection
from app.idempotency import Idempotency

logger = logging.getLogger(__name__)

PAISA = Decimal("0.01")
RUPEE = Decimal("1")
QTY_STEP = Decimal("0.001")

DEFAULT_RATES = {
    "epf_pct": Decimal("13"),
    "esic_pct": Decimal("3.25"),
    "service_pct": Decimal("10"),
    "cgst_pct": Decimal("9"),
    "sgst_pct": Decimal("9"),
}
MAX_EXTRA_CHARGES = 6
MAX_HEADER_FIELDS = 6
MAX_PARTY_FIELDS = 6
EXTRA_KINDS = ("pct", "amount")

# Parts of the printed bill that one bill can leave off. The same keys, in the same groups, are in
# frontend/src/billing/billLayout.ts (a test compares them), and both printed bills honour them.
HIDEABLE: dict[str, tuple[str, ...]] = {
    "Our details": ("address", "phone", "gstin", "pan", "pf_no", "esi_no", "reg_no"),
    "Billed to": ("party_address", "party_state", "party_gstin"),
    "Invoice details": ("for_month", "ref", "tender_id", "tender_date"),
    "Service": ("location", "service_description"),
    "Lines": ("qty_rate",),
    "Totals": ("amount_in_words", "lines_total", "sub_total", "taxable_total", "round_off"),
    "Footer": ("bank", "terms", "signatory", "customer_signature"),
}
HIDEABLE_KEYS = frozenset(key for keys in HIDEABLE.values() for key in keys)
MAX_LINES = 30
# How a bill's lines are worked out. unit: quantity x rate. daily: rate x days (times the quantity, when the bill says it
# counts). monthly: the same, with the days as a share of the month (days / month_days of a monthly rate).
LINE_BASES = ("unit", "daily", "monthly")
MAX_LINE_COLUMNS = 5
# The names a bill can give its columns, and the rows of its totals (the standard names are in billLayout.ts and billing_pdf.line_columns).
LINE_LABEL_KEYS = ("particulars", "qty", "rate", "days", "amount", "lines_total", "sub_total", "taxable_total", "epf", "esic", "service")
# Charges a line can be left out of, and the figures a person may enter instead of the calculated one.
SKIP_KEYS = ("epf", "esic", "service")
# What the service charge's percentage is taken of: the lines (that are part of it), or those and the EPFO and ESIC as well.
SERVICE_BASES = ("lines", "lines_epf_esic")
MANUAL_KEYS = {
    "epf_amount": "EPFO", "esic_amount": "ESIC", "service_amount": "Service charges", "cgst_amount": "CGST", "sgst_amount": "SGST",
}
MAX_AMOUNT = Decimal("10000000000")
MAX_DAYS = Decimal("100000")
DAYS_STEP = Decimal("0.01")
_COLUMN_KEY = re.compile(r"^[a-z0-9_]{1,20}$")
MAX_QTY = Decimal("1000000")
MAX_RATE = Decimal("100000000")

# Header printed on every bill. Edited from the Billing page; a copy is stored with each
# bill so reprinting an old bill never changes its letterhead.
DEFAULT_PROFILE: dict[str, Any] = {
    "company_name": "PRAKASH SECURITY SERVICES & WORKER CONTRACTOR",
    "address": "Vihar, Opposite Mascot Hospital, Sindhi Colony Road, Gwalior",
    "phone": "+91 7898264351, 9993931876",
    "gstin": "23AMNPM3066F2Z2",
    "pan": "AMNPM3066F",
    "pf_no": "MP/0025768",
    "esi_no": "18000228820001009",
    "reg_no": "17307/Gwl./CE/07",
    "bank_name": "ICICI Bank",
    "bank_ifsc": "ICIC0001438",
    "bank_account": "143805001573",
    "signatory": "For P.S.S. & W.C.",
    "signatory_title": "Chief Accountant",
    "terms": [
        "All disputes are subject to Gwalior jurisdiction.",
        "Please give us the cross cheque payment before the 5th of every month.",
        "E. & O.E.",
    ],
    "default_service_description": "Cleaning & Maintenance",
}
PROFILE_TEXT_LIMIT = 300
# The parts of the template (letterhead, registrations, bank, terms, signature) that one bill can have its own version of.
# Mirrors ``FIELDS`` in frontend/src/components/billing/BillOwnDetails.tsx.
PROFILE_BILL_KEYS = (
    "company_name", "address", "phone", "gstin", "pan", "pf_no", "esi_no", "reg_no",
    "bank_name", "bank_ifsc", "bank_account", "signatory", "signatory_title", "terms",
)


_GSTIN = re.compile(r"^[0-9A-Z]{15}$")


class BillError(ValueError):
    """The request cannot become a bill. The message is safe to show to the user."""


# --------------------------------------------------------------------------- numbering


def fy_start_year(day: date) -> int:
    """Indian financial year: April to March, named by the year it starts."""
    return day.year if day.month >= 4 else day.year - 1


def fy_label(start_year: int) -> str:
    return f"{start_year}-{(start_year + 1) % 100:02d}"


def bill_number(start_year: int, seq: int) -> str:
    return f"{fy_label(start_year)}/{seq}"


# --------------------------------------------------------------------------- arithmetic


def _dec(value: Any, label: str) -> Decimal:
    try:
        number = Decimal(str(value).strip() or "0")
    except (InvalidOperation, ValueError):
        raise BillError(f"{label} must be a number.") from None
    if not number.is_finite():
        raise BillError(f"{label} must be a number.")
    return number


def _paisa(value: Decimal) -> Decimal:
    return value.quantize(PAISA, rounding=ROUND_HALF_UP)


def _pct_of(base: Decimal, pct: Decimal) -> Decimal:
    return _paisa(base * pct / 100)


def clean_rates(rates: dict[str, Any] | None) -> dict[str, Decimal]:
    merged = {**DEFAULT_RATES}
    for key, value in (rates or {}).items():
        if key not in DEFAULT_RATES or value is None or value == "":
            continue
        pct = _dec(value, key)
        if pct < 0 or pct > 100:
            raise BillError("Percentages must be between 0 and 100.")
        merged[key] = pct.quantize(PAISA, rounding=ROUND_HALF_UP)
    return merged


def clean_line_setup(setup: dict[str, Any] | None) -> dict[str, Any]:
    """The layout of a bill's lines, always in full so the stored copy reads the same however it was sent. An empty one is
    the original layout: quantity x rate, no extra columns, the standard column names."""
    raw = setup or {}
    basis = raw.get("basis") or "unit"
    if basis not in LINE_BASES:
        raise BillError("Lines are worked out as quantity x rate, by the day or by the month.")
    month_days = raw.get("month_days")
    if month_days in (None, ""):
        month_days = None
    else:
        try:
            month_days = int(month_days)
        except (TypeError, ValueError):
            raise BillError("Days in the month must be a whole number from 1 to 31.") from None
        if not 1 <= month_days <= 31:
            raise BillError("Days in the month must be a whole number from 1 to 31.")
    service_on = raw.get("service_on") or "lines"
    if service_on not in SERVICE_BASES:
        raise BillError("The service charge is taken on the lines, or on the lines with the EPFO and ESIC.")
    labels = {}
    for key, value in (raw.get("labels") or {}).items():
        if key not in LINE_LABEL_KEYS:
            raise BillError(f"'{key}' is not a column of the lines.")
        text = " ".join(str(value or "").split())[:30]
        if text:
            labels[key] = text
    columns: list[dict[str, str]] = []
    for index, column in enumerate(raw.get("columns") or [], start=1):
        key = str(column.get("key") or "").strip()
        label = " ".join(str(column.get("label") or "").split())[:30]
        if not key and not label:
            continue
        if not _COLUMN_KEY.match(key) or any(key == other["key"] for other in columns):
            raise BillError(f"Column {index} is not valid.")
        if not label:
            raise BillError(f"Column {index} needs a name.")
        columns.append({"key": key, "label": label})
    if len(columns) > MAX_LINE_COLUMNS:
        raise BillError(f"A bill can have at most {MAX_LINE_COLUMNS} extra columns.")
    return {
        "basis": basis,
        "qty_multiplies": bool(raw.get("qty_multiplies", True)),
        "month_days": month_days,
        "totals_row": bool(raw.get("totals_row", False)),
        "charge_by_line": bool(raw.get("charge_by_line", False)),
        "service_on": service_on,
        "labels": labels,
        "columns": columns,
    }


def days_in_month(month: date | None) -> int:
    return calendar.monthrange(month.year, month.month)[1] if month else 30


def _half_up_div(numerator: int, denominator: int) -> int:
    return (2 * numerator + denominator) // (2 * denominator)


def _given(value: Any) -> bool:
    return str(value if value is not None else "").strip() != ""


def clean_lines(lines: list[dict[str, Any]], setup: dict[str, Any] | None = None, month_days: int = 30) -> list[dict[str, Any]]:
    """The lines as stored: each with its amount. ``setup`` is a cleaned layout (clean_line_setup); without one, quantity x rate.

    A line's amount is worked out from its quantity, rate and days, unless the person entered it (``amount_manual``): then that is
    the amount, the quantity, rate and days become optional, and the line keeps the amount it would have had (``auto_amount``) so a
    difference can be pointed out. A line can be left out of the EPFO, ESIC or service charge (``skip``)."""
    setup = setup if setup is not None and "labels" in setup else clean_line_setup(setup)
    basis, by_qty = setup["basis"], setup["qty_multiplies"]
    columns = setup["columns"]
    out: list[dict[str, Any]] = []
    for index, raw in enumerate(lines or [], start=1):
        particulars = str(raw.get("particulars") or "").strip()
        qty_raw, rate_raw, days_raw, manual_raw = raw.get("qty"), raw.get("rate"), raw.get("days"), raw.get("amount_manual")
        given = raw.get("fields") or {}
        values = {column["key"]: " ".join(str(given.get(column["key"]) or "").split())[:80] for column in columns}
        blank = (
            not particulars and not _given(qty_raw) and not _given(rate_raw) and not _given(days_raw) and not _given(manual_raw)
            and not any(values.values())
        )
        if blank:
            continue
        if not particulars:
            raise BillError(f"Line {index} needs a description.")
        skip = sorted({str(key) for key in raw.get("skip") or []})
        if any(key not in SKIP_KEYS for key in skip):
            raise BillError(f"Line {index} can only be left out of EPFO, ESIC or service charges.")
        has_manual = _given(manual_raw)
        manual = None
        if has_manual:
            manual = _paisa(_dec(manual_raw, f"Line {index} amount"))
            if manual < 0 or manual > MAX_AMOUNT:
                raise BillError(f"Line {index} amount is out of range.")
        needs_qty = basis == "unit" or by_qty
        qty = None
        if _given(qty_raw) or (needs_qty and not has_manual):
            qty = _dec(qty_raw, f"Line {index} quantity").quantize(QTY_STEP, rounding=ROUND_HALF_UP)
            if (needs_qty and qty <= 0 and not has_manual) or qty < 0 or qty > MAX_QTY:
                raise BillError(f"Line {index} quantity must be more than 0.")
        rate = None
        if _given(rate_raw) or not has_manual:
            rate = _paisa(_dec(rate_raw, f"Line {index} rate"))
            if rate < 0 or rate > MAX_RATE:
                raise BillError(f"Line {index} rate is out of range.")
        days = None
        if basis != "unit":
            if _given(days_raw) or (basis == "daily" and not has_manual):
                days = _dec(days_raw, f"Line {index} days").quantize(DAYS_STEP, rounding=ROUND_HALF_UP)
                if days <= 0 or days > MAX_DAYS:
                    raise BillError(f"Line {index} needs the number of days.")
            elif basis == "monthly" and rate is not None:
                days = Decimal(month_days)  # a monthly rate with no days is the whole month
        # What the quantity, rate and days come to, when they are all there.
        paise = None
        if rate is not None and (qty is not None or not (basis == "unit" or by_qty)) and (basis == "unit" or days is not None):
            qty_t = int((qty or 0) * 1000)
            rate_p = int(rate * 100)
            if basis == "unit":
                paise = _half_up_div(qty_t * rate_p, 1000)
            else:
                days_h = int(days * 100)
                share = month_days if basis == "monthly" else 1
                if by_qty:
                    paise = _half_up_div(qty_t * rate_p * days_h, 100_000 * share)
                else:
                    paise = _half_up_div(rate_p * days_h, 100 * share)
        auto = None if paise is None else (Decimal(paise) / 100).quantize(PAISA)
        row: dict[str, Any] = {"particulars": particulars[:200], "qty": qty, "rate": rate}
        if basis != "unit":
            row["days"] = days
        if columns:
            row["fields"] = values
        if skip:
            row["skip"] = skip
        if manual is not None:
            row["manual"] = True
            row["auto_amount"] = auto
        row["amount"] = manual if manual is not None else auto
        out.append(row)
    if not out:
        raise BillError("Add at least one line with a quantity and a rate." if basis == "unit" else "Add at least one line with a rate and days.")
    if len(out) > MAX_LINES:
        raise BillError(f"A bill can have at most {MAX_LINES} lines.")
    return out


def clean_manual_figures(manual: dict[str, Any] | None) -> dict[str, Decimal]:
    """The figures a person entered instead of the calculated ones (MANUAL_KEYS). An empty one is left to the calculation."""
    out: dict[str, Decimal] = {}
    for key, value in (manual or {}).items():
        if key not in MANUAL_KEYS:
            raise BillError(f"'{key}' cannot be entered by hand.")
        if not _given(value):
            continue
        amount = _paisa(_dec(value, f"{MANUAL_KEYS[key]} amount"))
        if amount < 0 or amount > MAX_AMOUNT:
            raise BillError(f"{MANUAL_KEYS[key]} amount is out of range.")
        out[key] = amount
    return out


def clean_extra_charges(charges: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """The charges a user added by name. A row with no label and no value is ignored, like a blank line."""
    out: list[dict[str, Any]] = []
    for index, raw in enumerate(charges or [], start=1):
        label = " ".join(str(raw.get("label") or "").split())
        value_raw = raw.get("value")
        if not label and not str(value_raw if value_raw is not None else "").strip():
            continue
        if not label:
            raise BillError(f"Extra charge {index} needs a name.")
        kind = raw.get("kind") or "pct"
        if kind not in EXTRA_KINDS:
            raise BillError(f"Extra charge '{label}' must be a percentage or an amount.")
        value = _dec(value_raw if value_raw is not None else 0, f"Extra charge '{label}'")
        if kind == "pct":
            if value < 0 or value > 100:
                raise BillError("Percentages must be between 0 and 100.")
            value = value.quantize(PAISA, rounding=ROUND_HALF_UP)
        else:
            if value < 0 or value > MAX_RATE:
                raise BillError(f"Extra charge '{label}' is out of range.")
            value = _paisa(value)
        out.append({"label": label[:60], "kind": kind, "value": value})
    if len(out) > MAX_EXTRA_CHARGES:
        raise BillError(f"A bill can have at most {MAX_EXTRA_CHARGES} extra charges.")
    return out


def _clean_named(fields: list[dict[str, Any]] | None, noun: str, limit: int) -> list[dict[str, str]]:
    """Named details as (label, value) pairs. A blank row is ignored; one with only a name or only a value is refused."""
    out: list[dict[str, str]] = []
    for index, raw in enumerate(fields or [], start=1):
        label = " ".join(str(raw.get("label") or "").split())[:30]
        value = " ".join(str(raw.get("value") or "").split())[:80]
        if not label and not value:
            continue
        if not label or not value:
            raise BillError(f"{noun.capitalize()} {index} needs both a name and a value.")
        out.append({"label": label, "value": value})
    if len(out) > limit:
        raise BillError(f"A bill can have at most {limit} {noun}s.")
    return out


def clean_header_fields(fields: list[dict[str, Any]] | None) -> list[dict[str, str]]:
    """Details printed with the GSTIN and PAN at the top of a bill, such as a vendor code."""
    return _clean_named(fields, "header detail", MAX_HEADER_FIELDS)


def clean_party_fields(fields: list[dict[str, Any]] | None) -> list[dict[str, str]]:
    """Details about the client printed under its GSTIN in Billed to, such as a state code or vendor number."""
    return _clean_named(fields, "client detail", MAX_PARTY_FIELDS)


def clean_hidden(keys: list[str] | None) -> list[str]:
    unknown = sorted({str(key) for key in keys or []} - HIDEABLE_KEYS)
    if unknown:
        raise BillError(f"Cannot hide '{unknown[0]}' on a bill.")
    return sorted({str(key) for key in keys or []})


def compute_bill(
    lines: list[dict[str, Any]],
    rates: dict[str, Any] | None = None,
    extra_charges: list[dict[str, Any]] | None = None,
    line_setup: dict[str, Any] | None = None,
    service_month: date | None = None,
    manual_figures: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Every figure on the bill, from its lines, percentages and extra charges. ``service_month`` gives a monthly rate its
    number of days (unless the layout names them); without it a month has 30.

    EPFO, ESIC and service charges are percentages of the lines that are not left out of them. Any of EPFO, ESIC, service
    charges, CGST and SGST can instead be entered (``manual_figures``): that figure is used as it is, what follows is worked out
    from it, and ``manual_figures`` in the result keeps it with the figure the calculation would have given. Nothing is refused
    for not matching: the editor warns, the bill is saved as entered."""
    setup = clean_line_setup(line_setup)
    rows = clean_lines(lines, setup, setup["month_days"] or days_in_month(service_month))
    pct = clean_rates(rates)
    extras = clean_extra_charges(extra_charges)
    entered = clean_manual_figures(manual_figures)
    lines_total = sum((row["amount"] for row in rows), Decimal("0"))
    base = {key: sum((row["amount"] for row in rows if key not in row.get("skip", ())), Decimal("0")) for key in SKIP_KEYS}
    auto = {
        "epf_amount": _pct_of(base["epf"], pct["epf_pct"]),
        "esic_amount": _pct_of(base["esic"], pct["esic_pct"]),
    }
    epf = entered.get("epf_amount", auto["epf_amount"])
    esic = entered.get("esic_amount", auto["esic_amount"])
    # The service charge is of the lines that are part of it, and, if the bill says so, of the EPFO and ESIC as well (as they stand).
    auto["service_amount"] = _pct_of(base["service"] + (epf + esic if setup["service_on"] == "lines_epf_esic" else Decimal("0")), pct["service_pct"])
    service = entered.get("service_amount", auto["service_amount"])
    sub_total = lines_total + epf + esic
    for charge in extras:
        charge["amount"] = _pct_of(lines_total, charge["value"]) if charge["kind"] == "pct" else charge["value"]
    taxable = sub_total + service + sum((charge["amount"] for charge in extras), Decimal("0"))
    auto["cgst_amount"] = _pct_of(taxable, pct["cgst_pct"])
    auto["sgst_amount"] = _pct_of(taxable, pct["sgst_pct"])
    cgst = entered.get("cgst_amount", auto["cgst_amount"])
    sgst = entered.get("sgst_amount", auto["sgst_amount"])
    exact = taxable + cgst + sgst
    grand = exact.quantize(RUPEE, rounding=ROUND_HALF_UP)
    return {
        "lines": rows,
        "line_setup": setup,
        "rates": pct,
        "extra_charges": extras,
        "manual_figures": {key: {"value": value, "auto": auto[key]} for key, value in entered.items()},
        "lines_total": lines_total,
        "epf_amount": epf,
        "esic_amount": esic,
        "sub_total": sub_total,
        "service_amount": service,
        "taxable_total": taxable,
        "cgst_amount": cgst,
        "sgst_amount": sgst,
        "round_off": grand - exact,
        "grand_total": grand,
    }


# --------------------------------------------------------------------------- serialising


def _plain(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, date):
        return value.isoformat()
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def _row(cur, row) -> dict[str, Any]:
    return {col.name: _plain(value) for col, value in zip(cur.description, row)}


# The printed figures. The same names are columns of orion_ods.bill and keys of compute_bill().
MONEY_COLUMNS = (
    "lines_total", "epf_amount", "esic_amount", "sub_total", "service_amount",
    "taxable_total", "cgst_amount", "sgst_amount", "round_off", "grand_total",
)
JSON_COLUMNS = ("lines", "rates", "extra_charges", "hidden", "header_fields", "party_fields", "line_setup", "manual_figures", "profile_overrides")

BILL_FROM = """
    orion_ods.bill b
    LEFT JOIN orion_ods.case cs ON cs.case_code = b.case_code
    LEFT JOIN orion_ods.client cl ON cl.client_code = b.client_code
"""

LIST_COLUMNS = """
    b.bill_code AS id, b.bill_number, b.fy_start_year, b.bill_seq, b.bill_date, b.service_month,
    b.case_code, cs.case_name, b.client_code, cl.client_name, b.legacy_client_ledger,
    b.party_name, b.party_gstin, b.location, b.ref_no, b.taxable_total, b.cgst_amount,
    b.sgst_amount, b.round_off, b.grand_total, b.status, b.gst_paid, b.gst_paid_amount, b.version_no,
    b.epf_amount, b.esic_amount, b.epf_paid_amount, b.esic_paid_amount,
    b.credited_amount, b.created_timestamp,
    COALESCE((
        SELECT SUM(t.amount_after_tax_gst)
          FROM orion_ods.case_transaction t
         WHERE t.bill_code = b.bill_code AND t.transaction_status = 'Committed'
    ), 0) AS received_total
"""


# --------------------------------------------------------------------------- profile


# The company's own typeface and size for its bills. They are kept in the profile but are not part of the copy each bill
# takes of it: a bill follows the company's setting until it is given a choice of its own.
COMPANY_FONT_KEYS = ("font_family", "font_size")


def get_profile() -> dict[str, Any]:
    with db_cursor() as cur:
        cur.execute("SELECT profile FROM orion_ods.bill_profile WHERE id = 1")
        row = cur.fetchone()
    stored = row[0] if row else {}
    family, size = bill_fonts.company_font(stored)
    return {**DEFAULT_PROFILE, **stored, "font_family": family, "font_size": size}


def save_profile(profile: dict[str, Any], user_id: int | None) -> dict[str, Any]:
    clean: dict[str, Any] = {}
    for key, default in DEFAULT_PROFILE.items():
        value = profile.get(key, default)
        if key == "terms":
            if not isinstance(value, list):
                raise BillError("Terms must be a list of lines.")
            clean[key] = [str(item).strip()[:PROFILE_TEXT_LIMIT] for item in value if str(item).strip()][:8]
        else:
            clean[key] = str(value or "").strip()[:PROFILE_TEXT_LIMIT]
    if not clean["company_name"]:
        raise BillError("The company name cannot be empty.")
    current = bill_fonts.company_font(get_profile())  # a profile sent without them keeps the company's setting
    try:
        clean["font_family"] = bill_fonts.clean_family(profile.get("font_family", current[0]))
        clean["font_size"] = bill_fonts.clean_size(profile.get("font_size", current[1]))
    except bill_fonts.FontError as error:
        raise BillError(str(error)) from None
    with db_cursor(commit=True) as cur:
        cur.execute(
            """
            INSERT INTO orion_ods.bill_profile (id, profile, updated_by)
            VALUES (1, %s::jsonb, %s)
            ON CONFLICT (id) DO UPDATE
               SET profile = EXCLUDED.profile, updated_by = EXCLUDED.updated_by,
                   updated_timestamp = CURRENT_TIMESTAMP
            """,
            (json.dumps(clean), user_id),
        )
    return clean


# --------------------------------------------------------------------------- cases


def list_cases() -> list[dict[str, Any]]:
    """Every case with its client and the client's billing details, plus what was used on the
    last issued bill so a repeat bill starts filled in: the lines from the case's last bill,
    and the party details from the client's last bill where the client record has none.

    A client that belongs to a group also carries ``group``: the group client's own billing
    details, for a bill that is addressed to the group instead of the client. The bill is still
    raised for the case's client (receivables and the warehouse follow that); only the party
    printed on it changes."""
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT cs.case_code, cs.case_name, cs.case_status,
                   cl.client_code, cl.client_name,
                   NULLIF(BTRIM(cl.billing_name), '') AS billing_name,
                   NULLIF(BTRIM(cl.gstin), '') AS gstin,
                   NULLIF(BTRIM(cl.billing_address), '') AS billing_address,
                   NULLIF(BTRIM(cl.client_location_state), '') AS state,
                   g.client_code AS group_code, g.client_name AS group_name,
                   NULLIF(BTRIM(g.billing_name), '') AS group_billing_name,
                   NULLIF(BTRIM(g.gstin), '') AS group_gstin,
                   NULLIF(BTRIM(g.billing_address), '') AS group_billing_address,
                   NULLIF(BTRIM(g.client_location_state), '') AS group_state,
                   NULLIF(BTRIM(op.tender_id), '') AS tender_id, op.opportunity_start_date AS tender_start_date
              FROM orion_ods.case cs
              LEFT JOIN LATERAL (
                  SELECT o.tender_id, o.opportunity_start_date
                    FROM orion_ods.opportunity o
                   WHERE o.opportunity_code = cs.opportunity_code OR o.opportunity_case_code = cs.case_code
                   ORDER BY (o.opportunity_code = cs.opportunity_code) DESC, o.opportunity_code
                   LIMIT 1
              ) op ON TRUE
              LEFT JOIN orion_ods.client cl ON cl.client_code = cs.client_code
              LEFT JOIN orion_ods.client g ON g.client_code = cl.client_group_code
             ORDER BY cs.case_name, cs.case_code
            """
        )
        cases = [_row(cur, row) for row in cur.fetchall()]
        cur.execute(
            """
            SELECT DISTINCT ON (case_code)
                   case_code, location, service_description, lines, rates, extra_charges, hidden,
                   header_fields, line_setup, tender_id, tender_start_date, profile_overrides, bill_number, bill_date
              FROM orion_ods.bill
             WHERE status = 'Issued' AND case_code IS NOT NULL
             ORDER BY case_code, created_timestamp DESC
            """
        )
        last_for_case = {row[0]: _row(cur, row) for row in cur.fetchall()}
        cur.execute(
            """
            SELECT DISTINCT ON (client_code)
                   client_code, party_name, party_gstin, party_address, party_state, party_fields
              FROM orion_ods.bill
             WHERE status = 'Issued' AND client_code IS NOT NULL
             ORDER BY client_code, created_timestamp DESC
            """
        )
        last_for_client = {row[0]: _row(cur, row) for row in cur.fetchall()}
    for case in cases:
        case["last"] = last_for_case.get(case["case_code"])
        case["last_party"] = last_for_client.get(case["client_code"])
        group_code = case.pop("group_code")
        group = {
            "client_code": group_code,
            "client_name": case.pop("group_name"),
            "billing_name": case.pop("group_billing_name"),
            "gstin": case.pop("group_gstin"),
            "billing_address": case.pop("group_billing_address"),
            "state": case.pop("group_state"),
            "last_party": last_for_client.get(group_code),
        }
        case["group"] = group if group_code else None
    return cases


# --------------------------------------------------------------------------- bills


def next_number(day: date) -> dict[str, Any]:
    """The number the next bill dated ``day`` would get. Only a preview: it is assigned on save."""
    year = fy_start_year(day)
    with db_cursor() as cur:
        cur.execute("SELECT last_no FROM orion_ods.bill_counter WHERE fy_start_year = %s", (year,))
        row = cur.fetchone()
    seq = (row[0] if row else 0) + 1
    return {"fy": fy_label(year), "seq": seq, "bill_number": bill_number(year, seq)}


def _month_start(value: str) -> date:
    try:
        year, month = (int(part) for part in str(value).split("-")[:2])
        return date(year, month, 1)
    except (ValueError, TypeError):
        raise BillError("Choose the month the bill is for.") from None


def _gstin(value: Any) -> str | None:
    text = "".join(str(value or "").split()).upper()
    if not text:
        return None
    if not _GSTIN.match(text):
        raise BillError("A GSTIN is 15 letters and digits, for example 23ABCDE1234F1Z5.")
    return text


def _text(value: Any, limit: int) -> str | None:
    text = " ".join(str(value or "").split())
    return text[:limit] or None


def _clean_bill(cur, data: dict[str, Any]) -> dict[str, Any]:
    """Validate what the user entered and work out the figures. Keys are orion_ods.bill columns."""
    bill_date = data.get("bill_date")
    if not isinstance(bill_date, date):
        raise BillError("Choose the bill date.")
    service_month = _month_start(data.get("service_month"))
    case_code = _text(data.get("case_code"), 40)
    if not case_code:
        raise BillError("Choose the case.")
    cur.execute("SELECT client_code FROM orion_ods.case WHERE case_code = %s", (case_code,))
    case = cur.fetchone()
    if not case:
        raise BillError("That case does not exist.")
    if not case[0]:
        raise BillError("That case has no client. Set the client on the case first.")
    party = _text(data.get("party_name"), 300)
    if not party:
        raise BillError("The bill needs a party name.")
    gstin = _gstin(data.get("party_gstin"))
    figures = compute_bill(data.get("lines") or [], data.get("rates"), data.get("extra_charges"), data.get("line_setup"), service_month,
                           data.get("manual_figures"))
    tender_start = data.get("tender_start_date")
    if tender_start is not None and not isinstance(tender_start, date):
        raise BillError("Choose the tender start date.")
    return {
        "bill_date": bill_date,
        "service_month": service_month,
        "case_code": case_code,
        "client_code": case[0],
        "party_name": party,
        "party_gstin": gstin,
        "party_address": _text(data.get("party_address"), 400),
        "party_state": _text(data.get("party_state"), 80),
        "ref_no": _text(data.get("ref_no"), 120),
        "ref_date": data.get("ref_date"),
        "tender_id": _text(data.get("tender_id"), 80),
        "tender_start_date": tender_start,
        "location": _text(data.get("location"), 300),
        "service_description": _text(data.get("service_description"), 200),
        "lines": json.dumps([{k: _plain(v) for k, v in row.items()} for row in figures["lines"]]),
        "rates": json.dumps({k: _plain(v) for k, v in figures["rates"].items()}),
        "extra_charges": json.dumps([{k: _plain(v) for k, v in row.items()} for row in figures["extra_charges"]]),
        "hidden": json.dumps(clean_hidden(data.get("hidden"))),
        "header_fields": json.dumps(clean_header_fields(data.get("header_fields"))),
        "party_fields": json.dumps(clean_party_fields(data.get("party_fields"))),
        "line_setup": json.dumps(figures["line_setup"]),
        "manual_figures": json.dumps({key: {k: _plain(v) for k, v in item.items()} for key, item in figures["manual_figures"].items()}),
        **{column: figures[column] for column in MONEY_COLUMNS},
    }


def clean_profile_fields(fields: dict[str, Any] | None) -> dict[str, Any]:
    """The template details a bill is given its own version of (PROFILE_BILL_KEYS), cleaned the way the template is."""
    out: dict[str, Any] = {}
    for key, value in (fields or {}).items():
        if key not in PROFILE_BILL_KEYS:
            raise BillError(f"'{key}' is not a detail a bill can have of its own.")
        if key == "terms":
            if not isinstance(value, list):
                raise BillError("Terms must be a list of lines.")
            out[key] = [str(item).strip()[:PROFILE_TEXT_LIMIT] for item in value if str(item).strip()][:8]
        else:
            out[key] = str(value or "").strip()[:PROFILE_TEXT_LIMIT]
    if "company_name" in out and not out["company_name"]:
        raise BillError("The company name cannot be empty.")
    return out


def apply_profile_edits(
    snapshot: dict[str, Any], overrides: dict[str, Any], template: dict[str, Any], submitted: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """The profile a bill keeps and the list of what is its own. ``snapshot`` is what the bill printed so far, ``overrides`` what
    already differed from the template, ``template`` today's template and ``submitted`` the cleaned values the person sent. A value
    that changes what the bill prints is applied; it counts as the bill's own unless it is the template's. A value that is not
    changed leaves the bill as it was, so a template changed since the bill was issued is not mistaken for an edit."""
    profile, own = dict(snapshot), dict(overrides)
    for key, value in submitted.items():
        if value == snapshot.get(key):
            continue
        profile[key] = value
        if value == template.get(key):
            own.pop(key, None)
        else:
            own[key] = value
    return profile, own


def _placeholder(column: str) -> str:
    return "%s::jsonb" if column in JSON_COLUMNS or column == "profile" else "%s"


def profile_snapshot(stored: dict[str, Any]) -> dict[str, Any]:
    """The copy of the company's profile that a bill keeps. It leaves out the company's typeface and size, which a bill
    follows live (``bill_fonts.effective``) unless it has a choice of its own."""
    return {**DEFAULT_PROFILE, **{key: value for key, value in stored.items() if key not in COMPANY_FONT_KEYS}}


def _own_font(data: dict[str, Any]) -> dict[str, Any]:
    """The typeface and size a bill is given of its own (empty: it follows the company's setting)."""
    try:
        return {"font_family": bill_fonts.clean_family(data.get("font_family"), allow_empty=True),
                "font_size": bill_fonts.clean_size(data.get("font_size"), allow_empty=True)}
    except bill_fonts.FontError as error:
        raise BillError(str(error)) from None


def _insert_bill(cur, data: dict[str, Any], user_id: int | None) -> str:
    """Validate, number and store one bill using ``cur``. The caller owns the transaction."""
    values = _clean_bill(cur, data)
    year = fy_start_year(values["bill_date"])

    # The counter row is locked until the transaction ends, so two people saving at once
    # get different numbers, and a failed save gives its number back.
    cur.execute(
        """
        INSERT INTO orion_ods.bill_counter (fy_start_year, last_no)
        VALUES (%s, 1)
        ON CONFLICT (fy_start_year)
        DO UPDATE SET last_no = orion_ods.bill_counter.last_no + 1
        RETURNING last_no
        """,
        (year,),
    )
    seq = cur.fetchone()[0]
    cur.execute("SELECT profile FROM orion_ods.bill_profile WHERE id = 1")
    stored = cur.fetchone()
    template = profile_snapshot(stored[0] if stored else {})
    profile, own = apply_profile_edits(template, {}, template, clean_profile_fields(data.get("profile_fields")))
    values.update(
        bill_number=bill_number(year, seq),
        fy_start_year=year,
        bill_seq=seq,
        profile=json.dumps(profile),
        profile_overrides=json.dumps(own),
        **_own_font(data),
        created_by=user_id,
        version_by=user_id,
    )
    columns = list(values)
    cur.execute(
        f"""
        INSERT INTO orion_ods.bill ({', '.join(columns)})
        VALUES ({', '.join(_placeholder(column) for column in columns)})
        RETURNING bill_code
        """,
        [values[column] for column in columns],
    )
    bill_code = cur.fetchone()[0]
    _sync_revenue(cur, _bill_row(cur, bill_code), user_id)
    return bill_code


# --------------------------------------------------------------------------- revenue entries
#
# A bill's money is tracked in orion_ods.case_transaction, the revenue table the dashboards
# read. An issued bill has at most one Prospective entry, for what is still to be received,
# and one Committed entry for each payment recorded against it. Together they always add
# up to the bill's grand total. The entries are written only here: the generic Transaction
# form treats a row that has a bill_code as read-only (entities.locked_reason).
#
# An entry carries the bill's figures: transaction_amount is the taxable value, gst is
# CGST + SGST, and amount_after_tax_gst is the grand total, so it can differ from
# amount + gst by the bill's round-off. transaction_date is the bill date; received_date
# is set on a Committed entry.

ZERO = Decimal("0")


def _inr(value: Decimal) -> str:
    return f"\u20b9{value:,.2f}"


def _bill_row(cur, bill_code: str, *, lock: bool = False) -> dict[str, Any] | None:
    cur.execute(
        f"SELECT * FROM orion_ods.bill WHERE bill_code = %s{' FOR UPDATE' if lock else ''}",
        (bill_code,),
    )
    row = cur.fetchone()
    return {col.name: value for col, value in zip(cur.description, row)} if row else None


def _revenue_entries(cur, bill_code: str, *, lock: bool = False) -> list[dict[str, Any]]:
    cur.execute(
        f"""
        SELECT transaction_code, case_code, transaction_status AS status, transaction_date,
               received_date, COALESCE(transaction_amount, 0) AS taxable, COALESCE(gst, 0) AS gst,
               COALESCE(amount_after_tax_gst, 0) AS total
          FROM orion_ods.case_transaction
         WHERE bill_code = %s
         ORDER BY created_timestamp, transaction_code
        {'FOR UPDATE' if lock else ''}
        """,
        (bill_code,),
    )
    return [{col.name: value for col, value in zip(cur.description, row)} for row in cur.fetchall()]


def split_payment(open_entry: dict[str, Decimal], amount: Decimal) -> tuple[dict[str, Decimal], dict[str, Decimal]]:
    """Divide the open entry into the part just received and the part still open.

    The taxable value and the GST are shared in the same proportion as the money, and the
    two parts always add back to the entry they came from.
    """
    ratio = amount / open_entry["total"]
    received = {
        "taxable": _paisa(open_entry["taxable"] * ratio),
        "gst": _paisa(open_entry["gst"] * ratio),
        "total": amount,
    }
    remaining = {key: open_entry[key] - received[key] for key in ("taxable", "gst", "total")}
    return received, remaining


def _sync_revenue(cur, bill: dict[str, Any], user_id: int | None = None) -> None:
    """Make the bill's open revenue entry match the bill. Call after every change to a bill."""
    entries = _revenue_entries(cur, bill["bill_code"], lock=True)
    received = [entry for entry in entries if entry["status"] == "Committed"]
    open_entry = next((entry for entry in entries if entry["status"] == "Prospective"), None)

    if bill["status"] == "Cancelled":
        if open_entry:
            cur.execute(
                """
                UPDATE orion_ods.case_transaction
                   SET transaction_status = 'Cancelled', last_updated_timestamp = CURRENT_TIMESTAMP,
                    last_updated_by = %s
                 WHERE transaction_code = %s
                """,
                (user_id, open_entry["transaction_code"]),
            )
        return
    if not bill["case_code"]:
        # Raised before bills were tagged to cases. Its revenue starts when it is tagged.
        return

    got = sum((entry["total"] for entry in received), ZERO)
    credited = bill.get("credited_amount") or ZERO  # approved credit notes: what a client no longer owes, never received
    if received and any(entry["case_code"] != bill["case_code"] for entry in received):
        raise BillError(
            f"{_inr(got)} has been received against this bill for its current case, so the case cannot be changed."
        )
    left = bill["grand_total"] - credited - got
    if left < 0:
        raise BillError(
            f"{_inr(got)} has already been received against this bill"
            + (f" and {_inr(credited)} credited" if credited else "")
            + ". Its total cannot go below that."
        )
    if left == 0:
        if open_entry:
            cur.execute(
                "DELETE FROM orion_ods.case_transaction WHERE transaction_code = %s",
                (open_entry["transaction_code"],),
            )
        return

    taxable = max(bill["taxable_total"] - (bill.get("credited_taxable") or ZERO) - sum((entry["taxable"] for entry in received), ZERO), ZERO)
    gst = max(
        bill["cgst_amount"] + bill["sgst_amount"] - (bill.get("credited_cgst") or ZERO) - (bill.get("credited_sgst") or ZERO)
        - sum((entry["gst"] for entry in received), ZERO),
        ZERO,
    )
    values = (bill["case_code"], bill["bill_date"], taxable, gst, left, f"Bill {bill['bill_number']}")
    if open_entry:
        cur.execute(
            """
            UPDATE orion_ods.case_transaction
               SET case_code = %s, transaction_date = %s, transaction_amount = %s, tax = 0, gst = %s,
                   amount_after_tax_gst = %s, transaction_description = %s,
                   last_updated_timestamp = CURRENT_TIMESTAMP,
                last_updated_by = %s
             WHERE transaction_code = %s
            """,
            (*values, user_id, open_entry["transaction_code"]),
        )
    else:
        cur.execute(
            """
            INSERT INTO orion_ods.case_transaction (
                case_code, transaction_date, transaction_amount, tax, gst, amount_after_tax_gst,
                transaction_description, transaction_status, bill_code, created_by, last_updated_by
            ) VALUES (%s, %s, %s, 0, %s, %s, %s, 'Prospective', %s, %s, %s)
            """,
            (*values, bill["bill_code"], user_id, user_id),
        )


def _deductions_by_entry(cur, bill_code: str) -> dict[str, list[dict[str, Any]]]:
    """What the client held back on each payment of the bill (the ones not reversed), by the revenue entry the payment made."""
    cur.execute(
        """
        SELECT deduction_id, transaction_code, kind, amount, section, rate, reason, matched_26as_timestamp IS NOT NULL
          FROM orion_ods.bill_payment_deduction
         WHERE bill_code = %s AND reversed_timestamp IS NULL
         ORDER BY deduction_id
        """,
        (bill_code,),
    )
    found: dict[str, list[dict[str, Any]]] = {}
    for deduction_id, code, kind, amount, section, rate, reason, matched in cur.fetchall():
        found.setdefault(code, []).append(
            {"id": deduction_id, "kind": kind, "amount": float(amount), "section": section,
             "rate": float(rate) if rate is not None else None, "reason": reason, "matched_26as": bool(matched)}
        )
    return found


def _gst_due(bill: dict[str, Any]) -> tuple[Decimal, Decimal]:
    """What is due to the government on the bill: its CGST and SGST less what approved credit notes have taken off."""
    return (
        Decimal(str(bill["cgst_amount"] or 0)) - Decimal(str(bill.get("credited_cgst") or 0)),
        Decimal(str(bill["sgst_amount"] or 0)) - Decimal(str(bill.get("credited_sgst") or 0)),
    )


def _revenue_summary(cur, bill_code: str, grand_total: Any, status: str, credited: Any = 0) -> dict[str, Any]:
    """What has been received against a bill and what is still to come, with each entry.

    ``received`` is what has SETTLED the bill: the cash that came in plus what the client held back (``deducted``). An entry's ``amount`` is
    the same, and its ``cash`` is what actually reached the account."""
    entries = _revenue_entries(cur, bill_code)
    received = sum((entry["total"] for entry in entries if entry["status"] == "Committed"), ZERO)
    total = Decimal(str(grand_total)) - Decimal(str(credited or 0))  # what is still to be received is the bill less what has been credited
    held = _deductions_by_entry(cur, bill_code)
    return {
        "received": float(received),
        "credited": float(credited or 0),
        "deducted": float(sum((Decimal(str(d["amount"])) for items in held.values() for d in items), ZERO)),
        "remaining": float(total - received) if status == "Issued" else 0.0,
        "entries": [
            {
                "id": entry["transaction_code"],
                "status": entry["status"],
                "bill_date": _plain(entry["transaction_date"]),
                "received_date": _plain(entry["received_date"]),
                "taxable": float(entry["taxable"]),
                "gst": float(entry["gst"]),
                "amount": float(entry["total"]),
                "cash": float(entry["total"] - sum((Decimal(str(d["amount"])) for d in held.get(entry["transaction_code"], [])), ZERO)),
                "deductions": held.get(entry["transaction_code"], []),
            }
            for entry in entries
        ],
    }


#: What a client may hold back when it pays a bill. TDS is the usual one; the rest need a reason (a penalty and "other") or are tiny (rounding).
DEDUCTION_KINDS = ("TDS", "Penalty", "Rounding", "Other")
MAX_DEDUCTIONS = 6
MAX_ROUNDING = Decimal("10.00")
#: TDS is worked out on the taxable value, never the whole bill, and the highest rate in the Act's table for these services is far below this:
#: more than a fifth of the amount settled is a mistyped figure, not a deduction.
MAX_TDS_SHARE = Decimal("0.20")
#: The sections a manpower or security services company is deducted under, with the rate usually applied (a SUGGESTION: the rate the client used is
#: what is typed; check the current rates with the tax adviser).
TDS_SECTIONS = (
    ("194C", "Contractors, security and manpower services", Decimal("2")),
    ("194J", "Professional or technical fees", Decimal("10")),
    ("194I", "Rent", Decimal("10")),
)
DEFAULT_TDS_SECTION = TDS_SECTIONS[0]
_SECTION = re.compile(r"^[0-9A-Z]{3,8}$")


def clean_deductions(raw: Any) -> list[dict[str, Any]]:
    """What the client held back, checked: a kind from the list, an amount over nothing, a TDS section, and a reason where one is needed."""
    if raw in (None, ""):
        return []
    if not isinstance(raw, list):
        raise BillError("The deductions are not valid.")
    if len(raw) > MAX_DEDUCTIONS:
        raise BillError(f"At most {MAX_DEDUCTIONS} deductions can be recorded with one payment.")
    cleaned: list[dict[str, Any]] = []
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            raise BillError(f"Deduction {index} is not valid.")
        kind = next((k for k in DEDUCTION_KINDS if k.lower() == str(item.get("kind") or "").strip().lower()), None)
        if kind is None:
            raise BillError(f"Deduction {index}: choose what was held back ({', '.join(DEDUCTION_KINDS)}).")
        amount = _paisa(_dec(item.get("amount"), f"The {kind} amount"))
        if amount <= 0:
            raise BillError(f"Deduction {index}: enter the {kind} amount.")
        reason = _text(item.get("reason"), 300)
        section = rate = None
        if kind == "TDS":
            section = re.sub(r"[\s-]", "", str(item.get("section") or "")).upper()
            if not _SECTION.match(section):
                raise BillError(f"Deduction {index}: give the TDS section the client deducted under, for example 194C.")
            if item.get("rate") not in (None, ""):
                rate = _dec(item.get("rate"), "The TDS rate")
                if rate <= 0 or rate > 100:
                    raise BillError(f"Deduction {index}: the TDS rate is a percentage over 0 and up to 100.")
                rate = rate.quantize(Decimal("0.001"))
        elif kind == "Rounding" and amount > MAX_ROUNDING:
            raise BillError(f"Deduction {index}: rounding is at most {_inr(MAX_ROUNDING)}. Use Other, with a reason, for more.")
        if kind in ("Penalty", "Other") and not reason:
            raise BillError(f"Deduction {index}: say why the {kind.lower()} was held back.")
        cleaned.append({"kind": kind, "amount": amount, "section": section, "rate": rate, "reason": reason})
    return cleaned


def apply_credit(cur, bill_code: str, total: Any, user_id: int | None) -> dict[str, Decimal]:
    """Take ``total`` off what a client still owes on a bill, as an approved credit note does: the open revenue entry shrinks (and goes when nothing
    is left), the bill's running credited figures go up, and the GST due on the bill goes down. The caller (``credit_notes``) owns the transaction and
    the credit note's own row. Returns the credited taxable value, CGST and SGST, the parts of ``total`` in the proportions of what was open.

    Refuses, so the whole approval is undone, when the bill is cancelled, has no case, has less than ``total`` still to receive, or has had more GST
    paid to the government than its GST would then come to."""
    credit = _paisa(_dec(total, "The credit"))
    if credit <= 0:
        raise BillError("A credit note is for an amount over nothing.")
    bill = _bill_row(cur, bill_code, lock=True)
    if not bill:
        raise BillError("That bill does not exist.")
    if bill["status"] != "Issued":
        raise BillError("A cancelled bill cannot be credited.")
    if not bill["case_code"]:
        raise BillError("Tag this bill to a case first, by editing it. Revenue is recorded against the case.")
    _sync_revenue(cur, bill, user_id)
    open_entry = next((entry for entry in _revenue_entries(cur, bill_code, lock=True) if entry["status"] == "Prospective"), None)
    if not open_entry:
        raise BillError("Nothing is still to be received on this bill, so there is nothing to credit.")
    if credit > open_entry["total"]:
        raise BillError(f"Only {_inr(open_entry['total'])} is still to be received on this bill, so a credit note cannot be for more.")
    parts, _left = split_payment(open_entry, credit)
    gst_parts = bill["cgst_amount"] + bill["sgst_amount"]
    cgst = _paisa(parts["gst"] * bill["cgst_amount"] / gst_parts) if gst_parts > 0 else ZERO
    sgst = parts["gst"] - cgst
    cur.execute(
        """
        UPDATE orion_ods.bill
           SET credited_taxable = credited_taxable + %s, credited_cgst = credited_cgst + %s, credited_sgst = credited_sgst + %s,
               credited_amount = credited_amount + %s, last_updated_timestamp = CURRENT_TIMESTAMP
         WHERE bill_code = %s
        """,
        (parts["taxable"], cgst, sgst, credit, bill_code),
    )
    edited = _bill_row(cur, bill_code)
    _sync_revenue(cur, edited, user_id)
    _sync_gst(cur, edited)  # refuses a credit that takes the GST below what has been paid
    return {"taxable": parts["taxable"], "cgst": cgst, "sgst": sgst, "total": credit}


def unapply_credit(cur, bill_code: str, parts: dict[str, Any], user_id: int | None) -> None:
    """Take a credit note back off the bill (an admin reversing it): what it credited is owed again, as an open entry, and the GST due goes back up."""
    bill = _bill_row(cur, bill_code, lock=True)
    if not bill:
        raise BillError("That bill does not exist.")
    cur.execute(
        """
        UPDATE orion_ods.bill
           SET credited_taxable = credited_taxable - %s, credited_cgst = credited_cgst - %s, credited_sgst = credited_sgst - %s,
               credited_amount = credited_amount - %s, last_updated_timestamp = CURRENT_TIMESTAMP
         WHERE bill_code = %s
        """,
        (parts["taxable"], parts["cgst"], parts["sgst"], parts["total"], bill_code),
    )
    edited = _bill_row(cur, bill_code)
    if edited["status"] == "Issued":
        _sync_revenue(cur, edited, user_id)
        _sync_gst(cur, edited)


def list_money_accounts() -> list[dict[str, Any]]:
    """The accounts a payment can go into or come out of, for the payment forms: name and kind only (no balance: that is for the Bank pages)."""
    with db_cursor() as cur:
        cur.execute("SELECT account_id, account_name, account_kind FROM orion_ods.bank_account ORDER BY account_id")
        return [{"account_id": a, "account_name": n, "account_kind": k} for a, n, k in cur.fetchall()]


def _checked_account(cur, account_id: Any) -> int | None:
    """The account a payment went into or came out of, or None for the default account. An account that does not exist is refused."""
    if account_id in (None, ""):
        return None
    try:
        number = int(account_id)
    except (TypeError, ValueError):
        raise BillError("That account is not valid.") from None
    cur.execute("SELECT 1 FROM orion_ods.bank_account WHERE account_id = %s", (number,))
    if not cur.fetchone():
        raise BillError("That account does not exist.")
    return number


def record_payment(
    bill_code: str, amount: Any, received_date: Any, user_id: int | None, idem: Idempotency | None = None, account_id: Any = None,
    deductions: Any = None,
) -> dict[str, Any]:
    """Record money received against a bill, and anything the client held back from it (``deductions``: TDS, a penalty, rounding).

    ``amount`` is the CASH that came in. The bill is settled by the cash plus the deductions, so a bill paid net of TDS closes, and the revenue
    entry holds that whole amount (the entries still add up to the bill's total); the bank sees only the cash (the view ``bank_movement``).

    Receiving everything that is still open turns the open entry into a Committed one.
    Receiving part of it splits the entry: a new Committed entry for the money that came in,
    and the open entry shrinks to what is left.

    With ``idem`` the same request arriving again (a double-click, a retry) is answered with the first one's result and records
    nothing: a repeated PARTIAL payment would otherwise be recorded twice.
    """
    paid = _paisa(_dec(amount, "Amount received"))
    if paid <= 0:
        raise BillError("Enter the amount received.")
    if not isinstance(received_date, date):
        raise BillError("Choose the date the money was received.")
    held = clean_deductions(deductions)
    held_total = sum((item["amount"] for item in held), ZERO)
    settled = paid + held_total  # what this payment takes off the bill: the cash and what was held back
    tds_total = sum((item["amount"] for item in held if item["kind"] == "TDS"), ZERO)
    if tds_total > _paisa(settled * MAX_TDS_SHARE):
        raise BillError("The TDS is more than a fifth of what this payment settles. Check the amounts.")
    conn = get_connection()
    cur = conn.cursor()
    try:
        if idem is not None:
            prior = idem.claim(cur)  # in this transaction: the key and the work are saved together or not at all
            if prior is not None:  # the same request again: answer with the first one's result
                conn.rollback()
                return get_bill(prior["bill_code"])
        bill = _bill_row(cur, bill_code, lock=True)
        if not bill:
            raise BillError("That bill does not exist.")
        if bill["status"] != "Issued":
            raise BillError("A cancelled bill cannot receive a payment.")
        account = _checked_account(cur, account_id)
        if not bill["case_code"]:
            raise BillError("Tag this bill to a case first, by editing it. Revenue is recorded against the case.")
        _sync_revenue(cur, bill, user_id)
        open_entry = next(
            (entry for entry in _revenue_entries(cur, bill_code, lock=True) if entry["status"] == "Prospective"),
            None,
        )
        if not open_entry:
            raise BillError("This bill has been received in full.")
        if settled > open_entry["total"]:
            raise BillError(
                f"Only {_inr(open_entry['total'])} is still to be received on this bill."
                + (f" The cash and what was held back come to {_inr(settled)}." if held else "")
            )
        note = f"Bill {bill['bill_number']}, received {received_date.strftime('%d %b %Y')}"
        if held:
            note += " (" + ", ".join(f"{item['kind']} {_inr(item['amount'])} held back" for item in held) + ")"
        if settled == open_entry["total"]:
            entry_code = open_entry["transaction_code"]
            cur.execute(
                """
                UPDATE orion_ods.case_transaction
                   SET transaction_status = 'Committed', received_date = %s, transaction_description = %s, account_id = %s,
                       last_updated_timestamp = CURRENT_TIMESTAMP,
                    last_updated_by = %s
                 WHERE transaction_code = %s
                """,
                (received_date, note, account, user_id, open_entry["transaction_code"]),
            )
        else:
            received, remaining = split_payment(open_entry, settled)
            cur.execute(
                """
                UPDATE orion_ods.case_transaction
                   SET transaction_amount = %s, gst = %s, amount_after_tax_gst = %s,
                       last_updated_timestamp = CURRENT_TIMESTAMP,
                    last_updated_by = %s
                 WHERE transaction_code = %s
                """,
                (remaining["taxable"], remaining["gst"], remaining["total"], user_id, open_entry["transaction_code"]),
            )
            cur.execute(
                """
                INSERT INTO orion_ods.case_transaction (
                    case_code, transaction_date, received_date, transaction_amount, tax, gst,
                    amount_after_tax_gst, transaction_description, transaction_status, bill_code,
                    created_by, last_updated_by, account_id
                ) VALUES (%s, %s, %s, %s, 0, %s, %s, %s, 'Committed', %s, %s, %s, %s)
                RETURNING transaction_code
                """,
                (
                    bill["case_code"], bill["bill_date"], received_date, received["taxable"], received["gst"],
                    received["total"], note, bill_code, user_id, user_id, account,
                ),
            )
            entry_code = cur.fetchone()[0]
        for item in held:
            cur.execute(
                """
                INSERT INTO orion_ods.bill_payment_deduction (
                    bill_code, transaction_code, kind, amount, section, rate, reason, received_date, fy_start_year, recorded_by
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (bill_code, entry_code, item["kind"], item["amount"], item["section"], item["rate"], item["reason"],
                 received_date, fy_start_year(received_date), user_id),
            )
        if idem is not None:
            idem.remember(cur, {"bill_code": bill_code})
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()
    return get_bill(bill_code)


def reverse_payment(bill_code: str, transaction_code: str, user_id: int | None) -> dict[str, Any]:
    """Undo a payment recorded by mistake: its amount goes back to being still to receive."""
    conn = get_connection()
    cur = conn.cursor()
    try:
        bill = _bill_row(cur, bill_code, lock=True)
        if not bill:
            raise BillError("That bill does not exist.")
        entries = _revenue_entries(cur, bill_code, lock=True)
        payment = next(
            (e for e in entries if e["transaction_code"] == transaction_code and e["status"] == "Committed"),
            None,
        )
        if not payment:
            raise BillError("That payment is not recorded against this bill.")
        # What the client held back goes with the payment. The rows stay, marked reversed (nothing is deleted).
        cur.execute(
            """
            UPDATE orion_ods.bill_payment_deduction
               SET reversed_by = %s, reversed_timestamp = CURRENT_TIMESTAMP, reversal_reason = 'The payment it came with was reversed'
             WHERE transaction_code = %s AND reversed_timestamp IS NULL
            """,
            (user_id, transaction_code),
        )
        open_entry = next((entry for entry in entries if entry["status"] == "Prospective"), None)
        if open_entry:
            cur.execute(
                """
                UPDATE orion_ods.case_transaction
                   SET transaction_amount = %s, gst = %s, amount_after_tax_gst = %s,
                       last_updated_timestamp = CURRENT_TIMESTAMP,
                    last_updated_by = %s
                 WHERE transaction_code = %s
                """,
                (
                    open_entry["taxable"] + payment["taxable"], open_entry["gst"] + payment["gst"],
                    open_entry["total"] + payment["total"], user_id, open_entry["transaction_code"],
                ),
            )
            cur.execute("DELETE FROM orion_ods.case_transaction WHERE transaction_code = %s", (transaction_code,))
        else:
            cur.execute(
                """
                UPDATE orion_ods.case_transaction
                   SET transaction_status = 'Prospective', received_date = NULL, transaction_description = %s,
                       last_updated_timestamp = CURRENT_TIMESTAMP,
                    last_updated_by = %s
                 WHERE transaction_code = %s
                """,
                (f"Bill {bill['bill_number']}", user_id, transaction_code),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()
    return get_bill(bill_code)


def create_bill(data: dict[str, Any], user_id: int | None, idem: Idempotency | None = None) -> dict[str, Any]:
    """Issue a bill. With ``idem`` the same request arriving again is answered with the bill the first one made: a second
    request would otherwise make a second tax invoice, with a second legal number."""
    conn = get_connection()
    cur = conn.cursor()
    try:
        if idem is not None:
            prior = idem.claim(cur)  # in this transaction: the key and the work are saved together or not at all
            if prior is not None:  # the same request again: answer with the first one's result
                conn.rollback()
                return get_bill(prior["bill_code"])
        bill_code = _insert_bill(cur, data, user_id)
        if idem is not None:
            idem.remember(cur, {"bill_code": bill_code})
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()
    return get_bill(bill_code)


def _differs(current: dict[str, Any], values: dict[str, Any]) -> bool:
    """Whether an edit changes anything that is stored. ``values`` comes from _clean_bill."""
    for column, new in values.items():
        if column in JSON_COLUMNS or column == "profile":
            new = json.loads(new)
        if current.get(column) != new:
            return True
    return False


def update_bill(bill_code: str, data: dict[str, Any], reason: str, user_id: int | None, idem: Idempotency | None = None) -> dict[str, Any]:
    """Replace an issued bill with an edited version. The bill keeps its number; the version
    being replaced is copied to orion_ods.bill_version first, in the same transaction. With ``idem`` a repeat of the same save is
    answered with success instead of "Nothing on the bill was changed"."""
    why = _text(reason, 300)
    if not why:
        raise BillError("Say what was changed and why.")
    conn = get_connection()
    cur = conn.cursor()
    try:
        if idem is not None:
            prior = idem.claim(cur)  # in this transaction: the key and the work are saved together or not at all
            if prior is not None:  # the same request again: answer with the first one's result
                conn.rollback()
                return get_bill(prior["bill_code"])
        cur.execute("SELECT * FROM orion_ods.bill WHERE bill_code = %s FOR UPDATE", (bill_code,))
        row = cur.fetchone()
        if not row:
            raise BillError("That bill does not exist.")
        current = {col.name: value for col, value in zip(cur.description, row)}
        if current["status"] != "Issued":
            raise BillError("A cancelled bill cannot be edited.")
        values = _clean_bill(cur, data)
        cur.execute("SELECT profile FROM orion_ods.bill_profile WHERE id = 1")
        stored = cur.fetchone()
        profile, own = apply_profile_edits(
            current.get("profile") or {}, current.get("profile_overrides") or {}, profile_snapshot(stored[0] if stored else {}),
            clean_profile_fields(data.get("profile_fields")),
        )
        values["profile"] = json.dumps(profile)
        values["profile_overrides"] = json.dumps(own)
        if fy_start_year(values["bill_date"]) != current["fy_start_year"]:
            raise BillError(
                f"Bill {current['bill_number']} is numbered in FY {fy_label(current['fy_start_year'])}. "
                "Keep the bill date in that financial year, or cancel this bill and issue a new one."
            )
        if not _differs(current, values):
            raise BillError("Nothing on the bill was changed.")
        for column, credited in (("taxable_total", "credited_taxable"), ("cgst_amount", "credited_cgst"), ("sgst_amount", "credited_sgst")):
            if current.get(credited) and Decimal(str(values[column])) < current[credited]:
                raise BillError(
                    f"{_inr(current[credited])} of this bill's {column.split('_')[0].upper()} has been credited by a credit note, so it cannot go below that. "
                    "An admin can reverse the credit note first."
                )
        cur.execute(
            """
            INSERT INTO orion_ods.bill_version (bill_code, version_no, snapshot, replaced_by)
            SELECT b.bill_code, b.version_no, to_jsonb(b), %s
              FROM orion_ods.bill b
             WHERE b.bill_code = %s
            """,
            (user_id, bill_code),
        )
        columns = list(values)
        cur.execute(
            f"""
            UPDATE orion_ods.bill
               SET {', '.join(f'{column} = {_placeholder(column)}' for column in columns)},
                   version_no = version_no + 1, version_reason = %s, version_by = %s,
                   version_timestamp = CURRENT_TIMESTAMP, last_updated_timestamp = CURRENT_TIMESTAMP
             WHERE bill_code = %s
            """,
            [*(values[column] for column in columns), why, user_id, bill_code],
        )
        edited = _bill_row(cur, bill_code)
        _sync_revenue(cur, edited, user_id)
        _sync_gst(cur, edited)  # refuses an edit that takes the GST below what has been paid
        _sync_statutory(cur, edited)  # and one that takes EPFO or ESIC below what has been paid
        if idem is not None:
            idem.remember(cur, {"bill_code": bill_code})
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()
    return get_bill(bill_code)


def set_bill_font(bill_code: str, family: Any, size: Any) -> dict[str, Any]:
    """Give a bill its own typeface and size, or (both empty) let it follow the company's setting again. This is how the
    bill looks, not what it says, so it does not make a new version and a cancelled bill may have it too."""
    values = _own_font({"font_family": family, "font_size": size})
    with db_cursor(commit=True) as cur:
        cur.execute(
            "UPDATE orion_ods.bill SET font_family = %s, font_size = %s, last_updated_timestamp = CURRENT_TIMESTAMP WHERE bill_code = %s",
            (values["font_family"], values["font_size"], bill_code),
        )
        if cur.rowcount == 0:
            raise BillError("That bill does not exist.")
    bill = get_bill(bill_code)
    assert bill is not None
    return bill


def get_bill(bill_code: str) -> dict[str, Any] | None:
    with db_cursor() as cur:
        cur.execute(
            f"""
            SELECT b.*, cs.case_name, cl.client_name, vu.display_name AS version_by_name, gu.display_name AS gst_paid_by_name
              FROM {BILL_FROM}
              LEFT JOIN orion_ods.app_user vu ON vu.id = b.version_by
              LEFT JOIN orion_ods.app_user gu ON gu.id = b.gst_paid_by
             WHERE b.bill_code = %s
            """,
            (bill_code,),
        )
        row = cur.fetchone()
        if not row:
            return None
        bill = _row(cur, row)
        bill["revenue"] = _revenue_summary(cur, bill_code, bill["grand_total"], bill["status"], bill.get("credited_amount"))
        cur.execute("SELECT profile FROM orion_ods.bill_profile WHERE id = 1")
        company = cur.fetchone()
        bill["font"] = bill_fonts.effective(bill, company[0] if company else None)  # what it is drawn in, wherever it is drawn
        payments = _gst_payment_rows(cur, bill_code)
        bill["gst"] = {**gst_summary(*_gst_due(bill), payments), "payments": gst_batches(payments)}
        dues = _statutory_payment_rows(cur, bill_code)
        bill["statutory"] = {**statutory_summary(*_statutory_due(bill), dues), "payments": statutory_batches(dues)}
    bill["id"] = bill["bill_code"]
    bill["is_current"] = True
    bill["current_version_no"] = bill["version_no"]
    return bill


def list_versions(bill_code: str) -> list[dict[str, Any]]:
    """Every version of a bill, newest first. The current one is the bill row itself."""
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT b.version_no, b.version_timestamp AS saved_timestamp, b.version_reason AS reason,
                   u.display_name AS saved_by, b.grand_total, TRUE AS is_current
              FROM orion_ods.bill b
              LEFT JOIN orion_ods.app_user u ON u.id = b.version_by
             WHERE b.bill_code = %s
            UNION ALL
            SELECT v.version_no, (v.snapshot ->> 'version_timestamp')::timestamptz,
                   v.snapshot ->> 'version_reason', u.display_name,
                   (v.snapshot ->> 'grand_total')::numeric, FALSE
              FROM orion_ods.bill_version v
              LEFT JOIN orion_ods.app_user u ON u.id = (v.snapshot ->> 'version_by')::integer
             WHERE v.bill_code = %s
             ORDER BY version_no DESC
            """,
            (bill_code, bill_code),
        )
        return [_row(cur, row) for row in cur.fetchall()]


def get_version(bill_code: str, version_no: int) -> dict[str, Any] | None:
    """One version of a bill in the same shape as get_bill, so it can be drawn the same way."""
    current = get_bill(bill_code)
    if current is None or version_no == current["version_no"]:
        return current
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT v.snapshot, cs.case_name, cl.client_name, u.display_name
              FROM orion_ods.bill_version v
              LEFT JOIN orion_ods.case cs ON cs.case_code = v.snapshot ->> 'case_code'
              LEFT JOIN orion_ods.client cl ON cl.client_code = v.snapshot ->> 'client_code'
              LEFT JOIN orion_ods.app_user u ON u.id = (v.snapshot ->> 'version_by')::integer
             WHERE v.bill_code = %s AND v.version_no = %s
            """,
            (bill_code, version_no),
        )
        row = cur.fetchone()
    if not row:
        return None
    return {
        **row[0],
        "case_name": row[1],
        "client_name": row[2],
        "version_by_name": row[3],
        "id": bill_code,
        "is_current": False,
        "current_version_no": current["version_no"],
        # how a bill looks is not versioned: an older version is drawn the way the bill is drawn now
        "font": current["font"], "font_family": current["font_family"], "font_size": current["font_size"],
    }


CARD_LINES = 4  # how many lines the hover card lists before saying "and N more"
CARD_PAYMENTS = 3


def payment_status(status: str, grand_total: float, received: float, credited: float = 0) -> str:
    """Where a bill stands with the money, in one word. A cancelled bill is owed nothing. ``received`` is what settled it (cash and what the client
    held back); a bill that is settled only with the help of a credit note is Settled, not Paid."""
    if status == "Cancelled":
        return "Cancelled"
    if received >= grand_total:
        return "Paid"
    if credited > 0 and received + credited >= grand_total:
        return "Settled"
    return "Part paid" if received > 0 else "Unpaid"


def card_from(bill: dict[str, Any], created_by_name: str | None, today: date | None = None) -> dict[str, Any]:
    """What the hover card shows about a bill, from the bill as ``get_bill`` returns it: who, what, how much, what has come in and
    when it was last touched. Nothing here is a second calculation of money: every figure is one the bill already holds."""
    today = today or date.today()
    revenue = bill.get("revenue") or {}
    received = float(revenue.get("received") or 0)
    remaining = float(revenue.get("remaining") or 0)
    paid_in = [entry for entry in revenue.get("entries") or [] if entry.get("status") == "Committed"]
    paid_in.sort(key=lambda entry: str(entry.get("received_date") or ""), reverse=True)
    lines = bill.get("lines") or []
    issued = bill.get("status") == "Issued"
    age = None
    if issued and remaining > 0 and bill.get("bill_date"):
        age = max((today - date.fromisoformat(str(bill["bill_date"])[:10])).days, 0)
    return {
        "id": bill["bill_code"],
        "bill_number": bill["bill_number"],
        "status": bill.get("status"),
        "payment_status": payment_status(str(bill.get("status")), float(bill.get("grand_total") or 0), received, float(revenue.get("credited") or 0)),
        "bill_date": bill.get("bill_date"),
        "service_month": bill.get("service_month"),
        "age_days": age,
        "ref_no": bill.get("ref_no"),
        "ref_date": bill.get("ref_date"),
        "location": bill.get("location"),
        "service_description": bill.get("service_description"),
        "client_code": bill.get("client_code"),
        "client_name": bill.get("client_name") or bill.get("legacy_client_ledger"),
        "case_code": bill.get("case_code"),
        "case_name": bill.get("case_name"),
        "party_name": bill.get("party_name"),
        "party_gstin": bill.get("party_gstin"),
        "party_state": bill.get("party_state"),
        "line_count": len(lines),
        "lines": [
            {"particulars": line.get("particulars"), "qty": line.get("qty"), "rate": line.get("rate"), "days": line.get("days"), "amount": line.get("amount")}
            for line in lines[:CARD_LINES]
        ],
        "figures": {
            "lines_total": bill.get("lines_total"),
            "epf_amount": bill.get("epf_amount"),
            "esic_amount": bill.get("esic_amount"),
            "service_amount": bill.get("service_amount"),
            "extra_charges": [{"label": charge.get("label"), "amount": charge.get("amount")} for charge in bill.get("extra_charges") or []],
            "taxable_total": bill.get("taxable_total"),
            "cgst_amount": bill.get("cgst_amount"),
            "sgst_amount": bill.get("sgst_amount"),
            "round_off": bill.get("round_off"),
            "grand_total": bill.get("grand_total"),
        },
        "payments": {
            "received": received,
            "credited": float(revenue.get("credited") or 0),
            "remaining": remaining,
            "count": len(paid_in),
            "recent": [{"received_date": entry.get("received_date"), "amount": entry.get("amount")} for entry in paid_in[:CARD_PAYMENTS]],
        },
        "statutory": {
            "status": (bill.get("statutory") or {}).get("status"),
            "total": (bill.get("statutory") or {}).get("total"),
            "epfo": (bill.get("statutory") or {}).get("epfo"),
            "esic": (bill.get("statutory") or {}).get("esic"),
        },
        "gst_paid": bool(bill.get("gst_paid")),
        "gst": {
            "status": (bill.get("gst") or {}).get("status"),
            "total": (bill.get("gst") or {}).get("total"),
            "cgst": (bill.get("gst") or {}).get("cgst"),
            "sgst": (bill.get("gst") or {}).get("sgst"),
            "last_paid_date": next((p["paid_date"] for p in (bill.get("gst") or {}).get("payments", []) if not p["reversed"]), None),
        },
        "version_no": bill.get("version_no"),
        "version_reason": bill.get("version_reason"),
        "version_by_name": bill.get("version_by_name"),
        "version_timestamp": bill.get("version_timestamp"),
        "created_by_name": created_by_name,
        "created_timestamp": bill.get("created_timestamp"),
        "cancelled_reason": bill.get("cancelled_reason"),
        "cancelled_timestamp": bill.get("cancelled_timestamp"),
    }


def bill_card(code: str | None = None, number: str | None = None) -> dict[str, Any] | None:
    """The hover card for a bill, found by its code (``BILL-0012``) or by the number printed on it (``2026-27/202``, unique for ever).
    None when there is no such bill."""
    code = (code or "").strip()[:60]
    number = (number or "").strip()[:60]
    if not code and number:
        with db_cursor() as cur:
            cur.execute("SELECT bill_code FROM orion_ods.bill WHERE bill_number = %s", (number,))
            row = cur.fetchone()
        code = row[0] if row else ""
    bill = get_bill(code) if code else None
    if not bill:
        return None
    created_by = None
    if bill.get("created_by") is not None:
        with db_cursor() as cur:
            cur.execute("SELECT display_name FROM orion_ods.app_user WHERE id = %s", (bill["created_by"],))
            row = cur.fetchone()
            created_by = row[0] if row else None
    return card_from(bill, created_by)


_FULL_MONTHS = ("january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december")


def month_hint(text: str) -> tuple[int, int | None] | None:
    """A month typed as a search: "sep", "september 2026", "sept 26", "2026-09" or "09/2026" -> (month number, year or None). Anything else is not a month."""
    t = " ".join(text.lower().replace(",", " ").replace(".", " ").split())
    found = re.fullmatch(r"(\d{4})[-/](\d{1,2})", t) or re.fullmatch(r"(\d{1,2})[-/](\d{4})", t)
    if found:
        a, b = int(found.group(1)), int(found.group(2))
        year, month = (a, b) if a > 31 else (b, a)
        return (month, year) if 1 <= month <= 12 else None
    found = re.fullmatch(r"([a-z]{3,9})(?: (\d{2}|\d{4}))?", t)
    if found:
        number = next((i + 1 for i, name in enumerate(_FULL_MONTHS) if name.startswith(found.group(1))), None)
        if number is not None:
            year = int(found.group(2)) if found.group(2) else None
            return (number, year + 2000 if year is not None and year < 100 else year)
    return None


def list_bills(
    fy: int | None = None,
    search: str | None = None,
    limit: int = 500,
    client_code: str | None = None,
    case_code: str | None = None,
    month: str | None = None,
) -> list[dict[str, Any]]:
    """Bills, newest first. ``month`` is the month the bill is FOR (YYYY-MM). A search matches the number, party, reference, case and client, and a month typed in words
    ("sep", "september 2026") matches the bills for that month."""
    where, params = ["TRUE"], []
    if fy:
        where.append("b.fy_start_year = %s")
        params.append(fy)
    if client_code:
        where.append("b.client_code = %s")
        params.append(client_code)
    if case_code:
        where.append("b.case_code = %s")
        params.append(case_code)
    if month:
        start = _month_start(month)
        where.append("b.service_month = %s")
        params.append(start)
    needle = (search or "").strip()[:100]
    if needle:
        clause = (
            "b.party_name ILIKE %s OR b.bill_number ILIKE %s OR b.ref_no ILIKE %s"
            " OR cs.case_name ILIKE %s OR cl.client_name ILIKE %s OR b.location ILIKE %s"
        )
        found = [f"%{needle}%"] * 6
        hint = month_hint(needle)
        if hint:
            clause += " OR (EXTRACT(MONTH FROM b.service_month) = %s AND (%s::int IS NULL OR EXTRACT(YEAR FROM b.service_month) = %s))"
            found += [hint[0], hint[1], hint[1]]
        where.append(f"({clause})")
        params.extend(found)
    with db_cursor() as cur:
        cur.execute(
            f"""
            SELECT {LIST_COLUMNS}
              FROM {BILL_FROM}
             WHERE {' AND '.join(where)}
             ORDER BY b.bill_date DESC, b.bill_seq DESC
             LIMIT %s
            """,
            [*params, max(1, min(limit, 2000))],
        )
        return [_row(cur, row) for row in cur.fetchall()]


DUE_LOOKBACK_MONTHS = 6


def months_between(earlier: date, later: date) -> int:
    return (later.year - earlier.year) * 12 + later.month - earlier.month


def default_due_month(today: date | None = None) -> date:
    """Bills are raised in the month after the service, so the month to bill is last month."""
    today = today or date.today()
    return date(today.year - 1, 12, 1) if today.month == 1 else date(today.year, today.month - 1, 1)


def list_due_to_bill(for_month: str | None = None) -> dict[str, Any]:
    """Cases that were billed before but have no bill yet for ``for_month`` (YYYY-MM).

    Each row is the case's latest issued bill, which is what a repeat bill is copied from.
    Cases billed longer ago than DUE_LOOKBACK_MONTHS are treated as ended, and an Inactive
    case is left out.
    """
    target = _month_start(for_month) if for_month else default_due_month()
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT l.bill_code AS id, l.bill_number, l.bill_date, l.service_month, l.party_name,
                   l.grand_total, l.location, l.case_code, cs.case_name, l.client_code, cl.client_name
              FROM (
                    SELECT DISTINCT ON (case_code) *
                      FROM orion_ods.bill
                     WHERE status = 'Issued' AND case_code IS NOT NULL
                     ORDER BY case_code, service_month DESC, bill_seq DESC
                   ) l
              JOIN orion_ods.case cs ON cs.case_code = l.case_code
              LEFT JOIN orion_ods.client cl ON cl.client_code = l.client_code
             WHERE l.service_month < %s
               AND l.service_month >= (%s::date - make_interval(months => %s))
               AND COALESCE(cs.case_status, 'Active') <> 'Inactive'
             ORDER BY l.service_month, cs.case_name
            """,
            (target, target, DUE_LOOKBACK_MONTHS),
        )
        cases = [_row(cur, row) for row in cur.fetchall()]
        # What is already billed for the month, so the page can say how far along the month is: the cases with an issued bill for it and what those bills came to.
        cur.execute(
            """
            SELECT COUNT(DISTINCT b.case_code), COALESCE(SUM(b.grand_total), 0)
              FROM orion_ods.bill b
              JOIN orion_ods.case cs ON cs.case_code = b.case_code
             WHERE b.status = 'Issued' AND b.service_month = %s
               AND COALESCE(cs.case_status, 'Active') <> 'Inactive'
            """,
            (target,),
        )
        billed_cases, billed_total = cur.fetchone()
    for case in cases:
        case["months_behind"] = months_between(date.fromisoformat(case["service_month"]), target)
    return {"month": target.strftime("%Y-%m"), "cases": cases, "billed": {"cases": int(billed_cases or 0), "total": float(billed_total or 0)}}


def financial_years() -> list[dict[str, Any]]:
    with db_cursor() as cur:
        cur.execute("SELECT DISTINCT fy_start_year FROM orion_ods.bill ORDER BY fy_start_year DESC")
        years = [row[0] for row in cur.fetchall()]
    current = fy_start_year(date.today())
    if current not in years:
        years.insert(0, current)
    return [{"id": str(year), "label": f"FY {fy_label(year)}"} for year in years]


def cancel_bill(bill_code: str, reason: str, user_id: int | None) -> dict[str, Any]:
    """Cancelling keeps the number on record, so the numbering never has gaps that cannot be explained."""
    why = _text(reason, 300)
    if not why:
        raise BillError("Say why the bill is being cancelled.")
    with db_cursor(commit=True) as cur:
        bill = _bill_row(cur, bill_code, lock=True)
        if not bill:
            raise BillError("That bill does not exist.")
        if bill["status"] != "Issued":
            raise BillError("That bill is already cancelled.")
        received = sum(
            (e["total"] for e in _revenue_entries(cur, bill_code, lock=True) if e["status"] == "Committed"), ZERO
        )
        if received > 0:
            raise BillError(
                f"{_inr(received)} has been received against this bill, so it cannot be cancelled. "
                "An admin can reverse the payments first."
            )
        if bill.get("credited_amount"):
            raise BillError(
                f"{_inr(bill['credited_amount'])} has been credited against this bill by a credit note, so it cannot be cancelled. "
                "An admin can reverse the credit note first."
            )
        gst_paid = sum((row["amount"] for row in _gst_payment_rows(cur, bill_code, lock=True) if not row["reversed"]), ZERO)
        if gst_paid > 0:
            raise BillError(
                f"{_inr(gst_paid)} of GST has been paid to the government on this bill, so it cannot be cancelled. "
                "Reverse the GST payments first (the bill's GST, History)."
            )
        statutory_paid = sum((row["amount"] for row in _statutory_payment_rows(cur, bill_code, lock=True) if not row["reversed"]), ZERO)
        if statutory_paid > 0:
            raise BillError(
                f"{_inr(statutory_paid)} of EPFO and ESIC has been paid on this bill, so it cannot be cancelled. "
                "Reverse those payments first (the bill's EPFO and ESIC, History)."
            )
        cur.execute(
            """
            UPDATE orion_ods.bill
               SET status = 'Cancelled', cancelled_reason = %s, cancelled_timestamp = CURRENT_TIMESTAMP,
                   last_updated_timestamp = CURRENT_TIMESTAMP
             WHERE bill_code = %s
            """,
            (why, bill_code),
        )
        _sync_revenue(cur, {**bill, "status": "Cancelled"}, user_id)
    return get_bill(bill_code)


GST_REASON_MIN = 5
GST_REASON_MAX = 300
GST_REFERENCE_MAX = 60
GST_COMPONENTS = ("CGST", "SGST")


class GstConflict(BillError):
    """Somebody changed the GST payments on this bill since the person opened it."""


def gst_summary(cgst_due: Any, sgst_due: Any, payments: list[dict[str, Any]]) -> dict[str, Any]:
    """Where the GST on a bill stands, from what it comes to and the payments recorded against it (a reversed one counts for nothing).

    Paid in full when each of CGST and SGST is covered; Part paid when something has been paid but not all of it. All figures are what the bill
    and its payments hold: nothing here is calculated afresh."""
    due = {"CGST": Decimal(str(cgst_due or 0)), "SGST": Decimal(str(sgst_due or 0))}
    paid = {name: ZERO for name in GST_COMPONENTS}
    for payment in payments:
        if not payment.get("reversed") and payment.get("component") in paid:
            paid[payment["component"]] += Decimal(str(payment["amount"]))
    left = {name: max(due[name] - paid[name], ZERO) for name in GST_COMPONENTS}
    total_due, total_paid, total_left = sum(due.values(), ZERO), sum(paid.values(), ZERO), sum(left.values(), ZERO)
    if total_due <= 0:
        status = "No GST"
    elif total_left <= 0:
        status = "Paid"
    else:
        status = "Part paid" if total_paid > 0 else "Not paid"
    out: dict[str, Any] = {"status": status}
    for name in GST_COMPONENTS:
        out[name.lower()] = {"due": float(due[name]), "paid": float(paid[name]), "remaining": float(left[name])}
    out["total"] = {"due": float(total_due), "paid": float(total_paid), "remaining": float(total_left)}
    return out


def _gst_payment_rows(cur, bill_code: str, *, lock: bool = False) -> list[dict[str, Any]]:
    cur.execute(
        f"""
        SELECT p.gst_payment_sk, p.batch_id, p.component, p.amount, p.paid_date, p.reference, p.recorded_by, ru.display_name AS recorded_by_name,
               p.recorded_timestamp, p.reversed_by, vu.display_name AS reversed_by_name, p.reversed_timestamp, p.reversal_reason
          FROM orion_ods.bill_gst_payment p
          LEFT JOIN orion_ods.app_user ru ON ru.id = p.recorded_by
          LEFT JOIN orion_ods.app_user vu ON vu.id = p.reversed_by
         WHERE p.bill_code = %s
         ORDER BY p.recorded_timestamp, p.gst_payment_sk
        {'FOR UPDATE OF p' if lock else ''}
        """,
        (bill_code,),
    )
    rows = [{col.name: value for col, value in zip(cur.description, row)} for row in cur.fetchall()]
    for row in rows:
        row["reversed"] = row["reversed_timestamp"] is not None
    return rows


def gst_batches(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The payments as people think of them: one entry per payment recorded together (its CGST and its SGST), newest first."""
    batches: dict[str, dict[str, Any]] = {}
    for row in rows:
        batch = batches.setdefault(
            row["batch_id"],
            {
                "batch_id": row["batch_id"], "paid_date": _plain(row["paid_date"]), "reference": row["reference"],
                "recorded_by_name": row["recorded_by_name"], "recorded_timestamp": _plain(row["recorded_timestamp"]),
                "cgst": 0.0, "sgst": 0.0, "total": 0.0, "reversed": row["reversed"], "reversed_by_name": row["reversed_by_name"],
                "reversed_timestamp": _plain(row["reversed_timestamp"]), "reversal_reason": row["reversal_reason"],
            },
        )
        amount = float(row["amount"])
        batch[row["component"].lower()] += amount
        batch["total"] += amount
    out = list(batches.values())
    for batch in out:
        for key in ("cgst", "sgst", "total"):
            batch[key] = round(batch[key], 2)
    return sorted(out, key=lambda batch: batch["recorded_timestamp"] or "", reverse=True)


def _sync_gst(cur, bill: dict[str, Any]) -> dict[str, Any]:
    """Make the bill's running total and its paid flag match its payments. Call after any change to them, and after any change to the bill's
    GST. Refuses (so the whole change is undone) if payments have been recorded for more than the bill's GST now comes to."""
    rows = _gst_payment_rows(cur, bill["bill_code"])
    summary = gst_summary(*_gst_due(bill), rows)
    for name in GST_COMPONENTS:
        part = summary[name.lower()]
        if part["paid"] > part["due"] + 0.004:
            raise BillError(
                f"{_inr(Decimal(str(part['paid'])))} of {name} has already been paid to the government on this bill, so its {name} cannot "
                f"go below that. Reverse the GST payment first (the bill's GST, History)."
            )
    active = [row for row in rows if not row["reversed"]]
    last = active[-1] if active else None
    whole = summary["status"] == "Paid"
    cur.execute(
        """
        UPDATE orion_ods.bill
           SET gst_paid = %s, gst_paid_amount = %s,
               gst_paid_by = CASE WHEN %s THEN %s::integer END,
               gst_paid_timestamp = CASE WHEN %s THEN %s::timestamptz END,
               last_updated_timestamp = CURRENT_TIMESTAMP
         WHERE bill_code = %s
        """,
        (whole, Decimal(str(summary["total"]["paid"])), whole, last["recorded_by"] if last else None, whole, last["recorded_timestamp"] if last else None, bill["bill_code"]),
    )
    return summary


def _lock_issued_bill(cur, bill_code: str, what: str = "GST") -> dict[str, Any]:
    bill = _bill_row(cur, bill_code, lock=True)
    if not bill:
        raise BillError("That bill does not exist.")
    if bill["status"] != "Issued":
        raise BillError(f"A cancelled bill has no {what} to pay.")
    return bill


def _gst_amount(value: Any, label: str) -> Decimal:
    if value is None or str(value).strip() == "":
        return ZERO
    amount = _paisa(_dec(value, label))
    if amount < 0:
        raise BillError(f"{label} cannot be negative.")
    return amount


def record_gst_payment(
    bill_code: str,
    user_id: int | None,
    *,
    confirm: bool = False,
    seen_paid: Any = None,
    cgst: Any = None,
    sgst: Any = None,
    paid_date: Any = None,
    reference: str | None = None,
    today: date | None = None,
    account_id: Any = None,
) -> dict[str, Any]:
    """Record a payment of GST to the government against a bill: an amount of CGST, of SGST, or of both, on a day, with an optional challan or
    payment reference. A bill's GST may be paid in several payments, on different days. A deliberate act, never a casual tick:

    * ``confirm`` must be true: a request that did not come from the confirmation screen is refused;
    * ``seen_paid`` is how much GST had been paid when the person opened the bill; if it has changed since, nothing is written;
    * each amount can be no more than is still to pay on that component, and the day is not before the bill and not in the future.

    The payments are kept for ever (reversing one keeps it, with who and why), so the bill's GST history is never lost."""
    if not confirm:
        raise BillError("Confirm the payment to continue.")
    if seen_paid is None:
        raise BillError("Reload the bill and try again: it is not clear what state you saw it in.")
    today = today or date.today()
    amounts = {"CGST": _gst_amount(cgst, "The CGST amount"), "SGST": _gst_amount(sgst, "The SGST amount")}
    if not any(amounts.values()):
        raise BillError("Enter how much CGST or SGST was paid.")
    day = _gst_day(paid_date)
    if day > today:
        raise BillError("The day the GST was paid cannot be in the future.")
    ref = " ".join(str(reference or "").split())[:GST_REFERENCE_MAX] or None
    with db_cursor(commit=True) as cur:
        bill = _lock_issued_bill(cur, bill_code)
        account = _checked_account(cur, account_id)
        if bill["bill_date"] and day < bill["bill_date"]:
            raise BillError(f"The GST cannot have been paid before the bill was dated ({bill['bill_date']:%d %b %Y}).")
        rows = _gst_payment_rows(cur, bill_code, lock=True)
        summary = gst_summary(*_gst_due(bill), rows)
        if _paisa(_dec(seen_paid, "The GST paid so far")) != _paisa(Decimal(str(summary["total"]["paid"]))):
            raise GstConflict(
                f"The GST payments on bill {bill['bill_number']} were changed by someone else while you had it open ({_inr(Decimal(str(summary['total']['paid'])))} "
                "is now recorded as paid). Reload the bill to see where it stands."
            )
        for name, amount in amounts.items():
            left = Decimal(str(summary[name.lower()]["remaining"]))
            if amount > left:
                raise BillError(
                    f"Only {_inr(left)} of {name} is left to pay on this bill." if left > 0 else f"The {name} on this bill is already paid in full."
                )
        batch = uuid.uuid4().hex
        for name, amount in amounts.items():
            if amount > 0:
                cur.execute(
                    """
                    INSERT INTO orion_ods.bill_gst_payment (bill_code, batch_id, component, amount, paid_date, reference, recorded_by, account_id)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (bill_code, batch, name, amount, day, ref, user_id, account),
                )
        _sync_gst(cur, bill)
    bill_after = get_bill(bill_code)
    if bill_after is None:
        raise BillError("That bill does not exist.")
    return bill_after


def reverse_gst_payment(bill_code: str, batch_id: str, user_id: int | None, *, confirm: bool = False, reason: str | None = None) -> dict[str, Any]:
    """Take a recorded GST payment back (all of what was recorded together), with the reason. The payment stays in the history, marked
    reversed, with who reversed it and when; what is owed goes up by what it had covered."""
    if not confirm:
        raise BillError("Confirm the reversal to continue.")
    why = " ".join(str(reason or "").split())
    if len(why) < GST_REASON_MIN:
        raise BillError(f"Say why the payment is being reversed (at least {GST_REASON_MIN} characters).")
    why = why[:GST_REASON_MAX]
    with db_cursor(commit=True) as cur:
        bill = _lock_issued_bill(cur, bill_code)
        rows = [row for row in _gst_payment_rows(cur, bill_code, lock=True) if row["batch_id"] == batch_id]
        if not rows:
            raise BillError("That payment does not exist.")
        if any(row["reversed"] for row in rows):
            raise GstConflict("That GST payment has already been reversed. Reload the bill to see where it stands.")
        cur.execute(
            """
            UPDATE orion_ods.bill_gst_payment
               SET reversed_by = %s, reversed_timestamp = CURRENT_TIMESTAMP, reversal_reason = %s
             WHERE bill_code = %s AND batch_id = %s AND reversed_timestamp IS NULL
            """,
            (user_id, why, bill_code, batch_id),
        )
        _sync_gst(cur, bill)
    bill_after = get_bill(bill_code)
    if bill_after is None:
        raise BillError("That bill does not exist.")
    return bill_after


# --------------------------------------------------------------------------- EPFO and ESIC paid on a bill
#
# What a bill charges for EPFO and for ESIC is paid over to the authorities, in whole or in parts, on different days. The business tracks it bill by bill, the
# same way it tracks GST: each payment is a row (``bill_statutory_payment``), a payment is a confirmed, dated, bounded act, and a reversal needs a reason and
# keeps the row. What is DUE on a bill is what it charged (``epf_amount``, ``esic_amount``); a credit note does not lower it, because what is owed to the
# authorities follows the wages worked, not the bill's value. None of this changes Revenue: EPFO and ESIC stay inside the bill's taxable value. Once PAID over it is a cost, on the day paid, against the bill's case (the view orion_dw.expense_cost); that does not depend on payroll.

STATUTORY_COMPONENTS = ("EPFO", "ESIC")
STATUTORY_REASON_MIN = 5
STATUTORY_REASON_MAX = 300
STATUTORY_REFERENCE_MAX = 60


class StatutoryConflict(BillError):
    """Somebody changed the EPFO or ESIC payments on this bill since the person opened it."""


def _statutory_due(bill: dict[str, Any]) -> tuple[Decimal, Decimal]:
    """What the bill charged for EPFO and for ESIC."""
    return Decimal(str(bill.get("epf_amount") or 0)), Decimal(str(bill.get("esic_amount") or 0))


def statutory_summary(epf_due: Any, esic_due: Any, payments: list[dict[str, Any]]) -> dict[str, Any]:
    """Where EPFO and ESIC stand on a bill, from what it charged and the payments recorded against it (a reversed one counts for nothing).

    Each of the two is Paid, Part paid, Not paid, or None (the bill charged nothing for it). The bill as a whole is Paid when both are covered. All figures
    are what the bill and its payments hold: nothing here is calculated afresh."""
    due = {"EPFO": Decimal(str(epf_due or 0)), "ESIC": Decimal(str(esic_due or 0))}
    paid = {name: ZERO for name in STATUTORY_COMPONENTS}
    for payment in payments:
        if not payment.get("reversed") and payment.get("component") in paid:
            paid[payment["component"]] += Decimal(str(payment["amount"]))
    left = {name: max(due[name] - paid[name], ZERO) for name in STATUTORY_COMPONENTS}
    total_due, total_paid, total_left = sum(due.values(), ZERO), sum(paid.values(), ZERO), sum(left.values(), ZERO)
    if total_due <= 0:
        status = "No EPFO or ESIC"
    elif total_left <= 0:
        status = "Paid"
    else:
        status = "Part paid" if total_paid > 0 else "Not paid"
    out: dict[str, Any] = {"status": status}
    for name in STATUTORY_COMPONENTS:
        if due[name] <= 0:
            part = "None"
        elif left[name] <= 0:
            part = "Paid"
        else:
            part = "Part paid" if paid[name] > 0 else "Not paid"
        out[name.lower()] = {"due": float(due[name]), "paid": float(paid[name]), "remaining": float(left[name]), "status": part}
    out["total"] = {"due": float(total_due), "paid": float(total_paid), "remaining": float(total_left)}
    return out


def _statutory_payment_rows(cur, bill_code: str, *, lock: bool = False) -> list[dict[str, Any]]:
    cur.execute(
        f"""
        SELECT p.statutory_payment_sk, p.batch_id, p.component, p.amount, p.paid_date, p.reference, p.recorded_by, ru.display_name AS recorded_by_name,
               p.recorded_timestamp, p.reversed_by, vu.display_name AS reversed_by_name, p.reversed_timestamp, p.reversal_reason
          FROM orion_ods.bill_statutory_payment p
          LEFT JOIN orion_ods.app_user ru ON ru.id = p.recorded_by
          LEFT JOIN orion_ods.app_user vu ON vu.id = p.reversed_by
         WHERE p.bill_code = %s
         ORDER BY p.recorded_timestamp, p.statutory_payment_sk
        {'FOR UPDATE OF p' if lock else ''}
        """,
        (bill_code,),
    )
    rows = [{col.name: value for col, value in zip(cur.description, row)} for row in cur.fetchall()]
    for row in rows:
        row["reversed"] = row["reversed_timestamp"] is not None
    return rows


def statutory_batches(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The payments as people think of them: one entry per payment recorded together (its EPFO and its ESIC), newest first."""
    batches: dict[str, dict[str, Any]] = {}
    for row in rows:
        batch = batches.setdefault(
            row["batch_id"],
            {
                "batch_id": row["batch_id"], "paid_date": _plain(row["paid_date"]), "reference": row["reference"],
                "recorded_by_name": row["recorded_by_name"], "recorded_timestamp": _plain(row["recorded_timestamp"]),
                "epfo": 0.0, "esic": 0.0, "total": 0.0, "reversed": row["reversed"], "reversed_by_name": row["reversed_by_name"],
                "reversed_timestamp": _plain(row["reversed_timestamp"]), "reversal_reason": row["reversal_reason"],
            },
        )
        amount = float(row["amount"])
        batch[row["component"].lower()] += amount
        batch["total"] += amount
    out = list(batches.values())
    for batch in out:
        for key in ("epfo", "esic", "total"):
            batch[key] = round(batch[key], 2)
    return sorted(out, key=lambda batch: batch["recorded_timestamp"] or "", reverse=True)


def _sync_statutory(cur, bill: dict[str, Any]) -> dict[str, Any]:
    """Make the bill's running totals match its payments. Call after any change to them and after any change to what the bill charges. Refuses (so the whole
    change is undone) if payments have been recorded for more than the bill now charges."""
    rows = _statutory_payment_rows(cur, bill["bill_code"])
    summary = statutory_summary(*_statutory_due(bill), rows)
    for name in STATUTORY_COMPONENTS:
        part = summary[name.lower()]
        if part["paid"] > part["due"] + 0.004:
            raise BillError(
                f"{_inr(Decimal(str(part['paid'])))} of {name} has already been paid on this bill, so its {name} cannot go below that. "
                "Reverse the payment first (the bill's EPFO and ESIC, History)."
            )
    cur.execute(
        """
        UPDATE orion_ods.bill
           SET epf_paid_amount = %s, esic_paid_amount = %s, last_updated_timestamp = CURRENT_TIMESTAMP
         WHERE bill_code = %s
        """,
        (Decimal(str(summary["epfo"]["paid"])), Decimal(str(summary["esic"]["paid"])), bill["bill_code"]),
    )
    return summary


def record_statutory_payment(
    bill_code: str,
    user_id: int | None,
    *,
    confirm: bool = False,
    seen_paid: Any = None,
    epfo: Any = None,
    esic: Any = None,
    paid_date: Any = None,
    reference: str | None = None,
    today: date | None = None,
    account_id: Any = None,
) -> dict[str, Any]:
    """Record a payment of EPFO, of ESIC, or of both, made to the authority against a bill: an amount of each, on a day, with an optional challan or payment
    reference. They may be paid in several payments, on different days. A deliberate act, never a casual tick:

    * ``confirm`` must be true: a request that did not come from the confirmation screen is refused;
    * ``seen_paid`` is how much EPFO and ESIC had been paid when the person opened the bill; if it has changed since, nothing is written;
    * each amount can be no more than is still to pay on it, and the day is not before the bill and not in the future.

    The payments are kept for ever (reversing one keeps it, with who and why). Money goes out of the bank on the day paid (the view ``bank_movement``)."""
    if not confirm:
        raise BillError("Confirm the payment to continue.")
    if seen_paid is None:
        raise BillError("Reload the bill and try again: it is not clear what state you saw it in.")
    today = today or date.today()
    amounts = {"EPFO": _gst_amount(epfo, "The EPFO amount"), "ESIC": _gst_amount(esic, "The ESIC amount")}
    if not any(amounts.values()):
        raise BillError("Enter how much EPFO or ESIC was paid.")
    day = _gst_day(paid_date, "EPFO or ESIC")
    if day > today:
        raise BillError("The day it was paid cannot be in the future.")
    ref = " ".join(str(reference or "").split())[:STATUTORY_REFERENCE_MAX] or None
    with db_cursor(commit=True) as cur:
        bill = _lock_issued_bill(cur, bill_code, "EPFO or ESIC")
        account = _checked_account(cur, account_id)
        if bill["bill_date"] and day < bill["bill_date"]:
            raise BillError(f"It cannot have been paid before the bill was dated ({bill['bill_date']:%d %b %Y}).")
        rows = _statutory_payment_rows(cur, bill_code, lock=True)
        summary = statutory_summary(*_statutory_due(bill), rows)
        if _paisa(_dec(seen_paid, "The EPFO and ESIC paid so far")) != _paisa(Decimal(str(summary["total"]["paid"]))):
            raise StatutoryConflict(
                f"The EPFO and ESIC payments on bill {bill['bill_number']} were changed by someone else while you had it open "
                f"({_inr(Decimal(str(summary['total']['paid'])))} is now recorded as paid). Reload the bill to see where it stands."
            )
        for name, amount in amounts.items():
            left = Decimal(str(summary[name.lower()]["remaining"]))
            if amount > left:
                raise BillError(
                    f"Only {_inr(left)} of {name} is left to pay on this bill." if left > 0 else f"The {name} on this bill is already paid in full."
                )
        batch = uuid.uuid4().hex
        for name, amount in amounts.items():
            if amount > 0:
                cur.execute(
                    """
                    INSERT INTO orion_ods.bill_statutory_payment (bill_code, batch_id, component, amount, paid_date, reference, recorded_by, account_id)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (bill_code, batch, name, amount, day, ref, user_id, account),
                )
        _sync_statutory(cur, bill)
    bill_after = get_bill(bill_code)
    if bill_after is None:
        raise BillError("That bill does not exist.")
    return bill_after


def reverse_statutory_payment(bill_code: str, batch_id: str, user_id: int | None, *, confirm: bool = False, reason: str | None = None) -> dict[str, Any]:
    """Take a recorded EPFO or ESIC payment back (all of what was recorded together), with the reason. The payment stays in the history, marked reversed,
    with who reversed it and when; what is owed goes up by what it had covered, and the bank balance goes back up by it."""
    if not confirm:
        raise BillError("Confirm the reversal to continue.")
    why = " ".join(str(reason or "").split())
    if len(why) < STATUTORY_REASON_MIN:
        raise BillError(f"Say why the payment is being reversed (at least {STATUTORY_REASON_MIN} characters).")
    why = why[:STATUTORY_REASON_MAX]
    with db_cursor(commit=True) as cur:
        bill = _lock_issued_bill(cur, bill_code, "EPFO or ESIC")
        rows = [row for row in _statutory_payment_rows(cur, bill_code, lock=True) if row["batch_id"] == batch_id]
        if not rows:
            raise BillError("That payment does not exist.")
        if any(row["reversed"] for row in rows):
            raise StatutoryConflict("That payment has already been reversed. Reload the bill to see where it stands.")
        cur.execute(
            """
            UPDATE orion_ods.bill_statutory_payment
               SET reversed_by = %s, reversed_timestamp = CURRENT_TIMESTAMP, reversal_reason = %s
             WHERE bill_code = %s AND batch_id = %s AND reversed_timestamp IS NULL
            """,
            (user_id, why, bill_code, batch_id),
        )
        _sync_statutory(cur, bill)
    bill_after = get_bill(bill_code)
    if bill_after is None:
        raise BillError("That bill does not exist.")
    return bill_after


def _gst_day(value: Any, what: str = "GST") -> date:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value or "").strip()[:10])
    except ValueError:
        raise BillError(f"Give the day the {what} was paid.") from None
