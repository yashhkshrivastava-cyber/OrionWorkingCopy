"""Payables: what the firm owes on expenses, and the payments that settle them.

A Committed expense is a cost taken on. The money leaves the bank when it is PAID, which may be later, in instalments, from different accounts. Each
payment is a row of ``orion_ods.expense_payment`` and this module is the only writer of that table. An expense is Unpaid, Part paid or Paid according to
the payments that have not been reversed; the status is worked out, never stored.

The bank reads the payments (the view ``bank_movement``), so recording one moves the balance of its account and reversing one moves it back. The Bank
module never records an expense payment a second time. A payment is a deliberate act, like a GST payment on a bill: it needs the confirmation, the day,
the amount (no more than is left), the account, and the amount the person saw as already paid (so two people cannot both settle the same expense),
and it is kept for ever (reversing one keeps it, with who and why).
"""

import logging
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Optional

from app.database import db_cursor
from app.idempotency import Idempotency

log = logging.getLogger(__name__)

ZERO = Decimal("0")
CENT = Decimal("0.01")
MAX_AMOUNT = Decimal("9999999999.99")
REFERENCE_MAX = 120
REASON_MIN = 5
REASON_MAX = 300
BUCKETS = ("not_due", "0-30", "31-60", "61-90", "90+")
BUCKET_LABELS = {"not_due": "Not yet due", "0-30": "0-30 days late", "31-60": "31-60 days late", "61-90": "61-90 days late", "90+": "Over 90 days late"}
STATUSES = ("Unpaid", "Part paid", "Paid")
PAGE_MAX = 200


class PayableError(ValueError):
    """Something the person can fix: shown to them as it is."""


class PayableConflict(PayableError):
    """The expense changed under the person, or the same thing was done twice."""


def _rows(cur) -> list[dict[str, Any]]:
    names = [d[0] for d in cur.description]
    return [dict(zip(names, row)) for row in cur.fetchall()]


def _row(cur) -> Optional[dict[str, Any]]:
    found = _rows(cur)
    return found[0] if found else None


def _inr(value: Any) -> str:
    amount = Decimal(str(value)).quantize(CENT)
    sign = "-" if amount < 0 else ""
    whole, _, frac = f"{abs(amount):.2f}".partition(".")
    head, tail = whole[:-3], whole[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    return f"{sign}₹{','.join(groups + [tail])}.{frac}"


def _money(value: Any, label: str) -> Decimal:
    try:
        amount = Decimal(str(value).strip())
        if not amount.is_finite():
            raise InvalidOperation
        amount = amount.quantize(CENT, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError, TypeError):
        raise PayableError(f"{label} must be a number.") from None
    if amount <= 0:
        raise PayableError(f"{label} must be more than zero.")
    if amount > MAX_AMOUNT:
        raise PayableError(f"{label} is too large.")
    return amount


def _day(value: Any) -> date:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value or "").strip()[:10])
    except ValueError:
        raise PayableError("Give the day the payment was made.") from None


def _total(expense: dict[str, Any]) -> Decimal:
    """What the expense came to, with tax and GST, to the paisa."""
    value = expense.get("amount_after_tax_gst")
    if value is None:
        value = expense.get("transaction_amount")
    return Decimal(str(value if value is not None else 0)).quantize(CENT, rounding=ROUND_HALF_UP)


def payment_status(total: Decimal, paid: Decimal) -> str:
    if paid <= 0:
        return "Unpaid"
    return "Paid" if paid >= total else "Part paid"


def bucket_of(days_late: int) -> str:
    """Where an unpaid amount sits in the ageing: by how many days past its due date (the transaction date when no due date was given)."""
    if days_late < 0:
        return "not_due"
    if days_late <= 30:
        return "0-30"
    if days_late <= 60:
        return "31-60"
    if days_late <= 90:
        return "61-90"
    return "90+"


_COLUMNS = """
    e.expense_code, e.case_code, cs.case_name, e.expense_type_code, et.expense_type_name, e.transaction_date, e.due_date,
    COALESCE(e.due_date, e.transaction_date) AS pay_by, e.transaction_description, e.transaction_status,
    e.amount_after_tax_gst, e.transaction_amount,
    COALESCE((SELECT SUM(p.amount) FROM orion_ods.expense_payment p WHERE p.expense_code = e.expense_code AND p.reversed_timestamp IS NULL), 0) AS paid
"""
_FROM = """
    FROM orion_ods.expense_transaction e
    LEFT JOIN orion_ods.case cs ON cs.case_code = e.case_code
    LEFT JOIN orion_ods.expense_type et ON et.expense_type_code = e.expense_type_code
"""


