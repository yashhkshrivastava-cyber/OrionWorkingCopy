"""The bank account: balance, ledger, forecast, entries, statement import and reconciliation.

The balance is never stored. It is the opening balance (typed in by hand, once) plus every movement since the opening date, and a movement
is read from wherever Orion already holds it through the view ``orion_ods.bank_movement``:

* a client's payment of a bill (a Committed revenue entry), an expense (a Committed expense entry) and GST paid on bills are Orion's own
  records. They are never typed again here, so a payment reversed on a bill, or an expense cancelled, changes the balance by itself.
* interest, other income, bank charges, loans, tax and anything else with no record elsewhere is a ``bank_entry``, made here and never deleted
  (a wrong one is voided with a reason).

A bank statement is uploaded to check the book against the bank: each statement line is matched to one movement (or several, for a deposit that
pays several bills) with ``bank_match``, and the lines nothing matches are shown, so that what is missing from Orion, or from the bank, is seen.
Everything is written only here, and every change is recorded in ``bank_audit``.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import re
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

import psycopg2.errors
from psycopg2.extras import execute_values

from app import bank_match, bank_statement
from app.database import db_cursor
from app.idempotency import Idempotency

logger = logging.getLogger(__name__)

PAISA = Decimal("0.01")
MAX_AMOUNT = Decimal("99999999999.99")

#: Money in that has no record elsewhere in Orion, and money out. The key is stored; the label is shown.
ENTRY_CATEGORIES: dict[str, dict[str, str]] = {
    "in": {
        "interest": "Interest earned",
        "other_income": "Other income",
        "loan_in": "Loan received",
        "owner_capital": "Capital introduced",
        "other_receipt": "Receipt with no bill (advance, deposit)",
        "refund": "Refund or reversal received",
        "other_in": "Other money in",
    },
    "out": {
        "bank_charges": "Bank charges",
        "tax": "Income tax or TDS paid",
        "gst_other": "GST paid (not recorded on a bill)",
        "statutory": "PF, ESI and other statutory dues (not recorded on a bill)",
        "salary": "Salary and wages",
        "loan_repayment": "Loan repayment",
        "owner_drawings": "Owner withdrawal",
        "other_out": "Other money out",
    },
}
#: What the other parts of Orion put into the ledger.
SYSTEM_CATEGORIES = {"client_receipt": "Client payment", "expense": "Expense", "gst_payment": "GST paid on a bill", "statutory_payment": "EPFO / ESIC paid on a bill", "payroll": "Salary (pay run)"}
CATEGORY_LABELS = {**SYSTEM_CATEGORIES, **ENTRY_CATEGORIES["in"], **ENTRY_CATEGORIES["out"]}
#: Earnings other than clients' payments: these are what "interest and other income" on the dashboards adds up.
INCOME_CATEGORIES = ("interest", "other_income")
#: Money that comes in with no bill behind it is an entry, with a reason: it is never typed into the generic forms (which refuse a Committed receipt with no bill).
NOTE_REQUIRED = ("other_receipt",)
SOURCES = ("revenue", "expense", "gst", "statutory", "entry", "payroll")
SOURCE_LABELS = {"revenue": "Client payment", "expense": "Expense", "gst": "GST paid", "statutory": "EPFO / ESIC paid", "entry": "Entry", "payroll": "Salary"}

PAGE_MAX = 200


class BankError(ValueError):
    """Something the person can fix: the message is shown to them as it is."""


class BankConflict(BankError):
    """Someone else got there first, or the state has changed."""


# ----------------------------------------------------------------------------------------------------------------------- helpers


def _rows(cur) -> list[dict[str, Any]]:
    names = [c[0] for c in cur.description]
    return [dict(zip(names, row)) for row in cur.fetchall()]


def _row(cur) -> Optional[dict[str, Any]]:
    found = _rows(cur)
    return found[0] if found else None


def _dec(value: Any, label: str) -> Decimal:
    try:
        out = Decimal(str(value).replace(",", "").strip())
        if not out.is_finite() or abs(out) > MAX_AMOUNT * 10:  # also keeps quantize from overflowing on 1e400
            raise BankError(f"{label} must be a number below {MAX_AMOUNT:,.0f}.")
        return out.quantize(PAISA)
    except (InvalidOperation, ValueError):
        raise BankError(f"{label} must be a number.") from None


def _amount(value: Any, label: str = "Amount") -> Decimal:
    out = _dec(value, label)
    if out <= 0:
        raise BankError(f"{label} must be more than zero.")
    if out > MAX_AMOUNT:
        raise BankError(f"{label} is too large.")
    return out


def _date(value: Any, label: str = "Date") -> date:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        raise BankError(f"{label} is not a valid date.") from None


def _opt_int(value: Any, label: str = "Account") -> Optional[int]:
    if value in (None, "", "all"):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        raise BankError(f"{label} is not valid.") from None


def _text(value: Any, label: str, limit: int, required: bool = False) -> Optional[str]:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if required and not text:
        raise BankError(f"{label} is required.")
    if len(text) > limit:
        raise BankError(f"{label} is too long (at most {limit} characters).")
    return text or None


def _inr(value: Any) -> str:
    return f"₹{Decimal(str(value)):,.2f}"


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, date):
        return value.isoformat()
    return value


def financial_year_start(day: date) -> date:
    """Indian financial year: 1 April."""
    return date(day.year if day.month >= 4 else day.year - 1, 4, 1)


def _audit(cur, user_id: Optional[int], action: str, detail: dict[str, Any]) -> None:
    cur.execute(
        "INSERT INTO orion_ods.bank_audit (user_id, action, detail) VALUES (%s, %s, %s::jsonb)",
        (user_id, action, json.dumps(_jsonable(detail))),
    )


ACCOUNT_COLUMNS = (
    "account_id, account_name, account_kind, bank_name, account_last4, opening_balance, opening_date, low_balance_floor, created_timestamp, last_updated_timestamp"
)


def _account_row(cur, lock: bool = False, account_id: Optional[int] = None) -> Optional[dict[str, Any]]:
    """One account: the one asked for, or, with none named, the first (the default account)."""
    where = "WHERE account_id = %s " if account_id else ""
    cur.execute(
        f"SELECT {ACCOUNT_COLUMNS} FROM orion_ods.bank_account {where}ORDER BY account_id LIMIT 1" + (" FOR UPDATE" if lock else ""),
        (account_id,) if account_id else (),
    )
    return _row(cur)


def _need_account(cur, lock: bool = False, account_id: Optional[int] = None) -> dict[str, Any]:
    account = _account_row(cur, lock, account_id)
    if not account:
        if account_id:
            raise BankError("That account does not exist.")
        raise BankError("Set up the bank account first: enter its opening balance on the Account tab.")
    return account


def _accounts(cur, account_id: Optional[int] = None) -> list[dict[str, Any]]:
    """The accounts a figure covers: the one asked for, or all of them."""
    if account_id:
        found = _account_row(cur, account_id=account_id)
        if not found:
            raise BankError("That account does not exist.")
        return [found]
    cur.execute(f"SELECT {ACCOUNT_COLUMNS} FROM orion_ods.bank_account ORDER BY account_id")
    return _rows(cur)


def _balance(cur, accounts: Any, as_of: Optional[date] = None) -> Decimal:
    """For each account, its opening balance plus every movement from its opening date to ``as_of`` (today); added up."""
    total = Decimal(0)
    for account in [accounts] if isinstance(accounts, dict) else accounts:
        cur.execute(
            "SELECT COALESCE(SUM(CASE WHEN direction = 'in' THEN amount ELSE -amount END), 0) FROM orion_ods.bank_movement "
            "WHERE account_id = %s AND move_date >= %s AND move_date <= %s",
            (account["account_id"], account["opening_date"], as_of or date.today()),
        )
        total += Decimal(account["opening_balance"]) + Decimal(cur.fetchone()[0])
    return total


def _pseudo(accounts: list[dict[str, Any]]) -> dict[str, Any]:
    """The accounts in scope shown as one: a single account as it is, several as "All accounts"."""
    if len(accounts) == 1:
        return accounts[0]
    return {
        "account_id": None, "account_name": f"All accounts ({len(accounts)})", "account_kind": "all", "bank_name": None, "account_last4": None,
        "opening_balance": sum((Decimal(a["opening_balance"]) for a in accounts), Decimal(0)), "opening_date": min(a["opening_date"] for a in accounts),
    }


def meta() -> dict[str, Any]:
    """The lists the screens draw their choices from, so the labels live in one place."""
    return {
        "entry_categories": {d: [{"key": k, "label": v} for k, v in cats.items()] for d, cats in ENTRY_CATEGORIES.items()},
        "category_labels": CATEGORY_LABELS,
        "source_labels": SOURCE_LABELS,
        "income_categories": list(INCOME_CATEGORIES),
    }


# ------------------------------------------------------------------------------------------------------------------------ account


def get_account(account_id: Optional[int] = None) -> dict[str, Any]:
    """One account (the first, unless one is named) and its balance today, or ``{"configured": False}`` before any account exists."""
    with db_cursor() as cur:
        account = _account_row(cur, account_id=account_id)
        if not account:
            return {"configured": False}
        cur.execute("SELECT COUNT(*) FROM orion_ods.bank_entry WHERE voided_timestamp IS NULL AND account_id = %s", (account["account_id"],))
        entries = cur.fetchone()[0]
        return {"configured": True, **account, "balance": _balance(cur, account), "entry_count": entries}


def list_accounts() -> dict[str, Any]:
    """Every account with its balance today, and the total across them."""
    with db_cursor() as cur:
        accounts = _accounts(cur)
        shown = [{**a, "balance": _balance(cur, a)} for a in accounts]
    return {"configured": bool(shown), "accounts": shown, "total": sum((a["balance"] for a in shown), Decimal(0))}


def preview_account_change(opening_balance: Any, opening_date: Any, account_id: Optional[int] = None) -> dict[str, Any]:
    """What the balance would become, for the confirmation screen."""
    new_balance = _dec(opening_balance, "Opening balance")
    new_date = _date(opening_date, "Opening date")
    with db_cursor() as cur:
        account = _account_row(cur, account_id=account_id)
        if not account:
            return {"current_balance": None, "new_balance": new_balance}
        after = {"account_id": account["account_id"], "opening_balance": new_balance, "opening_date": new_date}
        return {
            "current_balance": _balance(cur, account),
            "new_balance": _balance(cur, after),
            "opening_balance": account["opening_balance"],
            "opening_date": account["opening_date"],
        }


def save_account(data: dict[str, Any], user_id: Optional[int], confirm: bool = False, account_id: Optional[int] = None, create: bool = False) -> dict[str, Any]:
    """Create an account (the first, or another with ``create``) or change one. Changing the opening balance or its date moves every balance Orion
    shows, so it needs ``confirm``, is audited with the old and new figures, and cannot move the opening date past a line already matched."""
    name = _text(data.get("account_name"), "Account name", 80, required=True)
    kind = data.get("account_kind") or "bank"
    if kind not in ("bank", "cash"):
        raise BankError("An account is a bank account or a cash account.")
    bank = _text(data.get("bank_name"), "Bank", 80)
    last4 = _text(data.get("account_last4"), "Last four digits", 4)
    if last4 and not re.fullmatch(r"[0-9]{4}", last4):
        raise BankError("Give the last four digits of the account number, or leave it empty.")
    opening = _dec(data.get("opening_balance"), "Opening balance")
    if abs(opening) > MAX_AMOUNT:
        raise BankError("Opening balance is too large.")
    opening_date = _date(data.get("opening_date"), "Opening date")
    if opening_date > date.today():
        raise BankError("The opening date cannot be in the future.")
    # The minimum balance is optional. Left out of the request it stays as it was; sent empty it is cleared.
    sent_floor = "low_balance_floor" in data
    floor = None
    if sent_floor and str(data.get("low_balance_floor") if data.get("low_balance_floor") is not None else "").strip() != "":
        floor = _dec(data.get("low_balance_floor"), "Minimum balance")
        if abs(floor) > MAX_AMOUNT:
            raise BankError("Minimum balance is too large.")
    with db_cursor(commit=True) as cur:
        if create:
            cur.execute("LOCK TABLE orion_ods.bank_account IN SHARE ROW EXCLUSIVE MODE")
        account = None if create else _account_row(cur, lock=True, account_id=account_id)
        if account_id and not account and not create:
            raise BankError("That account does not exist.")
        if not account:
            cur.execute(
                "INSERT INTO orion_ods.bank_account (account_name, account_kind, bank_name, account_last4, opening_balance, opening_date, low_balance_floor, created_by) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING account_id",
                (name, kind, bank, last4, opening, opening_date, floor, user_id),
            )
            account_id = cur.fetchone()[0]
            _audit(cur, user_id, "account.create", {"account_id": account_id, "kind": kind, "opening_balance": opening, "opening_date": opening_date, "account_name": name})
        else:
            account_id = account["account_id"]
            if kind != account["account_kind"]:
                cur.execute("SELECT COUNT(*) FROM orion_ods.bank_statement_line WHERE account_id = %s", (account_id,))
                if cur.fetchone()[0]:
                    raise BankError("This account has statement lines, so it cannot change from a bank to a cash account.")
            changed = Decimal(account["opening_balance"]) != opening or account["opening_date"] != opening_date
            if changed and not confirm:
                raise BankConflict("Changing the opening balance changes every balance shown. Confirm the change to go ahead.")
            if changed and opening_date > account["opening_date"]:
                cur.execute(
                    "SELECT COUNT(*) FROM orion_ods.bank_match m JOIN orion_ods.bank_statement_line l ON l.line_id = m.line_id "
                    "WHERE l.line_date < %s AND l.account_id = %s",
                    (opening_date, account_id),
                )
                if cur.fetchone()[0]:
                    raise BankError("Some statement lines before that date are already matched. Unmatch them before moving the opening date later.")
            new_floor = floor if sent_floor else account["low_balance_floor"]
            cur.execute(
                "UPDATE orion_ods.bank_account SET account_name = %s, account_kind = %s, bank_name = %s, account_last4 = %s, opening_balance = %s, "
                "opening_date = %s, low_balance_floor = %s, last_updated_timestamp = CURRENT_TIMESTAMP WHERE account_id = %s",
                (name, kind, bank, last4, opening, opening_date, new_floor, account_id),
            )
            _audit(
                cur, user_id, "account.update",
                {
                    "account_id": account_id,
                    "from": {"opening_balance": account["opening_balance"], "opening_date": account["opening_date"], "account_name": account["account_name"], "low_balance_floor": account["low_balance_floor"]},
                    "to": {"opening_balance": opening, "opening_date": opening_date, "account_name": name, "low_balance_floor": new_floor},
                },
            )
    return get_account(account_id)


# ------------------------------------------------------------------------------------------------------------------------ ledger


def _page(limit: Any, page: Any) -> tuple[int, int]:
    try:
        size = max(1, min(int(limit or 50), PAGE_MAX))
        number = max(1, int(page or 1))
    except (TypeError, ValueError):
        raise BankError("The page is not valid.") from None
    return size, number


def _search_pattern(q: Any) -> Optional[str]:
    text = re.sub(r"[%_]", " ", str(q or "")).strip()
    return f"%{text[:60]}%" if text else None


def entry_totals(cur, start: Optional[date], end: Optional[date], categories: tuple[str, ...]) -> dict[str, float]:
    """What the bank book's own entries (not voided) of these categories add up to between two days, inclusive; either end may be open. Read by the profit and
    loss for the lines that only the bank knows (bank charges, interest, tax). It takes a cursor so the caller decides who may see it."""
    where, params = ["voided_timestamp IS NULL", "category = ANY(%s)"], [list(categories)]
    if start:
        where.append("entry_date >= %s")
        params.append(start)
    if end:
        where.append("entry_date <= %s")
        params.append(end)
    cur.execute("SELECT category, COALESCE(SUM(amount), 0) FROM orion_ods.bank_entry WHERE " + " AND ".join(where) + " GROUP BY 1", params)
    return {str(category): float(total) for category, total in cur.fetchall()}


def ledger(
    *, date_from: Any = None, date_to: Any = None, direction: Optional[str] = None, category: Optional[str] = None,
    source: Optional[str] = None, q: Optional[str] = None, reconciled: Optional[str] = None, oldest_first: bool = False,
    limit: Any = 50, page: Any = 1, account_id: Optional[int] = None,
) -> dict[str, Any]:
    """The book: every movement from the opening date to today with the balance after each, newest first. The running balance counts every
    movement of the accounts in view (one, or all), with each account's opening balance counted from its opening date, so it is the same
    whatever filter is on."""
    where, params = _ledger_filters(date_from, date_to, direction, category, source, q, reconciled)
    size, number = _page(limit, page)
    order = "ASC" if oldest_first else "DESC"
    with db_cursor() as cur:
        if not _accounts(cur, account_id):
            return {"configured": False, "rows": [], "total": 0}
        cur.execute(
            f"""
            WITH acc AS (
                SELECT account_id, account_name, account_kind, opening_balance, opening_date FROM orion_ods.bank_account
                 WHERE (%(account)s::int IS NULL OR account_id = %(account)s::int)
            ), mv AS (
                SELECT m.*, CASE WHEN m.direction = 'in' THEN m.amount ELSE -m.amount END AS signed, a.account_name, a.account_kind
                  FROM orion_ods.bank_movement m JOIN acc a ON a.account_id = m.account_id
                 WHERE m.move_date >= a.opening_date AND m.move_date <= CURRENT_DATE
            ), run AS (
                SELECT mv.*,
                       (SELECT COALESCE(SUM(opening_balance), 0) FROM acc WHERE opening_date <= mv.move_date)
                       + SUM(mv.signed) OVER (ORDER BY mv.move_date, mv.source, mv.source_ref ROWS UNBOUNDED PRECEDING) AS balance
                  FROM mv
            )
            SELECT run.source, run.source_ref, run.move_date, run.direction, run.amount, run.category, run.detail, run.counterparty,
                   run.description, run.reference, run.bill_code, run.balance, bm.line_id, run.account_id, run.account_name, run.account_kind,
                   COUNT(*) OVER () AS total_rows,
                   SUM(CASE WHEN run.direction = 'in' THEN run.amount ELSE 0 END) OVER () AS total_in,
                   SUM(CASE WHEN run.direction = 'out' THEN run.amount ELSE 0 END) OVER () AS total_out
              FROM run
              LEFT JOIN orion_ods.bank_match bm ON bm.source = run.source AND bm.source_ref = run.source_ref
             WHERE {where}
             ORDER BY run.move_date {order}, run.source {order}, run.source_ref {order}
             LIMIT %(limit)s OFFSET %(offset)s
            """,
            {"account": account_id, **params, "limit": size, "offset": (number - 1) * size},
        )
        found = _rows(cur)
    total = found[0]["total_rows"] if found else 0
    totals = {"in": found[0]["total_in"] if found else 0, "out": found[0]["total_out"] if found else 0}
    rows = []
    for item in found:
        for key in ("total_rows", "total_in", "total_out"):
            item.pop(key, None)
        item["reconciled"] = item.pop("line_id") is not None
        item["category_label"] = CATEGORY_LABELS.get(item["category"], item["category"])
        item["source_label"] = SOURCE_LABELS.get(item["source"], item["source"])
        rows.append(item)
    return {"configured": True, "rows": rows, "total": total, "page": number, "page_size": size, "totals": totals}


def _ledger_filters(date_from, date_to, direction, category, source, q, reconciled) -> tuple[str, dict[str, Any]]:
    clauses: list[str] = ["TRUE"]
    params: dict[str, Any] = {}

    def ask(value: Any) -> str:
        name = f"p{len(params)}"
        params[name] = value
        return f"%({name})s"

    if date_from:
        clauses.append(f"run.move_date >= {ask(_date(date_from, 'From date'))}")
    if date_to:
        clauses.append(f"run.move_date <= {ask(_date(date_to, 'To date'))}")
    if direction:
        if direction not in ("in", "out"):
            raise BankError("Direction must be in or out.")
        clauses.append(f"run.direction = {ask(direction)}")
    if category:
        clauses.append(f"run.category = {ask(str(category)[:40])}")
    if source:
        if source not in SOURCES:
            raise BankError("That kind of movement does not exist.")
        clauses.append(f"run.source = {ask(source)}")
    if reconciled:
        if reconciled not in ("yes", "no"):
            raise BankError("Reconciled must be yes or no.")
        clauses.append("bm.line_id IS NOT NULL" if reconciled == "yes" else "bm.line_id IS NULL")
    pattern = _search_pattern(q)
    if pattern:
        like = ask(pattern)
        clauses.append(f"(run.counterparty ILIKE {like} OR run.description ILIKE {like} OR run.reference ILIKE {like} OR run.detail ILIKE {like})")
    return " AND ".join(clauses), params


def _safe_cell(value: Any) -> Any:
    """A spreadsheet runs a cell that starts with = + - @ as a formula; text a person typed must not be able to."""
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


def ledger_csv(**filters: Any) -> str:
    """The ledger (with the filters on) as a CSV the accountant can open, oldest first."""
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["Date", "Kind", "Category", "Counterparty", "Description", "Reference", "Money in", "Money out", "Balance", "Reconciled"])
    number = 1
    while True:
        result = ledger(**{**filters, "oldest_first": True, "limit": PAGE_MAX, "page": number})
        for row in result["rows"]:
            writer.writerow([
                row["move_date"].isoformat(), row["source_label"], row["category_label"], _safe_cell(row["counterparty"]),
                _safe_cell(row["description"]), _safe_cell(row["reference"]),
                f"{row['amount']:.2f}" if row["direction"] == "in" else "", f"{row['amount']:.2f}" if row["direction"] == "out" else "",
                f"{row['balance']:.2f}", "Yes" if row["reconciled"] else "No",
            ])
        if number * result.get("page_size", PAGE_MAX) >= result["total"]:
            break
        number += 1
    return out.getvalue()


# ----------------------------------------------------------------------------------------------------------------------- summary


def summary(account_id: Optional[int] = None) -> dict[str, Any]:
    """The overview: balance, this month and this financial year, interest and other income, what is not yet reconciled. For one account, or
    (with none named) all of them added together, each counted from its own opening date."""
    today = date.today()
    fy = financial_year_start(today)
    month = today.replace(day=1)
    with db_cursor() as cur:
        accounts = _accounts(cur, account_id)
        if not accounts:
            return {"configured": False}
        ids = [a["account_id"] for a in accounts]
        cur.execute(
            """
            SELECT COALESCE(SUM(CASE WHEN m.direction = 'in' THEN m.amount ELSE -m.amount END), 0) AS net,
                   COALESCE(SUM(CASE WHEN m.direction = 'in'  AND m.move_date >= %(month)s THEN m.amount END), 0) AS month_in,
                   COALESCE(SUM(CASE WHEN m.direction = 'out' AND m.move_date >= %(month)s THEN m.amount END), 0) AS month_out,
                   COALESCE(SUM(CASE WHEN m.direction = 'in'  AND m.move_date >= %(fy)s THEN m.amount END), 0) AS fy_in,
                   COALESCE(SUM(CASE WHEN m.direction = 'out' AND m.move_date >= %(fy)s THEN m.amount END), 0) AS fy_out,
                   COALESCE(SUM(CASE WHEN m.category = 'interest' AND m.move_date >= %(fy)s THEN m.amount END), 0) AS fy_interest,
                   COALESCE(SUM(CASE WHEN m.category = 'other_income' AND m.move_date >= %(fy)s THEN m.amount END), 0) AS fy_other_income,
                   COALESCE(SUM(CASE WHEN m.category = 'bank_charges' AND m.move_date >= %(fy)s THEN m.amount END), 0) AS fy_charges,
                   COALESCE(SUM(CASE WHEN m.category = 'client_receipt' AND m.move_date >= %(fy)s THEN m.amount END), 0) AS fy_client_receipts,
                   COUNT(*) AS movements
              FROM orion_ods.bank_movement m JOIN orion_ods.bank_account a ON a.account_id = m.account_id
             WHERE m.account_id = ANY(%(ids)s) AND m.move_date >= a.opening_date AND m.move_date <= %(today)s
            """,
            {"month": month, "fy": fy, "ids": ids, "today": today},
        )
        k = _row(cur)
        cur.execute(
            "SELECT COUNT(*) AS n, COALESCE(SUM(CASE WHEN m.direction = 'in' THEN m.amount ELSE -m.amount END), 0) AS net "
            "FROM orion_ods.bank_movement m JOIN orion_ods.bank_account a ON a.account_id = m.account_id "
            "LEFT JOIN orion_ods.bank_match b ON b.source = m.source AND b.source_ref = m.source_ref "
            "WHERE m.account_id = ANY(%s) AND m.move_date >= a.opening_date AND m.move_date <= %s AND b.match_id IS NULL "
            "AND a.account_kind = 'bank'",
            (ids, today),
        )
        loose_book = _row(cur)
        cur.execute(
            "SELECT COUNT(*) FILTER (WHERE status = 'Unmatched') AS unmatched, COUNT(*) FILTER (WHERE status = 'Matched') AS matched, "
            "COUNT(*) FILTER (WHERE status = 'Ignored') AS ignored, MIN(line_date) AS first_line, MAX(line_date) AS last_line "
            "FROM orion_ods.bank_statement_line WHERE account_id = ANY(%s)",
            (ids,),
        )
        lines = _row(cur)
        cur.execute(
            "SELECT import_id, filename, uploaded_timestamp, period_from, period_to, closing_statement_balance "
            "FROM orion_ods.bank_statement_import WHERE account_id = ANY(%s) ORDER BY import_id DESC LIMIT 1",
            (ids,),
        )
        last_import = _row(cur)
        broken = _exception_count(cur, ids)
        per_account = [{"account_id": a["account_id"], "account_name": a["account_name"], "account_kind": a["account_kind"], "balance": _balance(cur, a)} for a in accounts]
    shown = _pseudo(accounts)
    balance = sum((a["balance"] for a in per_account), Decimal(0))
    return {
        "configured": True,
        "account": {key: shown.get(key) for key in ("account_id", "account_name", "account_kind", "bank_name", "account_last4", "opening_balance", "opening_date")},
        "accounts": per_account,
        "as_of": today,
        "balance": balance,
        "month": {"from": month, "money_in": k["month_in"], "money_out": k["month_out"], "net": Decimal(k["month_in"]) - Decimal(k["month_out"])},
        "financial_year": {
            "from": fy, "money_in": k["fy_in"], "money_out": k["fy_out"], "net": Decimal(k["fy_in"]) - Decimal(k["fy_out"]),
            "client_receipts": k["fy_client_receipts"], "interest": k["fy_interest"], "other_income": k["fy_other_income"],
            "bank_charges": k["fy_charges"],
            "interest_and_other_income": Decimal(k["fy_interest"]) + Decimal(k["fy_other_income"]),
        },
        "movements": k["movements"],
        "reconciliation": {
            "book_unmatched": loose_book["n"], "book_unmatched_net": loose_book["net"],
            "lines_unmatched": lines["unmatched"], "lines_matched": lines["matched"], "lines_ignored": lines["ignored"],
            "statement_from": lines["first_line"], "statement_to": lines["last_line"],
            "changed_after_matching": broken,
        },
        "last_import": last_import,
    }


def series(months: Any = 12, account_id: Optional[int] = None) -> dict[str, Any]:
    """Money in, money out and the closing balance for each month, and where the money came from and went to."""
    try:
        count = max(1, min(int(months), 36))
    except (TypeError, ValueError):
        raise BankError("Months must be a number.") from None
    today = date.today()
    first = today.replace(day=1)
    for _ in range(count - 1):
        first = (first - timedelta(days=1)).replace(day=1)
    with db_cursor() as cur:
        accounts = _accounts(cur, account_id)
        if not accounts:
            return {"configured": False, "months": [], "categories": []}
        ids = [a["account_id"] for a in accounts]
        first = max(first, min(a["opening_date"] for a in accounts).replace(day=1))
        base = {"ids": ids, "first": first, "today": today}
        cur.execute(
            """
            SELECT date_trunc('month', m.move_date)::date AS month,
                   SUM(CASE WHEN m.direction = 'in' THEN m.amount ELSE 0 END) AS money_in,
                   SUM(CASE WHEN m.direction = 'out' THEN m.amount ELSE 0 END) AS money_out,
                   SUM(CASE WHEN m.category = 'client_receipt' THEN m.amount ELSE 0 END) AS client_receipts,
                   SUM(CASE WHEN m.category IN ('interest', 'other_income') THEN m.amount ELSE 0 END) AS other_income,
                   SUM(CASE WHEN m.category = 'interest' THEN m.amount ELSE 0 END) AS interest
              FROM orion_ods.bank_movement m JOIN orion_ods.bank_account a ON a.account_id = m.account_id
             WHERE m.account_id = ANY(%(ids)s) AND m.move_date >= %(first)s AND m.move_date >= a.opening_date AND m.move_date <= %(today)s GROUP BY 1
            """,
            base,
        )
        by_month = {r["month"]: r for r in _rows(cur)}
        cur.execute(
            "SELECT COALESCE(SUM(CASE WHEN m.direction = 'in' THEN m.amount ELSE -m.amount END), 0) FROM orion_ods.bank_movement m "
            "JOIN orion_ods.bank_account a ON a.account_id = m.account_id "
            "WHERE m.account_id = ANY(%(ids)s) AND m.move_date >= a.opening_date AND m.move_date < %(first)s",
            base,
        )
        # an account's opening balance joins the total in the month it opens
        running = sum((Decimal(a["opening_balance"]) for a in accounts if a["opening_date"] < first), Decimal(0)) + Decimal(cur.fetchone()[0])
        opens = {}
        for a in accounts:
            if a["opening_date"] >= first:
                key = a["opening_date"].replace(day=1)
                opens[key] = opens.get(key, Decimal(0)) + Decimal(a["opening_balance"])
        cur.execute(
            "SELECT m.category, m.direction, SUM(m.amount) AS total, COUNT(*) AS n FROM orion_ods.bank_movement m "
            "JOIN orion_ods.bank_account a ON a.account_id = m.account_id "
            "WHERE m.account_id = ANY(%(ids)s) AND m.move_date >= %(first)s AND m.move_date >= a.opening_date AND m.move_date <= %(today)s GROUP BY 1, 2 ORDER BY 3 DESC",
            base,
        )
        categories = [
            {**r, "label": CATEGORY_LABELS.get(r["category"], r["category"])} for r in _rows(cur)
        ]
    out = []
    cursor_month = first
    while cursor_month <= today:
        row = by_month.get(cursor_month, {})
        money_in, money_out = Decimal(row.get("money_in") or 0), Decimal(row.get("money_out") or 0)
        running += money_in - money_out + opens.get(cursor_month, Decimal(0))
        out.append({
            "month": cursor_month, "money_in": money_in, "money_out": money_out, "net": money_in - money_out, "closing_balance": running,
            "client_receipts": row.get("client_receipts") or 0, "other_income": row.get("other_income") or 0, "interest": row.get("interest") or 0,
        })
        cursor_month = (cursor_month + timedelta(days=32)).replace(day=1)
    return {"configured": True, "months": out, "categories": categories}


def breakdown(date_from: date, date_to: date, account_id: Optional[int] = None) -> list[dict[str, Any]]:
    """Money in and out by category over a period: where the money came from and where it went."""
    with db_cursor() as cur:
        accounts = _accounts(cur, account_id)
        if not accounts:
            return []
        cur.execute(
            "SELECT m.category, m.direction, SUM(m.amount) AS total, COUNT(*) AS n FROM orion_ods.bank_movement m "
            "JOIN orion_ods.bank_account a ON a.account_id = m.account_id "
            "WHERE m.account_id = ANY(%s) AND m.move_date >= %s AND m.move_date >= a.opening_date AND m.move_date <= %s GROUP BY 1, 2 ORDER BY 3 DESC",
            ([a["account_id"] for a in accounts], date_from, min(date_to, date.today())),
        )
        return [{**r, "label": CATEGORY_LABELS.get(r["category"], r["category"])} for r in _rows(cur)]


def other_income(date_from: date, date_to: date, limit: int = 200, account_id: Optional[int] = None) -> list[dict[str, Any]]:
    """Interest and other income received in a period, newest first: what is on top of clients' payments."""
    with db_cursor() as cur:
        accounts = _accounts(cur, account_id)
        if not accounts:
            return []
        cur.execute(
            "SELECT m.move_date, m.category, m.counterparty, m.description, m.reference, m.amount FROM orion_ods.bank_movement m "
            "JOIN orion_ods.bank_account a ON a.account_id = m.account_id "
            "WHERE m.account_id = ANY(%s) AND m.category = ANY(%s) AND m.direction = 'in' AND m.move_date >= %s AND m.move_date >= a.opening_date "
            "AND m.move_date <= %s ORDER BY m.move_date DESC, m.source_ref DESC LIMIT %s",
            ([a["account_id"] for a in accounts], list(INCOME_CATEGORIES), date_from, min(date_to, date.today()), limit),
        )
        return [{**r, "category_label": CATEGORY_LABELS.get(r["category"], r["category"])} for r in _rows(cur)]


