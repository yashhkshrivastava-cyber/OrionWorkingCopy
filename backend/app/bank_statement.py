"""Reading a bank statement file (CSV or Excel) into lines, whatever bank it came from.

Banks export the same facts in different shapes: a few lines of account details above the table, then headers named ``Narration``,
``Particulars`` or ``Transaction Remarks``; money in two columns (``Withdrawal`` / ``Deposit``, ``Debit`` / ``Credit``) or in one
signed column with ``Dr`` / ``Cr`` beside it; dates as ``31/03/26``, ``31-Mar-2026`` or an Excel date; newest line first or last; a
narration that wraps onto the next row; opening, closing and total rows in the middle. This module finds the table, works out which
column is which, reads every line, and checks the result against the statement's own running balance, because a statement that does not
add up has been misread (or has lines missing) and the person must be told before anything is saved.

Nothing here touches the database or the application: bytes in, a description of what the file holds out. ``parse_statement`` is the
entry point. The person can override the guess for any column (``mapping``).
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Optional

from app.xlsx_io import read_first_sheet

MAX_BYTES = 6 * 1024 * 1024
MAX_LINES = 20_000
HEADER_SEARCH_ROWS = 80
PAISA = Decimal("0.01")

#: What each column of a statement can be called, best name first. Compared after lower-casing and dropping punctuation.
SYNONYMS: dict[str, tuple[str, ...]] = {
    "date": ("transaction date", "txn date", "tran date", "trans date", "date", "posting date", "post date", "value date", "value dt"),
    "description": (
        "narration", "description", "particulars", "transaction remarks", "transaction details", "transaction description", "remarks",
        "details", "narrative", "transaction particulars",
    ),
    "reference": (
        "chq ref no", "chq no", "cheque no", "cheque number", "cheque ref no", "ref no", "ref number", "reference no", "reference number",
        "reference", "utr", "utr no", "utr number", "instrument no", "instrument number", "transaction id", "txn id", "chq ref number",
        "ref no cheque no", "cheque no ref no", "chq no ref no",
    ),
    "debit": (
        "withdrawal amt", "withdrawal amount", "withdrawals", "withdrawal", "debit amount", "debit amt", "debits", "debit", "paid out",
        "amount debited", "dr amount", "dr",
    ),
    "credit": (
        "deposit amt", "deposit amount", "deposits", "deposit", "credit amount", "credit amt", "credits", "credit", "paid in",
        "amount credited", "cr amount", "cr",
    ),
    "amount": ("transaction amount", "txn amount", "amount inr", "amount", "amt"),
    "balance": ("closing balance", "running balance", "available balance", "balance amt", "balance amount", "balance inr", "balance", "bal"),
    "type": ("dr cr", "cr dr", "drcr", "crdr", "transaction type", "txn type", "type", "dr or cr"),
}
FIELD_ORDER = ("date", "description", "reference", "debit", "credit", "amount", "balance", "type")

MONTHS = {m: i for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), start=1)}

# A row that is the statement talking about itself, not a transaction.
SUMMARY_WORDS = re.compile(r"\b(opening balance|closing balance|total|grand total|statement summary|balance b/?f|balance c/?f|brought forward|carried forward)\b", re.I)


class StatementError(ValueError):
    """The file cannot be read as a statement. The message is safe to show to the person."""


@dataclass
class StatementLine:
    row: int                      # the row in the file (1-based), for telling the person where
    date: date
    description: str
    reference: str
    direction: str                # 'in' or 'out'
    amount: Decimal
    balance: Optional[Decimal] = None

    @property
    def signed(self) -> Decimal:
        return self.amount if self.direction == "in" else -self.amount


@dataclass
class Issue:
    row: Optional[int]
    message: str
    severity: str = "warning"     # 'warning' or 'error'


@dataclass
class ParsedStatement:
    filename: str
    sha256: str
    header_row: int = 0
    headers: list[str] = field(default_factory=list)
    mapping: dict[str, int] = field(default_factory=dict)
    lines: list[StatementLine] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)
    opening_balance: Optional[Decimal] = None     # the statement's own, from the balance column
    closing_balance: Optional[Decimal] = None
    period_from: Optional[date] = None
    period_to: Optional[date] = None
    newest_first: bool = False
    balance_checked: int = 0
    balance_breaks: int = 0
    skipped_rows: int = 0
    sample: list[list[str]] = field(default_factory=list)   # the first rows of the table as text, for the person to confirm the guess

    @property
    def balanced(self) -> Optional[bool]:
        """True when every line's balance followed from the one before; None when the file has no balance column to check."""
        return None if not self.balance_checked else self.balance_breaks == 0