def _shape(row: dict[str, Any], today: date) -> dict[str, Any]:
    total = _total(row)
    paid = Decimal(str(row["paid"])).quantize(CENT)
    left = max(total - paid, ZERO)
    pay_by = row["pay_by"]
    days_late = (today - pay_by).days if pay_by else 0
    committed = row["transaction_status"] == "Committed"
    return {
        "expense_code": row["expense_code"],
        "case_code": row["case_code"],
        "case_name": row["case_name"],
        "expense_type": row["expense_type_name"],
        "description": row["transaction_description"],
        "transaction_date": row["transaction_date"],
        "due_date": row["due_date"],
        "pay_by": pay_by,
        "status": row["transaction_status"],
        "total": total,
        "paid": paid,
        "left": left,
        "payment_status": payment_status(total, paid) if committed else None,
        "days_late": days_late if committed and left > 0 else None,
        "bucket": bucket_of(days_late) if committed and left > 0 else None,
    }


def _payment_rows(cur, expense_code: str, *, lock: bool = False) -> list[dict[str, Any]]:
    cur.execute(
        """
        SELECT p.payment_id, p.amount, p.paid_date, p.reference, p.account_id, a.account_name, p.recorded_by, p.recorded_timestamp,
               p.reversed_by, p.reversed_timestamp, p.reversal_reason
          FROM orion_ods.expense_payment p
          LEFT JOIN orion_ods.bank_account a ON a.account_id = COALESCE(p.account_id, (SELECT MIN(account_id) FROM orion_ods.bank_account))
         WHERE p.expense_code = %s
         ORDER BY p.paid_date, p.payment_id
        """ + (" FOR UPDATE OF p" if lock else ""),
        (expense_code,),
    )
    return _rows(cur)


def get_expense(expense_code: str, today: Optional[date] = None) -> Optional[dict[str, Any]]:
    """One expense with what has been paid on it and every payment (reversed ones too, marked)."""
    today = today or date.today()
    with db_cursor() as cur:
        cur.execute(f"SELECT {_COLUMNS} {_FROM} WHERE e.expense_code = %s", (expense_code,))
        row = _row(cur)
        if not row:
            return None
        out = _shape(row, today)
        out["payments"] = [{**p, "reversed": p["reversed_timestamp"] is not None} for p in _payment_rows(cur, expense_code)]
    return out


def _left_sql() -> str:
    return "ROUND(COALESCE(x.amount_after_tax_gst, x.transaction_amount, 0), 2) - x.paid"


def list_payables(
    *, status: str = "open", bucket: Optional[str] = None, q: Optional[str] = None, page: Any = 1, limit: Any = 50, today: Optional[date] = None,
    case_code: Optional[str] = None,
) -> dict[str, Any]:
    """The Committed expenses: those with something still to pay (``open``, oldest due first) or those paid in full (``paid``, newest first).

    The ageing and the totals always cover every open expense, whatever the page, the search or the ageing group chosen, so they do not change as the
    list is filtered.
    """
    today = today or date.today()
    if status not in ("open", "paid"):
        raise PayableError("Choose open or paid.")
    if bucket is not None and bucket not in BUCKETS:
        raise PayableError("That ageing group does not exist.")
    try:
        size = min(max(int(limit), 1), PAGE_MAX)
        number = max(int(page), 1)
    except (TypeError, ValueError):
        raise PayableError("The page is not valid.") from None
    needle = str(q).strip()[:80] if q is not None and str(q).strip() else None
    base = f"SELECT {_COLUMNS} {_FROM} WHERE e.transaction_status = 'Committed' AND COALESCE(e.due_date, e.transaction_date) IS NOT NULL"
    chosen_case = str(case_code).strip() if case_code else None
    with db_cursor() as cur:
        cur.execute(f"SELECT * FROM ({base}) x WHERE {_left_sql()} > 0")
        open_rows = [_shape(r, today) for r in _rows(cur)]
        # The cases that have something owed, for the filter (always every open expense, whichever case is chosen).
        owed_cases: dict[Any, dict[str, Any]] = {}
        for r in open_rows:
            item = owed_cases.setdefault(r["case_code"], {"case_code": r["case_code"], "case_name": r["case_name"], "count": 0, "amount": ZERO})
            item["count"] += 1
            item["amount"] += r["left"]
        paid_rows: list[dict[str, Any]] = []
        paid_total = 0
        if status == "paid":
            like = None
            if needle:
                like = "%" + needle.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            where = f"{_left_sql()} <= 0" + (" AND x.case_code = %(case)s" if chosen_case else "") + (
                " AND (x.expense_code ILIKE %(like)s OR x.case_name ILIKE %(like)s OR x.expense_type_name ILIKE %(like)s OR x.transaction_description ILIKE %(like)s)"
                if like else ""
            )
            cur.execute(f"SELECT COUNT(*) FROM ({base}) x WHERE {where}", {"like": like, "case": chosen_case})
            paid_total = cur.fetchone()[0]
            cur.execute(
                f"SELECT * FROM ({base}) x WHERE {where} ORDER BY x.pay_by DESC, x.expense_code LIMIT %(n)s OFFSET %(o)s",
                {"like": like, "case": chosen_case, "n": size, "o": (number - 1) * size},
            )
            paid_rows = [_shape(r, today) for r in _rows(cur)]
    aged = {key: {"label": BUCKET_LABELS[key], "count": 0, "amount": ZERO} for key in BUCKETS}
    for r in open_rows:
        aged[r["bucket"]]["count"] += 1
        aged[r["bucket"]]["amount"] += r["left"]
    if status == "open":
        pool = [r for r in open_rows if (not bucket or r["bucket"] == bucket) and (not chosen_case or r["case_code"] == chosen_case)]
        if needle:
            lowered = needle.lower()
            pool = [r for r in pool if lowered in " ".join(str(r[k] or "") for k in ("expense_code", "case_name", "expense_type", "description")).lower()]
        pool.sort(key=lambda r: (r["pay_by"], r["expense_code"]))
        total = len(pool)
        items = pool[(number - 1) * size:number * size]
    else:
        total, items = paid_total, paid_rows
    return {
        "items": items,
        "total": total,
        "page": number,
        "limit": size,
        "summary": {
            "owed": sum((r["left"] for r in open_rows), ZERO),
            "overdue": sum((r["left"] for r in open_rows if r["bucket"] != "not_due"), ZERO),
            "open_count": len(open_rows),
            "due_in_7_days": sum((r["left"] for r in open_rows if r["bucket"] == "not_due" and (r["pay_by"] - today).days <= 7), ZERO),
        },
        "ageing": [{"bucket": key, **aged[key]} for key in BUCKETS],
        "cases": sorted(owed_cases.values(), key=lambda c: (c["case_code"] is None, str(c["case_name"] or "").lower())),
    }