# ---------------------------------------------------------------------------------------------------------------------- forecast


def forecast(*, include_overdue: bool = False, weeks: int = 13) -> dict[str, Any]:
    """Where the balance is heading, from what Orion already knows is coming: bills clients are yet to pay, costs still to come, and GST still
    to pay (estimated for the 20th of the month after the bill). Money overdue is shown on its own and left out of the projection unless asked."""
    today = date.today()
    horizon = today + timedelta(days=7 * weeks)
    with db_cursor() as cur:
        accounts = _accounts(cur)  # what is expected is not yet in an account, so the forecast is of all of them together
        if not accounts:
            return {"configured": False}
        balance = _balance(cur, accounts)
        cur.execute(
            "SELECT source, source_ref, due_date, direction, amount, category, counterparty, description, reference "
            "FROM orion_ods.bank_expected WHERE due_date <= %s ORDER BY due_date, source, source_ref",
            (horizon,),
        )
        items = _rows(cur)
    overdue = [i for i in items if i["due_date"] < today]
    upcoming = [i for i in items if i["due_date"] >= today]
    for item in items:
        item["category_label"] = CATEGORY_LABELS.get(item["category"], item["category"])
    week_rows = []
    running = balance + (sum((_signed(i) for i in overdue), Decimal(0)) if include_overdue else Decimal(0))
    lowest = {"balance": running, "week_start": today}
    for index in range(weeks):
        start = today + timedelta(days=7 * index)
        end = start + timedelta(days=6)
        inside = [i for i in upcoming if start <= i["due_date"] <= end]
        money_in = sum((Decimal(i["amount"]) for i in inside if i["direction"] == "in"), Decimal(0))
        money_out = sum((Decimal(i["amount"]) for i in inside if i["direction"] == "out"), Decimal(0))
        running += money_in - money_out
        week_rows.append({"week_start": start, "week_end": end, "money_in": money_in, "money_out": money_out, "balance": running})
        if running < lowest["balance"]:
            lowest = {"balance": running, "week_start": start}

    def total(rows: list[dict[str, Any]], direction: str) -> Decimal:
        return sum((Decimal(i["amount"]) for i in rows if i["direction"] == direction), Decimal(0))

    def window(days: int) -> dict[str, Any]:
        inside = [i for i in upcoming if i["due_date"] <= today + timedelta(days=days)]
        money_in, money_out = total(inside, "in"), total(inside, "out")
        return {"days": days, "money_in": money_in, "money_out": money_out, "projected_balance": balance + money_in - money_out}

    return {
        "configured": True,
        "as_of": today,
        "balance": balance,
        "include_overdue": include_overdue,
        "overdue": {"money_in": total(overdue, "in"), "money_out": total(overdue, "out"), "count": len(overdue), "items": overdue[:25]},
        "windows": [window(30), window(60), window(90)],
        "weeks": week_rows,
        "lowest": lowest,
        "upcoming": upcoming[:25],
        "note": "This is only what Orion knows is coming. Anything not yet entered as a bill, an expected payment or an expected expense is not in it.",
    }