# ------------------------------------------------------------------------------------------------------------------ reading a file


def _text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return re.sub(r"\s+", " ", str(value)).strip()


def _decode(content: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise StatementError("The file could not be read as text. Export the statement as CSV or Excel from your bank's net banking.")


def read_rows(filename: str, content: bytes) -> list[list[object]]:
    """The file as rows of cells. CSV (any common delimiter) and Excel (.xlsx) are read; anything else is explained."""
    if len(content) > MAX_BYTES:
        raise StatementError(f"That file is larger than {MAX_BYTES // (1024 * 1024)} MB. Export a shorter period.")
    if not content.strip():
        raise StatementError("That file is empty.")
    name = (filename or "").lower()
    if content[:4] == b"%PDF" or name.endswith(".pdf"):
        raise StatementError("A PDF statement cannot be read reliably. In net banking, export the statement as CSV or Excel instead.")
    if name.endswith(".xls") and not content[:2] == b"PK":
        raise StatementError("Old Excel (.xls) files are not supported. Save it as .xlsx or CSV, then upload that.")
    if content[:2] == b"PK" or name.endswith(".xlsx"):
        try:
            return read_first_sheet(content)
        except Exception as exc:  # noqa: BLE001 - a damaged workbook is reported, whatever is wrong with it
            raise StatementError("That Excel file could not be read. Try saving it again as .xlsx or CSV.") from exc
    text = _decode(content)
    sample = text[:8192]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    return [list(row) for row in csv.reader(io.StringIO(text), dialect)]


# --------------------------------------------------------------------------------------------------------- dates and amounts


def parse_date(value: object) -> Optional[date]:
    """A date as banks write it: day first, two or four digit year, month as a number or a name; or an Excel date. None if it is not one."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if 20_000 < float(value) < 80_000:  # an Excel serial date (1954 to 2118)
            return date(1899, 12, 30) + timedelta(days=int(value))
        return None
    text = _text(value)
    if not text:
        return None
    text = re.sub(r"\s+\d{1,2}:\d{2}(:\d{2})?(\s*[ap]m)?$", "", text, flags=re.I)  # a time of day after the date
    iso = re.fullmatch(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", text)
    if iso:
        return _make_date(int(iso.group(1)), int(iso.group(2)), int(iso.group(3)))
    numeric = re.fullmatch(r"(\d{1,2})[-/. ](\d{1,2})[-/. ](\d{2}|\d{4})", text)
    if numeric:
        return _make_date(_year(numeric.group(3)), int(numeric.group(2)), int(numeric.group(1)))
    named = re.fullmatch(r"(\d{1,2})[-/. ]([A-Za-z]{3,9})[-/. ,]*(\d{2}|\d{4})", text)
    if named:
        month = MONTHS.get(named.group(2)[:3].lower())
        return _make_date(_year(named.group(3)), month, int(named.group(1))) if month else None
    return None


def _year(text: str) -> int:
    year = int(text)
    return year + 2000 if year < 100 else year


def _make_date(year: int, month: Optional[int], day: int) -> Optional[date]:
    try:
        return date(year, month or 0, day)
    except ValueError:
        return None


def parse_money(value: object) -> tuple[Optional[Decimal], Optional[str]]:
    """An amount and, when the cell says so, whether it is a debit ('dr') or credit ('cr'): ``1,23,456.00``, ``(500)``, ``500 Cr``, ``-500``,
    ``₹ 2,000``. (None, None) for an empty cell or text that is not an amount."""
    if value is None:
        return None, None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return Decimal(str(value)).quantize(PAISA, rounding=ROUND_HALF_UP), None
    text = _text(value)
    if not text or text in ("-", "--", "—", "NA", "N/A", "nil", "Nil"):
        return None, None
    hint = None
    tail = re.search(r"\s*(dr|cr|debit|credit)\.?$", text, re.I)
    if tail:
        hint = "dr" if tail.group(1).lower().startswith("d") else "cr"
        text = text[: tail.start()]
    negative = text.startswith("(") and text.endswith(")") or text.startswith("-") or text.endswith("-")
    found = re.search(r"\d[\d,]*(?:\.\d+)?|\.\d+", text)   # the first number in it, whatever surrounds it ("Rs. 1,000.00")
    if not found or re.search(r"\d\.\d+\.\d", text):
        return None, None
    cleaned = found.group(0).replace(",", "")
    try:
        amount = Decimal(cleaned)
    except InvalidOperation:
        return None, None
    return (-amount if negative else amount).quantize(PAISA, rounding=ROUND_HALF_UP), hint


# ---------------------------------------------------------------------------------------------------------- finding the table


def _norm(cell: object) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", _text(cell).lower())).strip()


def _score(cell: str, names: tuple[str, ...]) -> int:
    """How well a header cell fits a field: 0 for not at all, higher for a closer match and for a name earlier in the list."""
    if not cell:
        return 0
    for rank, name in enumerate(names):
        if cell == name:
            return 100 - rank
    for rank, name in enumerate(names):
        if len(name) > 3 and (cell.startswith(name + " ") or cell.endswith(" " + name)):
            return 60 - rank
    return 0


def _assign(headers: list[str]) -> dict[str, int]:
    """Which column is which: each field takes its best-fitting column, and no column serves two fields."""
    options: list[tuple[int, str, int]] = []
    for field_name in FIELD_ORDER:
        for index, cell in enumerate(headers):
            score = _score(cell, SYNONYMS[field_name])
            if score:
                options.append((score, field_name, index))
    taken_columns: set[int] = set()
    taken_fields: set[str] = set()
    mapping: dict[str, int] = {}
    for _best, field_name, index in sorted(options, key=lambda item: (-item[0], FIELD_ORDER.index(item[1]), item[2])):
        if field_name in taken_fields or index in taken_columns:
            continue
        mapping[field_name] = index
        taken_fields.add(field_name)
        taken_columns.add(index)
    return mapping


def _usable(mapping: dict[str, int]) -> bool:
    return "date" in mapping and (("debit" in mapping and "credit" in mapping) or "amount" in mapping)


def find_header(rows: list[list[object]]) -> tuple[int, dict[str, int], list[str]]:
    """The header row (0-based index into rows), the guessed column map and the header texts. The first rows of a statement are usually
    account details; the table starts at the row that names a date and the money."""
    best: Optional[tuple[int, int, dict[str, int], list[str]]] = None
    for index, row in enumerate(rows[:HEADER_SEARCH_ROWS]):
        headers = [_norm(cell) for cell in row]
        mapping = _assign(headers)
        if not _usable(mapping):
            continue
        score = len(mapping)
        if best is None or score > best[0]:
            best = (score, index, mapping, [_text(cell) for cell in row])
    if best is None:
        raise StatementError(
            "Could not find the table in that file: no row names a date and the money (Withdrawal and Deposit, Debit and Credit, or Amount). "
            "Check that it is a bank statement, or tell Orion which column is which."
        )
    return best[1], best[2], best[3]


# ------------------------------------------------------------------------------------------------------------- reading the lines


def _cell(row: list[object], mapping: dict[str, int], name: str) -> object:
    index = mapping.get(name)
    return row[index] if index is not None and index < len(row) else None


def parse_statement(filename: str, content: bytes, mapping: Optional[dict[str, int]] = None, header_row: Optional[int] = None) -> ParsedStatement:
    """Read a statement. ``mapping`` (field -> 0-based column) and ``header_row`` (1-based) override the guess for a file the guess got wrong."""
    rows = read_rows(filename, content)
    result = ParsedStatement(filename=filename, sha256=hashlib.sha256(content).hexdigest())
    if header_row:
        start = header_row - 1
        if not 0 <= start < len(rows):
            raise StatementError("That header row is not in the file.")
        headers = [_text(cell) for cell in rows[start]]
        guessed = _assign([_norm(cell) for cell in rows[start]])
        use = {**guessed, **(mapping or {})}
    elif mapping:
        start, guessed, headers = find_header(rows)
        use = {**guessed, **mapping}
    else:
        start, use, headers = find_header(rows)
    if not _usable(use):
        raise StatementError("The columns are not enough to read a statement: it needs a date and either Debit and Credit, or an Amount.")
    result.header_row, result.headers, result.mapping = start + 1, headers, use
    result.sample = [[_text(cell) for cell in row] for row in rows[start : start + 7]]

    lines: list[StatementLine] = []
    opening_row: Optional[Decimal] = None
    negatives = 0
    for offset, row in enumerate(rows[start + 1 :], start=start + 2):
        if len(lines) >= MAX_LINES:
            result.issues.append(Issue(offset, f"Only the first {MAX_LINES:,} lines were read. Upload a shorter period.", "error"))
            break
        if not any(_text(cell) for cell in row):
            continue
        when = parse_date(_cell(row, use, "date"))
        description = _text(_cell(row, use, "description"))
        if when is None:
            # A narration that wrapped onto the next row has text and no date or amount; a summary or page-break row is skipped.
            amounts = [parse_money(_cell(row, use, key))[0] for key in ("debit", "credit", "amount") if key in use]
            if description and lines and not any(a for a in amounts) and not SUMMARY_WORDS.search(description):
                lines[-1].description = f"{lines[-1].description} {description}".strip()
            elif SUMMARY_WORDS.search(" ".join(_text(c) for c in row)):
                result.skipped_rows += 1
                text = " ".join(_text(c) for c in row)
                balance, _ = parse_money(_cell(row, use, "balance"))
                if re.search(r"opening balance|brought forward|balance b/?f", text, re.I) and balance is not None and opening_row is None:
                    opening_row = balance
            else:
                result.skipped_rows += 1
            continue
        debit, _ = parse_money(_cell(row, use, "debit")) if "debit" in use else (None, None)
        credit, _ = parse_money(_cell(row, use, "credit")) if "credit" in use else (None, None)
        balance, _ = parse_money(_cell(row, use, "balance")) if "balance" in use else (None, None)
        direction, amount = None, None
        if debit and credit:
            result.issues.append(Issue(offset, f"Row {offset}: both a debit and a credit are filled in, so it was not read.", "error"))
            continue
        if debit:
            direction, amount = "out", abs(debit)
        elif credit:
            direction, amount = "in", abs(credit)
        elif "amount" in use:
            value, hint = parse_money(_cell(row, use, "amount"))
            kind = _text(_cell(row, use, "type")).lower() if "type" in use else ""
            if value:
                if kind.startswith(("dr", "d", "w")) or hint == "dr":
                    direction = "out"
                elif kind.startswith(("cr", "c")) or hint == "cr":
                    direction = "in"
                elif value < 0:
                    direction = "out"
                    negatives += 1
                elif "type" not in use:
                    direction = "?"          # positive and nothing to say which way: decided below, from the balance column
                else:
                    direction = "in"
                amount = abs(value)
        if direction is None or amount is None or amount == 0:
            if SUMMARY_WORDS.search(description) or description == "":
                result.skipped_rows += 1
                if balance is not None and re.search(r"opening|brought forward", description, re.I) and opening_row is None:
                    opening_row = balance
            continue
        lines.append(StatementLine(row=offset, date=when, description=description, reference=_text(_cell(row, use, "reference")), direction=direction, amount=amount, balance=balance))

    _decide_unknown_directions(lines, result, opening_row, negatives > 0)
    if not lines:
        raise StatementError("The table was found but no transactions could be read from it. Check which column is which.")
    _order_and_check(lines, result, opening_row)
    result.lines = lines
    result.period_from = min(line.date for line in lines)
    result.period_to = max(line.date for line in lines)
    return result


def _decide_unknown_directions(lines: list[StatementLine], result: ParsedStatement, opening: Optional[Decimal], signed_convention: bool) -> None:
    """One amount column that is positive for every line and has no Dr/Cr beside it. If other lines are negative, the positive ones are
    credits. Otherwise the balance column says which way each line moved the money; the first line has no balance before it, so it
    needs the file's opening balance, or its own narration (a credit or a debit)."""
    unknown = [line for line in lines if line.direction == "?"]
    if not unknown:
        return
    if signed_convention:
        for line in unknown:
            line.direction = "in"
        return
    if all(line.balance is not None for line in lines):
        before = opening
        for line in lines:
            if line.direction == "?" and before is not None and line.balance is not None:
                line.direction = "in" if line.balance > before else "out"
            before = line.balance
    for line in lines:
        if line.direction == "?":
            text = line.description.lower()
            if re.search(r"\b(cr|credit|deposit|received|interest|neft cr|imps cr|upi cr)\b", text):
                line.direction = "in"
            elif re.search(r"\b(dr|debit|withdrawal|paid|neft dr|imps dr|upi dr|chq|cheque)\b", text):
                line.direction = "out"
    for line in lines:
        if line.direction == "?":
            raise StatementError(
                "The statement has one amount column and nothing to say which lines are debits and which are credits "
                "(no Dr/Cr column, no negative amounts, and no balance column or opening balance to work it out from)."
            )
    result.issues.append(Issue(None, "The file has one amount column without Dr/Cr, so each line's direction was worked out from the balance column.", "warning"))


def _breaks(lines: list[StatementLine]) -> tuple[int, int]:
    """(lines whose balance followed from the previous line's, lines where it did not), over consecutive lines that both have a balance."""
    checked = broken = 0
    for before, line in zip(lines, lines[1:]):
        if before.balance is None or line.balance is None:
            continue
        checked += 1
        if abs(before.balance + line.signed - line.balance) > Decimal("0.005"):
            broken += 1
    return checked, broken


def _order_and_check(lines: list[StatementLine], result: ParsedStatement, opening_row: Optional[Decimal]) -> None:
    """Put the lines oldest first (many banks list newest first) and check them against the running balance."""
    reverse_checked, reverse_broken = _breaks(list(reversed(lines)))
    forward_checked, forward_broken = _breaks(lines)
    if forward_checked:
        # With balances the chain decides which way the file runs.
        if reverse_broken < forward_broken:
            lines.reverse()
            result.newest_first = True
    elif len(lines) > 1 and lines[0].date > lines[-1].date:
        lines.reverse()
        result.newest_first = True
    result.balance_checked, result.balance_breaks = _breaks(lines)
    if result.balance_breaks:
        result.issues.append(
            Issue(None, f"{result.balance_breaks} of {result.balance_checked} lines do not follow from the balance before them. A line may be missing from the file, or a column was misread.", "error")
        )
    first, last = lines[0], lines[-1]
    if first.balance is not None:
        result.opening_balance = (first.balance - first.signed).quantize(PAISA)
        if opening_row is not None and abs(opening_row - result.opening_balance) > Decimal("0.005"):
            result.issues.append(Issue(None, f"The file's opening balance row ({opening_row}) does not match the first line ({result.opening_balance}).", "warning"))
    elif opening_row is not None:
        result.opening_balance = opening_row
    if last.balance is not None:
        result.closing_balance = last.balance


# ---------------------------------------------------------------------------------------------------------------- recognising lines


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


def fingerprints(lines: list[StatementLine]) -> list[str]:
    """A fingerprint per line, stable across uploads of the same period or of overlapping ones. Two genuinely identical lines on one day (the
    same amount, the same narration) are told apart by their order in the file, so each is kept once and neither is lost."""
    seen: dict[str, int] = {}
    out: list[str] = []
    for line in lines:
        base = "|".join((line.date.isoformat(), line.direction, str(line.amount), _squash(line.description), _squash(line.reference)))
        count = seen.get(base, 0)
        seen[base] = count + 1
        out.append(hashlib.sha1(f"{base}|{count}".encode()).hexdigest())
    return out


def describe(parsed: ParsedStatement) -> dict[str, Any]:
    """What the person is shown before anything is saved: what was found, how it was read, and anything that looks wrong."""
    money_in = sum((line.amount for line in parsed.lines if line.direction == "in"), Decimal(0))
    money_out = sum((line.amount for line in parsed.lines if line.direction == "out"), Decimal(0))
    return {
        "filename": parsed.filename,
        "header_row": parsed.header_row,
        "headers": parsed.headers,
        "mapping": parsed.mapping,
        "columns": {name: (parsed.headers[index] if index < len(parsed.headers) else "") for name, index in parsed.mapping.items()},
        "sample": parsed.sample,
        "line_count": len(parsed.lines),
        "period_from": parsed.period_from.isoformat() if parsed.period_from else None,
        "period_to": parsed.period_to.isoformat() if parsed.period_to else None,
        "money_in": float(money_in),
        "money_out": float(money_out),
        "opening_balance": float(parsed.opening_balance) if parsed.opening_balance is not None else None,
        "closing_balance": float(parsed.closing_balance) if parsed.closing_balance is not None else None,
        "newest_first": parsed.newest_first,
        "balance_checked": parsed.balance_checked,
        "balance_breaks": parsed.balance_breaks,
        "balanced": parsed.balanced,
        "skipped_rows": parsed.skipped_rows,
        "issues": [{"row": issue.row, "message": issue.message, "severity": issue.severity} for issue in parsed.issues],
        "first_lines": [
            {"row": line.row, "date": line.date.isoformat(), "description": line.description, "direction": line.direction, "amount": float(line.amount)}
            for line in parsed.lines[:8]
        ],
    }