def _lock_expense(cur, expense_code: str) -> dict[str, Any]:
    cur.execute(f"SELECT {_COLUMNS} {_FROM} WHERE e.expense_code = %s FOR UPDATE OF e", (expense_code,))
    row = _row(cur)
    if not row:
        raise PayableError("That expense does not exist.")
    return row


def _checked_account(cur, account_id: Any) -> tuple[Optional[int], Optional[dict[str, Any]]]:
    """The account a payment leaves from, and that account's row. None means the first account (as everywhere), and when there is no account at all
    the payment is kept with none (it is read as the first account once one exists)."""
    if account_id in (None, ""):
        cur.execute("SELECT account_id, opening_date FROM orion_ods.bank_account ORDER BY account_id LIMIT 1")
        found = _row(cur)
        return (found["account_id"] if found else None), found
    try:
        number = int(account_id)
    except (TypeError, ValueError):
        raise PayableError("That account is not valid.") from None
    cur.execute("SELECT account_id, opening_date FROM orion_ods.bank_account WHERE account_id = %s", (number,))
    found = _row(cur)
    if not found:
        raise PayableError("That account does not exist.")
    return number, found


def _pay(
    cur,
    expense_code: str,
    user_id: Optional[int],
    *,
    amount: Optional[Decimal],
    day: date,
    reference: Optional[str],
    account_id: Any,
    seen: Optional[Decimal],
    today: date,
    on_entry: bool = False,
) -> dict[str, Any]:
    """The payment itself, in the caller's transaction. ``amount`` None means all that is left; ``seen`` None skips the check against what the person saw
    (an expense that was entered a moment ago has nothing to have been seen). ``on_entry`` is a payment recorded together with the expense: with several
    accounts the account must be named, and a day before the account's opening is allowed (what was paid then is already inside the opening balance)."""
    row = _lock_expense(cur, expense_code)
    if row["transaction_status"] != "Committed":
        raise PayableError("Only an expense that has been incurred (Committed) can be paid. Set it to Committed first.")
    if on_entry and account_id in (None, ""):
        cur.execute("SELECT COUNT(*) FROM orion_ods.bank_account")
        if cur.fetchone()[0] > 1:
            raise PayableError("Choose the account it was paid from.")
    account, account_row = _checked_account(cur, account_id)
    if not on_entry and account_row and day < account_row["opening_date"]:
        raise PayableError(f"That is before the account's opening date ({account_row['opening_date']:%d %b %Y}): it is already inside the opening balance.")
    shaped = _shape(row, today)
    if seen is not None and shaped["paid"] != seen:
        raise PayableConflict(
            f"The payments on this expense were changed by someone else while you had it open ({_inr(shaped['paid'])} is now recorded as paid). "
            "Reload it to see where it stands."
        )
    if shaped["left"] <= 0:
        raise PayableError("This expense is already paid in full.")
    paying = shaped["left"] if amount is None else amount
    if paying > shaped["left"]:
        raise PayableError(f"Only {_inr(shaped['left'])} is left to pay on this expense.")
    cur.execute(
        """
        INSERT INTO orion_ods.expense_payment (expense_code, amount, paid_date, reference, account_id, recorded_by)
        VALUES (%s, %s, %s, %s, %s, %s) RETURNING payment_id
        """,
        (expense_code, paying, day, reference, account, user_id),
    )
    payment_id = cur.fetchone()[0]
    return {
        "payment_id": payment_id, "expense_code": expense_code, "amount": str(paying), "paid_date": day.isoformat(), "account_id": account,
        "reference": reference, "paid": str(shaped["paid"] + paying), "left": str(shaped["left"] - paying),
        "payment_status": payment_status(shaped["total"], shaped["paid"] + paying),
    }