#: How far ahead the minimum balance is looked at.
LOW_BALANCE_DAYS = 14


def alerts() -> list[dict[str, Any]]:
    """What deserves a look about the balance, from the minimum each account may have been given (``low_balance_floor``): an account below its minimum now,
    and the accounts together expected to fall below their minimums within two weeks (from what Orion already knows is coming, with overdue money left out).
    Nothing is enforced; with no minimum set there is nothing to say. Most urgent first."""
    with db_cursor() as cur:
        accounts = _accounts(cur)
        with_floor = [a for a in accounts if a.get("low_balance_floor") is not None]
        if not with_floor:
            return []
        balances = {a["account_id"]: _balance(cur, a) for a in accounts}
    found: list[dict[str, Any]] = []
    for account in with_floor:
        floor, balance = Decimal(account["low_balance_floor"]), balances[account["account_id"]]
        if balance < floor:
            found.append({
                "key": f"below:{account['account_id']}", "level": "critical", "account_id": account["account_id"], "account_name": account["account_name"],
                "title": f"{account['account_name']} is below its minimum balance",
                "detail": f"It holds {_inr(balance)} now; the minimum is {_inr(floor)}.", "balance": balance, "floor": floor, "date": None,
            })
    total_floor = sum((Decimal(a["low_balance_floor"]) for a in with_floor), Decimal(0))
    now_total = sum(balances.values(), Decimal(0))
    ahead = forecast(include_overdue=False, weeks=LOW_BALANCE_DAYS // 7)
    if ahead.get("configured") and now_total >= total_floor:
        low = ahead["lowest"]
        if Decimal(low["balance"]) < total_floor:
            found.append({
                "key": "projected", "level": "warning", "account_id": None, "account_name": None,
                "title": f"The balance is expected to fall below the minimum within {LOW_BALANCE_DAYS} days",
                "detail": (
                    f"Across the accounts, from {_inr(now_total)} now to {_inr(low['balance'])} in the week of {low['week_start']:%d %b}; the minimums add up to "
                    f"{_inr(total_floor)}. This is only what Orion already knows is coming."
                ),
                "balance": Decimal(low["balance"]), "floor": total_floor, "date": low["week_start"],
            })
    return found


def _signed(item: dict[str, Any]) -> Decimal:
    return Decimal(item["amount"]) if item["direction"] == "in" else -Decimal(item["amount"])


# ----------------------------------------------------------------------------------------------------------------------- entries


def _entry_json(row: dict[str, Any]) -> dict[str, Any]:
    out = _jsonable(dict(row))
    out["category_label"] = CATEGORY_LABELS.get(out["category"], out["category"])
    return out


def get_entry(entry_id: int) -> Optional[dict[str, Any]]:
    with db_cursor() as cur:
        cur.execute(
            "SELECT entry_id, entry_date, direction, amount, category, counterparty, description, reference, statement_line_id, "
            "created_by, created_timestamp, voided_by, voided_timestamp, void_reason FROM orion_ods.bank_entry WHERE entry_id = %s",
            (entry_id,),
        )
        found = _row(cur)
    return _entry_json(found) if found else None


def create_entry(data: dict[str, Any], user_id: Optional[int], idem: Optional[Idempotency] = None) -> dict[str, Any]:
    """Money in or out with no record elsewhere in Orion. With ``line_id`` it is made from an unmatched statement line (its date, direction
    and amount) and matched to it in the same step. With ``idem`` the same request arriving again records nothing and returns the first answer."""
    direction = data.get("direction")
    if direction not in ("in", "out"):
        raise BankError("Choose whether the money came in or went out.")
    category = data.get("category")
    if category not in ENTRY_CATEGORIES[direction]:
        raise BankError("Choose a category that fits.")
    amount = _amount(data.get("amount"))
    when = _date(data.get("entry_date"), "Date")
    if when > date.today():
        raise BankError("The date cannot be in the future. An entry records money that has already moved.")
    counterparty = _text(data.get("counterparty"), "From or to", 120)
    description = _text(data.get("description"), "Note", 300)
    reference = _text(data.get("reference"), "Reference", 120)
    if category in NOTE_REQUIRED and not description:
        raise BankError("Say what this receipt is for (who paid, and why there is no bill), so it can be explained later.")
    line_id = data.get("line_id")
    with db_cursor(commit=True) as cur:
        if idem is not None:
            prior = idem.claim(cur)
            if prior is not None:
                return prior
        line = _lock_line(cur, int(line_id)) if line_id is not None else None
        account = _need_account(cur, account_id=line["account_id"] if line else _opt_int(data.get("account_id")))
        if when < account["opening_date"]:
            raise BankError(f"That is before the opening date ({account['opening_date']:%d %b %Y}): it is already inside the opening balance.")
        if line is not None:
            if line["status"] != "Unmatched":
                raise BankConflict("That statement line is already matched or ignored.")
            if line["direction"] != direction or Decimal(line["amount"]) != amount or line["line_date"] != when:
                raise BankError("An entry made from a statement line must have the line's date, direction and amount.")
        cur.execute(
            "INSERT INTO orion_ods.bank_entry (account_id, entry_date, direction, amount, category, counterparty, description, reference, "
            "statement_line_id, created_by) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING entry_id",
            (account["account_id"], when, direction, amount, category, counterparty, description, reference, line_id, user_id),
        )
        entry_id = cur.fetchone()[0]
        if line:
            cur.execute(
                "INSERT INTO orion_ods.bank_match (line_id, source, source_ref, amount, method, matched_by) VALUES (%s, 'entry', %s, %s, 'created', %s)",
                (line["line_id"], str(entry_id), amount, user_id),
            )
            cur.execute("UPDATE orion_ods.bank_statement_line SET status = 'Matched', ignore_reason = NULL WHERE line_id = %s", (line["line_id"],))
        _audit(cur, user_id, "entry.create", {"entry_id": entry_id, "account_id": account["account_id"], "date": when, "direction": direction, "amount": amount, "category": category, "line_id": line_id})
        result = {"entry_id": entry_id, "account_id": account["account_id"], "entry_date": when, "direction": direction, "amount": amount, "category": category,
                  "category_label": CATEGORY_LABELS[category], "counterparty": counterparty, "description": description, "reference": reference,
                  "statement_line_id": line_id}
        result = _jsonable(result)
        if idem is not None:
            idem.remember(cur, result)
    return result


def void_entry(entry_id: int, reason: Any, user_id: Optional[int]) -> dict[str, Any]:
    """A wrong entry stops counting; it is never deleted. A statement line matched to it goes back to unmatched."""
    why = _text(reason, "Reason", 300, required=True)
    if len(why or "") < 5:
        raise BankError("Say why in a few words, so the history makes sense later.")
    with db_cursor(commit=True) as cur:
        cur.execute("SELECT entry_id, voided_timestamp, amount, category FROM orion_ods.bank_entry WHERE entry_id = %s FOR UPDATE", (entry_id,))
        found = _row(cur)
        if not found:
            raise BankError("That entry does not exist.")
        if found["voided_timestamp"] is not None:
            raise BankConflict("That entry has already been voided.")
        cur.execute(
            "UPDATE orion_ods.bank_entry SET voided_by = %s, voided_timestamp = CURRENT_TIMESTAMP, void_reason = %s WHERE entry_id = %s",
            (user_id, why, entry_id),
        )
        cur.execute("DELETE FROM orion_ods.bank_match WHERE source = 'entry' AND source_ref = %s RETURNING line_id", (str(entry_id),))
        for (line_id,) in cur.fetchall():
            _refresh_line_status(cur, line_id)
        _audit(cur, user_id, "entry.void", {"entry_id": entry_id, "amount": found["amount"], "category": found["category"], "reason": why})
    return get_entry(entry_id) or {}


def activity(limit: Any = 50) -> list[dict[str, Any]]:
    """Who did what, newest first."""
    try:
        size = max(1, min(int(limit), 200))
    except (TypeError, ValueError):
        raise BankError("The limit is not valid.") from None
    with db_cursor() as cur:
        cur.execute(
            "SELECT a.audit_id, a.occurred, a.user_id, u.username, a.action, a.detail FROM orion_ods.bank_audit a "
            "LEFT JOIN orion_ods.app_user u ON u.id = a.user_id ORDER BY a.audit_id DESC LIMIT %s",
            (size,),
        )
        return _rows(cur)


# ----------------------------------------------------------------------------------------------------------------- statement import


def _need_statement_account(cur, account_id: Optional[int], lock: bool = False) -> dict[str, Any]:
    """A statement belongs to a bank account. A cash account has none: it is counted, not reconciled."""
    account = _need_account(cur, lock, account_id)
    if account["account_kind"] != "bank":
        raise BankError("A cash account has no bank statement.")
    return account


def preview_statement(
    filename: str, content: bytes, mapping: Optional[dict[str, int]] = None, header_row: Optional[int] = None, account_id: Optional[int] = None,
) -> dict[str, Any]:
    """Read a statement without saving anything: what it holds, how the columns were understood, whether it adds up, what is already known."""
    try:
        parsed = bank_statement.parse_statement(filename, content, mapping=mapping, header_row=header_row)
    except bank_statement.StatementError as exc:
        raise BankError(str(exc)) from exc
    result = bank_statement.describe(parsed)
    prints = bank_statement.fingerprints(parsed.lines)
    with db_cursor() as cur:
        account = _need_statement_account(cur, account_id)
        known = 0
        if prints:
            cur.execute("SELECT COUNT(*) FROM orion_ods.bank_statement_line WHERE account_id = %s AND fingerprint = ANY(%s)", (account["account_id"], prints))
            known = cur.fetchone()[0]
        cur.execute("SELECT import_id, uploaded_timestamp FROM orion_ods.bank_statement_import WHERE file_sha256 = %s", (parsed.sha256,))
        same = _row(cur)
        before_opening = sum(1 for line in parsed.lines if line.date < account["opening_date"])
        book_at_start = None
        if parsed.opening_balance is not None and parsed.period_from:
            book_at_start = _balance(cur, account, parsed.period_from - timedelta(days=1))
    result.update({
        "known_lines": known,
        "new_lines": len(parsed.lines) - known,
        "already_imported": bool(same),
        "before_opening_date": before_opening,
        "opening_date": account["opening_date"].isoformat(),
        "book_balance_before_period": float(book_at_start) if book_at_start is not None else None,
        "sha256": parsed.sha256,
        "can_import": not any(i.severity == "error" for i in parsed.issues) and bool(parsed.lines) and not same,
    })
    return result


def import_statement(
    filename: str, content: bytes, user_id: Optional[int], mapping: Optional[dict[str, int]] = None, header_row: Optional[int] = None,
    account_id: Optional[int] = None,
) -> dict[str, Any]:
    """Save a statement's lines (the file is read again here; nothing the browser says about its contents is trusted), skip any line already
    held from an earlier upload, set aside lines before the opening date, and match what can be matched with certainty."""
    try:
        parsed = bank_statement.parse_statement(filename, content, mapping=mapping, header_row=header_row)
    except bank_statement.StatementError as exc:
        raise BankError(str(exc)) from exc
    errors = [i.message for i in parsed.issues if i.severity == "error"]
    if errors:
        raise BankError("The statement cannot be imported: " + errors[0])
    if not parsed.lines:
        raise BankError("The file has no transactions in it.")
    prints = bank_statement.fingerprints(parsed.lines)
    with db_cursor(commit=True) as cur:
        account = _need_statement_account(cur, account_id, lock=True)
        cur.execute("SELECT import_id FROM orion_ods.bank_statement_import WHERE file_sha256 = %s AND account_id = %s", (parsed.sha256, account["account_id"]))
        if cur.fetchone():
            raise BankConflict("This exact file has already been imported.")
        cur.execute(
            "INSERT INTO orion_ods.bank_statement_import (account_id, filename, file_sha256, uploaded_by, period_from, period_to, line_count, "
            "opening_statement_balance, closing_statement_balance) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING import_id",
            (account["account_id"], filename[:200], parsed.sha256, user_id, parsed.period_from, parsed.period_to, len(parsed.lines),
             parsed.opening_balance, parsed.closing_balance),
        )
        import_id = cur.fetchone()[0]
        values = []
        for line, print_ in zip(parsed.lines, prints):
            early = line.date < account["opening_date"]
            values.append((
                import_id, account["account_id"], line.date, (line.description or "")[:500], (line.reference or "")[:200] or None,
                line.direction, line.amount, line.balance, print_,
                "Ignored" if early else "Unmatched", "Before the opening date: already inside the opening balance" if early else None,
            ))
        inserted = execute_values(
            cur,
            "INSERT INTO orion_ods.bank_statement_line (import_id, account_id, line_date, description, reference, direction, amount, balance_after, "
            "fingerprint, status, ignore_reason) VALUES %s ON CONFLICT (account_id, fingerprint) DO NOTHING RETURNING line_id",
            values,
            fetch=True,
        )
        new_count = len(inserted)
        cur.execute(
            "UPDATE orion_ods.bank_statement_import SET new_count = %s, duplicate_count = %s WHERE import_id = %s",
            (new_count, len(values) - new_count, import_id),
        )
        matched = _auto_match(cur, user_id, account["account_id"])
        _audit(cur, user_id, "statement.import", {
            "import_id": import_id, "account_id": account["account_id"], "filename": filename[:200], "lines": len(values), "new": new_count, "duplicates": len(values) - new_count,
            "auto_matched": matched,
        })
    return {"import_id": import_id, "line_count": len(values), "new_count": new_count, "duplicate_count": len(values) - new_count, "auto_matched": matched}


def imports(account_id: Optional[int] = None) -> list[dict[str, Any]]:
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT i.import_id, i.account_id, i.filename, i.uploaded_timestamp, u.username AS uploaded_by, i.period_from, i.period_to, i.line_count, i.new_count,
                   i.duplicate_count, i.opening_statement_balance, i.closing_statement_balance,
                   (SELECT COUNT(*) FROM orion_ods.bank_statement_line l WHERE l.import_id = i.import_id AND l.status = 'Matched') AS matched
              FROM orion_ods.bank_statement_import i LEFT JOIN orion_ods.app_user u ON u.id = i.uploaded_by
              WHERE (%s::int IS NULL OR i.account_id = %s::int)
             ORDER BY i.import_id DESC LIMIT 100
            """,
            (account_id, account_id),
        )
        return _rows(cur)


def remove_import(import_id: int, user_id: Optional[int]) -> None:
    """Take back a wrong upload (the wrong columns, the wrong file). Refused while any of its lines is matched: unmatch those first."""
    with db_cursor(commit=True) as cur:
        cur.execute("SELECT import_id, filename FROM orion_ods.bank_statement_import WHERE import_id = %s FOR UPDATE", (import_id,))
        found = _row(cur)
        if not found:
            raise BankError("That upload does not exist.")
        cur.execute("SELECT COUNT(*) FROM orion_ods.bank_statement_line WHERE import_id = %s AND status = 'Matched'", (import_id,))
        if cur.fetchone()[0]:
            raise BankError("Some lines of this upload are matched. Unmatch them first.")
        cur.execute("DELETE FROM orion_ods.bank_statement_line WHERE import_id = %s", (import_id,))
        removed = cur.rowcount
        cur.execute("DELETE FROM orion_ods.bank_statement_import WHERE import_id = %s", (import_id,))
        _audit(cur, user_id, "statement.remove", {"import_id": import_id, "filename": found["filename"], "lines": removed})


# --------------------------------------------------------------------------------------------------------------------- matching


def _lock_line(cur, line_id: int) -> dict[str, Any]:
    cur.execute(
        "SELECT line_id, account_id, line_date, description, reference, direction, amount, status, ignore_reason FROM orion_ods.bank_statement_line "
        "WHERE line_id = %s FOR UPDATE",
        (line_id,),
    )
    found = _row(cur)
    if not found:
        raise BankError("That statement line does not exist.")
    return found


def _refresh_line_status(cur, line_id: int) -> None:
    cur.execute(
        "UPDATE orion_ods.bank_statement_line SET status = CASE WHEN EXISTS (SELECT 1 FROM orion_ods.bank_match WHERE line_id = %s) "
        "THEN 'Matched' ELSE 'Unmatched' END, ignore_reason = NULL WHERE line_id = %s AND status <> 'Ignored'",
        (line_id, line_id),
    )


def _open_movements(cur, start: date, end: date, account_id: Optional[int] = None) -> list[dict[str, Any]]:
    """Movements in the book nothing on the statement has been matched to yet, in one account (a line can only be a movement of its own account)."""
    cur.execute(
        "SELECT m.source, m.source_ref, m.move_date, m.direction, m.amount, m.category, m.detail, m.counterparty, m.description, m.reference, m.bill_code "
        "FROM orion_ods.bank_movement m LEFT JOIN orion_ods.bank_match b ON b.source = m.source AND b.source_ref = m.source_ref "
        "WHERE b.match_id IS NULL AND m.move_date >= %s AND m.move_date <= %s AND (%s::int IS NULL OR m.account_id = %s::int)",
        (start, end, account_id, account_id),
    )
    return _rows(cur)


def _auto_match(cur, user_id: Optional[int], account_id: Optional[int] = None) -> int:
    """Match what is certain, account by account."""
    cur.execute(
        "SELECT DISTINCT account_id FROM orion_ods.bank_statement_line WHERE status = 'Unmatched' AND (%s::int IS NULL OR account_id = %s::int) ORDER BY 1",
        (account_id, account_id),
    )
    return sum(_auto_match_account(cur, user_id, row[0]) for row in cur.fetchall())


def _auto_match_account(cur, user_id: Optional[int], account_id: int) -> int:
    cur.execute(
        "SELECT line_id, line_date, description, reference, direction, amount FROM orion_ods.bank_statement_line "
        "WHERE status = 'Unmatched' AND account_id = %s ORDER BY line_date, line_id",
        (account_id,),
    )
    lines = _rows(cur)
    if not lines:
        return 0
    margin = timedelta(days=bank_match.AUTO_DAYS)
    movements = _open_movements(cur, min(item["line_date"] for item in lines) - margin, max(item["line_date"] for item in lines) + margin, account_id)
    made = 0
    for line, movement in bank_match.auto_pairs(lines, movements):
        cur.execute(
            "INSERT INTO orion_ods.bank_match (line_id, source, source_ref, amount, method, matched_by) VALUES (%s, %s, %s, %s, 'auto', %s) "
            "ON CONFLICT (source, source_ref) DO NOTHING RETURNING match_id",
            (line["line_id"], movement["source"], movement["source_ref"], movement["amount"], user_id),
        )
        if cur.fetchone():
            cur.execute("UPDATE orion_ods.bank_statement_line SET status = 'Matched' WHERE line_id = %s", (line["line_id"],))
            made += 1
    return made


def run_auto_match(user_id: Optional[int], account_id: Optional[int] = None) -> dict[str, Any]:
    """Match everything that is certain, again (new entries or payments may have been made since the upload)."""
    with db_cursor(commit=True) as cur:
        made = _auto_match(cur, user_id, account_id)
        if made:
            _audit(cur, user_id, "match.auto", {"matched": made})
    return {"matched": made}


def lines(
    *, status: Optional[str] = None, q: Optional[str] = None, date_from: Any = None, date_to: Any = None, limit: Any = 50, page: Any = 1,
    account_id: Optional[int] = None,
) -> dict[str, Any]:
    """Statement lines, newest first, each with what it is matched to; unmatched ones also carry Orion's guess at what they are."""
    clauses, params = ["TRUE"], []
    if account_id:
        clauses.append("l.account_id = %s")
        params.append(account_id)
    if status:
        if status not in ("Unmatched", "Matched", "Ignored"):
            raise BankError("Status must be Unmatched, Matched or Ignored.")
        clauses.append("l.status = %s")
        params.append(status)
    if date_from:
        clauses.append("l.line_date >= %s")
        params.append(_date(date_from, "From date"))
    if date_to:
        clauses.append("l.line_date <= %s")
        params.append(_date(date_to, "To date"))
    pattern = _search_pattern(q)
    if pattern:
        clauses.append("(l.description ILIKE %s OR l.reference ILIKE %s)")
        params.extend([pattern, pattern])
    size, number = _page(limit, page)
    where = " AND ".join(clauses)
    with db_cursor() as cur:
        cur.execute(
            f"""
            SELECT l.line_id, l.import_id, l.account_id, l.line_date, l.description, l.reference, l.direction, l.amount, l.balance_after, l.status, l.ignore_reason,
                   COALESCE(json_agg(json_build_object('source', m.source, 'source_ref', m.source_ref, 'amount', m.amount, 'method', m.method,
                            'counterparty', mv.counterparty, 'description', mv.description, 'reference', mv.reference, 'bill_code', mv.bill_code,
                            'move_date', mv.move_date, 'category', mv.category))
                            FILTER (WHERE m.match_id IS NOT NULL), '[]'::json) AS matches,
                   COUNT(*) OVER () AS total_rows
              FROM orion_ods.bank_statement_line l
              LEFT JOIN orion_ods.bank_match m ON m.line_id = l.line_id
              LEFT JOIN orion_ods.bank_movement mv ON mv.source = m.source AND mv.source_ref = m.source_ref
             WHERE {where}
             GROUP BY l.line_id
             ORDER BY l.line_date DESC, l.line_id DESC
             LIMIT %s OFFSET %s
            """,
            [*params, size, (number - 1) * size],
        )
        found = _rows(cur)
    total = found[0]["total_rows"] if found else 0
    for item in found:
        item.pop("total_rows", None)
        item["guess"] = bank_match.classify(item) if item["status"] == "Unmatched" else None
        if item["guess"]:
            item["guess"]["category_label"] = CATEGORY_LABELS.get(item["guess"]["category"], item["guess"]["category"])
    return {"rows": found, "total": total, "page": number, "page_size": size}


def suggestions(line_id: int) -> dict[str, Any]:
    """For one unmatched line: the movements it could be (best first), groups of movements that add up to it, and a guess at what it is."""
    with db_cursor() as cur:
        cur.execute(
            "SELECT line_id, account_id, line_date, description, reference, direction, amount, status FROM orion_ods.bank_statement_line WHERE line_id = %s",
            (line_id,),
        )
        line = _row(cur)
        if not line:
            raise BankError("That statement line does not exist.")
        if line["status"] == "Matched":
            raise BankConflict("That statement line is already matched.")
        margin = timedelta(days=bank_match.SUGGEST_DAYS)
        movements = _open_movements(cur, line["line_date"] - margin, line["line_date"] + margin, line["account_id"])
    options = [
        {"movement": _jsonable(c.movement), "score": c.score, "days": c.days, "reasons": list(c.reasons)}
        for c in bank_match.candidates(line, movements)
    ]
    groups = [_jsonable(group) for group in bank_match.combinations_for(line, movements)] if not options else []
    guess = bank_match.classify(line)
    if guess:
        guess["category_label"] = CATEGORY_LABELS.get(guess["category"], guess["category"])
    return {"line": _jsonable(line), "candidates": options, "combinations": groups, "guess": guess, "categories": meta()["entry_categories"][line["direction"]]}


def match_line(line_id: int, refs: list[dict[str, Any]], user_id: Optional[int]) -> dict[str, Any]:
    """Match a line to the movement(s) the person chose. Their amounts must add up to the line to the paisa."""
    if not refs or len(refs) > 10:
        raise BankError("Choose between one and ten movements.")
    with db_cursor(commit=True) as cur:
        line = _lock_line(cur, line_id)
        if line["status"] != "Unmatched":
            raise BankConflict("That statement line is already matched or ignored.")
        total = Decimal(0)
        seen = set()
        for ref in refs:
            source, source_ref = str(ref.get("source", "")), str(ref.get("source_ref", ""))
            if source not in SOURCES or not source_ref or (source, source_ref) in seen:
                raise BankError("One of the chosen movements is not valid.")
            seen.add((source, source_ref))
            cur.execute(
                "SELECT direction, amount, account_id FROM orion_ods.bank_movement WHERE source = %s AND source_ref = %s",
                (source, source_ref),
            )
            movement = _row(cur)
            if not movement:
                raise BankConflict("One of those movements no longer exists. Reload and try again.")
            if movement["direction"] != line["direction"]:
                raise BankError("A payment received cannot be matched to money paid out, or the other way round.")
            if movement["account_id"] != line["account_id"]:
                raise BankError("That movement is in another account: a statement line can only be matched to money of its own account.")
            total += Decimal(movement["amount"])
            try:
                cur.execute(
                    "INSERT INTO orion_ods.bank_match (line_id, source, source_ref, amount, method, matched_by) VALUES (%s, %s, %s, %s, 'manual', %s)",
                    (line_id, source, source_ref, movement["amount"], user_id),
                )
            except psycopg2.errors.UniqueViolation:  # the whole save is rolled back by db_cursor
                raise BankConflict("One of those movements is already matched to another statement line.") from None
        if total != Decimal(line["amount"]):
            raise BankError(f"Those add up to {_inr(total)} but the statement line is {_inr(line['amount'])}. They must be exactly equal.")
        cur.execute("UPDATE orion_ods.bank_statement_line SET status = 'Matched' WHERE line_id = %s", (line_id,))
        _audit(cur, user_id, "match.manual", {"line_id": line_id, "amount": line["amount"], "to": [{"source": s, "ref": r} for s, r in seen]})
    return {"line_id": line_id, "matched": len(refs)}


def unmatch_line(line_id: int, user_id: Optional[int]) -> dict[str, Any]:
    with db_cursor(commit=True) as cur:
        line = _lock_line(cur, line_id)
        if line["status"] != "Matched":
            raise BankConflict("That statement line is not matched.")
        cur.execute("DELETE FROM orion_ods.bank_match WHERE line_id = %s RETURNING source, source_ref, method", (line_id,))
        removed = cur.fetchall()
        cur.execute("UPDATE orion_ods.bank_statement_line SET status = 'Unmatched', ignore_reason = NULL WHERE line_id = %s", (line_id,))
        _audit(cur, user_id, "match.remove", {"line_id": line_id, "was": [{"source": s, "ref": r, "method": m} for s, r, m in removed]})
    return {"line_id": line_id}


_EXCEPTION_SQL = """
    SELECT l.line_id, l.account_id, l.line_date, l.description, l.direction, l.amount AS line_amount,
           json_agg(json_build_object(
               'source', m.source, 'source_ref', m.source_ref, 'matched_amount', m.amount, 'now_amount', mv.amount, 'gone', mv.source IS NULL,
               'revenue_status', t.transaction_status, 'bill_code', t.bill_code, 'expense_status', e.transaction_status,
               'payment_reversed', ep.reversed_timestamp IS NOT NULL, 'run_reversed', sr.reversed_timestamp IS NOT NULL
           ) ORDER BY m.match_id) AS broken
      FROM orion_ods.bank_match m
      JOIN orion_ods.bank_statement_line l ON l.line_id = m.line_id
      LEFT JOIN orion_ods.bank_movement mv ON mv.source = m.source AND mv.source_ref = m.source_ref
      LEFT JOIN orion_ods.case_transaction t ON m.source = 'revenue' AND t.transaction_code = m.source_ref
      LEFT JOIN orion_ods.expense_payment ep ON m.source = 'expense' AND ep.payment_id::text = m.source_ref
      LEFT JOIN orion_ods.expense_transaction e ON e.expense_code = ep.expense_code
      LEFT JOIN orion_ods.salary_run sr ON m.source = 'payroll' AND sr.run_id::text = m.source_ref
     WHERE (mv.source IS NULL OR mv.amount <> m.amount) AND (%(account)s::int IS NULL OR l.account_id = %(account)s::int)
     GROUP BY l.line_id
"""


def _why_it_broke(item: dict[str, Any]) -> str:
    """In plain words, what happened to a movement after a statement line was matched to it."""
    if not item["gone"]:
        return f"its amount changed from {_inr(item['matched_amount'])} to {_inr(item['now_amount'])}"
    source = item["source"]
    if source == "revenue":
        status = item.get("revenue_status")
        if status == "Prospective":
            return "the payment was reversed on its bill"
        if status == "Cancelled":
            return "its bill was cancelled"
        return "the payment is no longer in the book"
    if source == "expense":
        if item.get("payment_reversed"):
            return "the expense payment was reversed"
        return "the expense payment is no longer in the book"
    if source == "payroll":
        return "the salary pay run was reversed" if item.get("run_reversed") else "the salary pay run is no longer in the book"
    if source == "gst":
        return "the GST payment was reversed"
    if source == "statutory":
        return "the EPFO / ESIC payment was reversed"
    return "the entry was voided"


def exceptions(account_id: Optional[int] = None) -> list[dict[str, Any]]:
    """Statement lines matched to something that has since changed in the book: a payment reversed on its bill, an expense cancelled, a GST payment
    reversed, an amount edited. The match no longer holds, so the line is shown here until a person returns it to unmatched (and the book and the bank
    are compared again), instead of looking reconciled when it is not."""
    with db_cursor() as cur:
        cur.execute(_EXCEPTION_SQL + " ORDER BY l.line_date DESC, l.line_id DESC", {"account": account_id})
        found = _rows(cur)
    for row in found:
        for item in row["broken"]:
            item["why"] = _why_it_broke(item)
        row["reason"] = "; ".join(sorted({i["why"] for i in row["broken"]}))
    return found


def _exception_count(cur, account_ids: list[int]) -> int:
    cur.execute("SELECT COUNT(*) FROM (" + _EXCEPTION_SQL.replace("%(account)s::int IS NULL OR l.account_id = %(account)s::int", "l.account_id = ANY(%(ids)s)") + ") x", {"ids": account_ids})
    return cur.fetchone()[0]


def clear_exception(line_id: int, user_id: Optional[int]) -> dict[str, Any]:
    """Return a line whose match no longer holds to unmatched, with what went wrong written to the history. Whatever is certain is then matched again
    (a payment that was reversed and recorded afresh matches the same line on its own)."""
    with db_cursor(commit=True) as cur:
        line = _lock_line(cur, line_id)
        cur.execute(_EXCEPTION_SQL.replace("GROUP BY l.line_id", "AND l.line_id = %(line)s GROUP BY l.line_id"), {"account": None, "line": line_id})
        found = _rows(cur)
        if not found:
            raise BankConflict("Nothing has changed since that line was matched.")
        broken = found[0]["broken"]
        cur.execute("DELETE FROM orion_ods.bank_match WHERE line_id = %s", (line_id,))
        cur.execute("UPDATE orion_ods.bank_statement_line SET status = 'Unmatched', ignore_reason = NULL WHERE line_id = %s", (line_id,))
        why = [{"source": i["source"], "ref": i["source_ref"], "why": _why_it_broke(i)} for i in broken]
        _audit(cur, user_id, "match.exception_cleared", {"line_id": line_id, "amount": line["amount"], "broken": why})
        rematched = _auto_match_account(cur, user_id, line["account_id"])
    return {"line_id": line_id, "rematched": rematched}


def ignore_line(line_id: int, reason: Any, user_id: Optional[int]) -> dict[str, Any]:
    """A line that is not the firm's movement to book (a transfer between the firm's own accounts, a duplicate): set aside with a reason."""
    why = _text(reason, "Reason", 200, required=True)
    with db_cursor(commit=True) as cur:
        line = _lock_line(cur, line_id)
        if line["status"] != "Unmatched":
            raise BankConflict("Only an unmatched line can be set aside.")
        cur.execute("UPDATE orion_ods.bank_statement_line SET status = 'Ignored', ignore_reason = %s WHERE line_id = %s", (why, line_id))
        _audit(cur, user_id, "line.ignore", {"line_id": line_id, "amount": line["amount"], "reason": why})
    return {"line_id": line_id}


def unignore_line(line_id: int, user_id: Optional[int]) -> dict[str, Any]:
    with db_cursor(commit=True) as cur:
        line = _lock_line(cur, line_id)
        if line["status"] != "Ignored":
            raise BankConflict("That line is not set aside.")
        account = _need_account(cur, account_id=line["account_id"])
        if line["line_date"] < account["opening_date"]:
            raise BankError("That line is before the opening date: it is already inside the opening balance.")
        cur.execute("UPDATE orion_ods.bank_statement_line SET status = 'Unmatched', ignore_reason = NULL WHERE line_id = %s", (line_id,))
        _audit(cur, user_id, "line.unignore", {"line_id": line_id})
    return {"line_id": line_id}


def entry_from_line(line_id: int, data: dict[str, Any], user_id: Optional[int], idem: Optional[Idempotency] = None) -> dict[str, Any]:
    """The line has no record in Orion (interest, a bank charge ...): make the entry from it and match the two in one step."""
    with db_cursor() as cur:
        line = _lock_line(cur, line_id)
    return create_entry({
        "direction": line["direction"], "amount": line["amount"], "entry_date": line["line_date"], "category": data.get("category"),
        "counterparty": data.get("counterparty"), "description": data.get("description") or line["description"],
        "reference": data.get("reference") or line["reference"], "line_id": line_id,
    }, user_id, idem)


def reconciliation(account_id: Optional[int] = None) -> dict[str, Any]:
    """Does the book agree with the bank? The balance on the latest statement against the book's balance on the same day, and what explains the
    difference: movements the bank does not show yet, statement lines the book does not hold. Whatever is left unexplained is a wrong opening
    balance or a missing period. It is of one account (the first, unless one is named); a cash account has no statement."""
    with db_cursor() as cur:
        account = _account_row(cur, account_id=account_id)
        if not account:
            return {"configured": False}
        if account["account_kind"] != "bank":
            return {"configured": True, "state": "no_statement", "cash": True, "account_id": account["account_id"]}
        opening, mine = account["opening_date"], account["account_id"]
        cur.execute(
            "SELECT line_date, balance_after FROM orion_ods.bank_statement_line WHERE balance_after IS NOT NULL AND line_date >= %s AND account_id = %s "
            "ORDER BY line_date DESC, line_id DESC LIMIT 1",
            (opening, mine),
        )
        last = _row(cur)
        if not last:
            cur.execute("SELECT COUNT(*) FROM orion_ods.bank_statement_line WHERE account_id = %s", (mine,))
            return {"configured": True, "state": "no_statement", "has_lines": bool(cur.fetchone()[0])}
        as_of = last["line_date"]
        statement_balance = Decimal(last["balance_after"])
        book_balance = _balance(cur, account, as_of)
        cur.execute(
            "SELECT COUNT(*) AS n, COALESCE(SUM(CASE WHEN m.direction = 'in' THEN m.amount ELSE 0 END), 0) AS money_in, "
            "COALESCE(SUM(CASE WHEN m.direction = 'out' THEN m.amount ELSE 0 END), 0) AS money_out "
            "FROM orion_ods.bank_movement m LEFT JOIN orion_ods.bank_match b ON b.source = m.source AND b.source_ref = m.source_ref "
            "WHERE b.match_id IS NULL AND m.move_date >= %s AND m.move_date <= %s AND m.account_id = %s",
            (opening, as_of, mine),
        )
        book_side = _row(cur)
        cur.execute(
            "SELECT COUNT(*) AS n, COALESCE(SUM(CASE WHEN direction = 'in' THEN amount ELSE 0 END), 0) AS money_in, "
            "COALESCE(SUM(CASE WHEN direction = 'out' THEN amount ELSE 0 END), 0) AS money_out "
            "FROM orion_ods.bank_statement_line WHERE status <> 'Matched' AND line_date >= %s AND line_date <= %s AND account_id = %s",
            (opening, as_of, mine),
        )
        bank_side = _row(cur)
        changed = _exception_count(cur, [mine])
    book_net = Decimal(book_side["money_in"]) - Decimal(book_side["money_out"])
    bank_net = Decimal(bank_side["money_in"]) - Decimal(bank_side["money_out"])
    # book = statement + (book items the bank lacks) - (bank items the book lacks); what is left over cannot be explained by unmatched items
    unexplained = book_balance - (statement_balance + book_net - bank_net)
    return {
        "configured": True,
        "account_id": mine,
        "changed_after_matching": changed,
        "state": "reconciled" if unexplained == 0 and book_side["n"] == 0 and bank_side["n"] == 0 and not changed else ("explained" if unexplained == 0 and not changed else "unexplained"),
        "as_of": as_of,
        "statement_balance": statement_balance,
        "book_balance": book_balance,
        "difference": book_balance - statement_balance,
        "book_only": {"count": book_side["n"], "money_in": book_side["money_in"], "money_out": book_side["money_out"], "net": book_net},
        "statement_only": {"count": bank_side["n"], "money_in": bank_side["money_in"], "money_out": bank_side["money_out"], "net": bank_net},
        "unexplained": unexplained,
    }


# ---------------------------------------------------------------------------------------------------------------- for the Copilot


def categorisation_candidates(limit: int = 40) -> list[dict[str, Any]]:
    """Unmatched lines Orion's own rules could not name: what the AI is asked about (never more than ``limit``)."""
    with db_cursor() as cur:
        cur.execute(
            "SELECT line_id, line_date, description, reference, direction, amount FROM orion_ods.bank_statement_line "
            "WHERE status = 'Unmatched' ORDER BY line_date DESC, line_id DESC LIMIT %s",
            (limit * 3,),
        )
        found = _rows(cur)
    return [line for line in found if bank_match.classify(line) is None][:limit]