def _reference(value: Optional[str]) -> Optional[str]:
    return " ".join(str(value or "").split())[:REFERENCE_MAX] or None


def record_payment(
    expense_code: str,
    user_id: Optional[int],
    *,
    confirm: bool = False,
    seen_paid: Any = None,
    amount: Any = None,
    paid_date: Any = None,
    reference: Optional[str] = None,
    account_id: Any = None,
    idem: Optional[Idempotency] = None,
    today: Optional[date] = None,
) -> dict[str, Any]:
    """Record a payment of an expense: an amount, on a day, from an account, with an optional reference.

    * ``confirm`` must be true: a request that did not come from the confirmation screen is refused;
    * ``seen_paid`` is how much had been paid when the person opened it; if it has changed since, nothing is written;
    * the amount is no more than is left, the day is not in the future and not before the account's opening date (it would already be inside the
      opening balance), and only a Committed expense can be paid (a Prospective one has not been incurred yet).

    With ``idem`` the same request arriving again records nothing and returns the first answer.
    """
    if not confirm:
        raise PayableError("Confirm the payment to continue.")
    if seen_paid is None:
        raise PayableError("Reload the page and try again: it is not clear what state you saw the expense in.")
    today = today or date.today()
    paying = _money(amount, "The amount")
    day = _day(paid_date)
    if day > today:
        raise PayableError("The day of the payment cannot be in the future. A payment records money that has already gone out.")
    try:
        seen = Decimal(str(seen_paid)).quantize(CENT, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        raise PayableError("The amount already paid is not a number.") from None
    with db_cursor(commit=True) as cur:
        if idem is not None:
            prior = idem.claim(cur)
            if prior is not None:
                return prior
        result = _pay(cur, expense_code, user_id, amount=paying, day=day, reference=_reference(reference), account_id=account_id, seen=seen, today=today)
        if idem is not None:
            idem.remember(cur, result)
    return result


def pay_on_entry(
    cur, expense_code: str, user_id: Optional[int], *, paid_date: Any, account_id: Any = None, reference: Optional[str] = None, today: Optional[date] = None,
) -> dict[str, Any]:
    """Pay in full the expense that has just been entered, in the transaction that entered it (so both are saved, or neither). The person chose this when
    they filled in the day it was paid; the day is not in the future."""
    today = today or date.today()
    day = _day(paid_date)
    if day > today:
        raise PayableError("The day it was paid cannot be in the future. A payment records money that has already gone out.")
    return _pay(cur, expense_code, user_id, amount=None, day=day, reference=_reference(reference), account_id=account_id, seen=None, today=today, on_entry=True)


def reverse_payment(payment_id: int, user_id: Optional[int], *, confirm: bool = False, reason: Any = None) -> dict[str, Any]:
    """Take a payment back, with the reason. It stays in the history, marked reversed, with who and when; the expense is owed again by what it covered
    and the money returns to the account it left."""
    if not confirm:
        raise PayableError("Confirm the reversal to continue.")
    why = " ".join(str(reason or "").split())
    if len(why) < REASON_MIN:
        raise PayableError(f"Say why the payment is being reversed (at least {REASON_MIN} characters).")
    why = why[:REASON_MAX]
    with db_cursor(commit=True) as cur:
        cur.execute("SELECT payment_id, expense_code, amount, reversed_timestamp FROM orion_ods.expense_payment WHERE payment_id = %s FOR UPDATE", (payment_id,))
        found = _row(cur)
        if not found:
            raise PayableError("That payment does not exist.")
        if found["reversed_timestamp"] is not None:
            raise PayableConflict("That payment has already been reversed. Reload the expense to see where it stands.")
        cur.execute(
            "UPDATE orion_ods.expense_payment SET reversed_by = %s, reversed_timestamp = CURRENT_TIMESTAMP, reversal_reason = %s WHERE payment_id = %s",
            (user_id, why, payment_id),
        )
    return {"payment_id": payment_id, "expense_code": found["expense_code"], "amount": str(found["amount"])}
