"""Payroll: salary reaches the bank in pay runs.

A month's salary lines (``employee_transaction``) are paid together by one bank transfer. A pay run is one row of ``orion_ods.salary_run``: the month, the
day, the account and the bank reference, with the lines it paid (``employee_transaction.salary_run_id``). What a run came to is the sum of its lines, never
stored. This module is the only writer of ``salary_run``, and the only thing that sets a line to paid or takes it back.

The bank reads the runs (the view ``bank_movement``), one movement per run, so one transfer on a statement matches one movement; recording a run moves the
balance of its account and reversing it moves it back. Marking salary paid is a deliberate act, like a payment on a bill: it needs the confirmation, the
lines chosen, the amount the person saw (so two people cannot both mark the same salary paid), the day and the account, and it is kept for ever (reversing
a run keeps it, with who and why, and the lines go back to unpaid).
"""

import logging
import re
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Optional

from app.database import db_cursor
from app.idempotency import Idempotency

log = logging.getLogger(__name__)

ZERO = Decimal("0")
CENT = Decimal("0.01")
REFERENCE_MAX = 120
REASON_MIN = 5
REASON_MAX = 300
MAX_LINES = 2000
MONTH = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


class PayrollError(ValueError):
    """Something the person can fix: shown to them as it is."""


class PayrollConflict(PayrollError):
    """The salary changed under the person, or the same thing was done twice."""


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


def _month(value: Any) -> str:
    text = str(value or "").strip()
    if not MONTH.match(text):
        raise PayrollError("Choose the month the salary is for.")
    return text


def _day(value: Any) -> date:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value or "").strip()[:10])
    except ValueError:
        raise PayrollError("Give the day the salary was paid.") from None


def _amount(value: Any, label: str) -> Decimal:
    try:
        number = Decimal(str(value).strip())
        if not number.is_finite():
            raise InvalidOperation
        return number.quantize(CENT, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError, TypeError):
        raise PayrollError(f"{label} must be a number.") from None


def months(limit: int = 36) -> list[dict[str, Any]]:
    """Each month that has salary lines: what was to be paid, what has been, and what is still to pay (the newest months first)."""
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT t.month_year,
                   COUNT(*) FILTER (WHERE t.salary_amount > 0) AS lines,
                   COALESCE(SUM(t.salary_amount) FILTER (WHERE t.salary_amount > 0), 0) AS total,
                   COUNT(*) FILTER (WHERE t.salary_run_id IS NOT NULL AND t.salary_amount > 0) AS paid_lines,
                   COALESCE(SUM(t.salary_amount) FILTER (WHERE t.salary_run_id IS NOT NULL AND t.salary_amount > 0), 0) AS paid_total,
                   COUNT(*) FILTER (WHERE t.salary_run_id IS NULL AND t.salary_paid = 'No' AND t.salary_amount > 0) AS unpaid_lines,
                   COALESCE(SUM(t.salary_amount) FILTER (WHERE t.salary_run_id IS NULL AND t.salary_paid = 'No' AND t.salary_amount > 0), 0) AS unpaid_total,
                   (SELECT COUNT(*) FROM orion_ods.salary_run r WHERE r.month_year = t.month_year AND r.reversed_timestamp IS NULL) AS runs
              FROM orion_ods.employee_transaction t
             WHERE t.month_year IS NOT NULL
             GROUP BY t.month_year
             ORDER BY t.month_year DESC
             LIMIT %s
            """,
            (min(max(int(limit), 1), 120),),
        )
        return _rows(cur)


def unpaid_lines(month_year: Any) -> dict[str, Any]:
    """The salary lines of a month that no pay run has paid: who, how much, and the case it was worked at (the case on the line, which an attendance register
    sets, or else the employee's own). ``cases`` lists those cases with what is unpaid at each, so a month can be paid one case at a time."""
    month = _month(month_year)
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT t.employee_transaction_code AS code, t.employee_code, e.employee_name, t.days_worked, t.salary_amount AS amount, t.transaction_date,
                   cs.case_code, cs.case_name
              FROM orion_ods.employee_transaction t
              LEFT JOIN orion_ods.employee e ON e.employee_code = t.employee_code
              LEFT JOIN orion_ods."case" cs ON cs.case_code = COALESCE(t.case_code, e.employee_case_code)
             WHERE t.month_year = %s AND t.salary_paid = 'No' AND t.salary_run_id IS NULL AND t.salary_amount > 0
             ORDER BY e.employee_name NULLS LAST, t.employee_transaction_code
            """,
            (month,),
        )
        lines = _rows(cur)
    total = sum((Decimal(str(line["amount"])) for line in lines), ZERO).quantize(CENT)
    by_case: dict[Any, dict[str, Any]] = {}
    for line in lines:
        entry = by_case.setdefault(line["case_code"], {"case_code": line["case_code"], "case_name": line["case_name"], "lines": 0, "total": ZERO})
        entry["lines"] += 1
        entry["total"] += Decimal(str(line["amount"]))
    cases = sorted(({**entry, "total": entry["total"].quantize(CENT)} for entry in by_case.values()), key=lambda e: (e["case_code"] is None, str(e["case_name"] or "").lower()))
    return {"month_year": month, "lines": lines, "count": len(lines), "total": total, "cases": cases}


_RUN_COLUMNS = """
    r.run_id, r.month_year, r.paid_date, r.reference, r.account_id, a.account_name, r.recorded_by, r.recorded_timestamp,
    r.reversed_by, r.reversed_timestamp, r.reversal_reason,
    (SELECT COUNT(*) FROM orion_ods.employee_transaction t WHERE t.salary_run_id = r.run_id) AS lines,
    COALESCE((SELECT ROUND(SUM(t.salary_amount), 2) FROM orion_ods.employee_transaction t WHERE t.salary_run_id = r.run_id), 0) AS total
"""
_RUN_FROM = """
    FROM orion_ods.salary_run r
    LEFT JOIN orion_ods.bank_account a ON a.account_id = COALESCE(r.account_id, (SELECT MIN(account_id) FROM orion_ods.bank_account))
"""


def runs(*, month_year: Any = None, limit: Any = 50) -> list[dict[str, Any]]:
    """The pay runs, newest first, reversed ones too (marked). Only counts and totals: the lines (who was paid what) stay in Operational Data."""
    where, params = "", []
    if month_year not in (None, ""):
        where = "WHERE r.month_year = %s"
        params.append(_month(month_year))
    try:
        size = min(max(int(limit), 1), 200)
    except (TypeError, ValueError):
        raise PayrollError("The page is not valid.") from None
    with db_cursor() as cur:
        cur.execute(f"SELECT {_RUN_COLUMNS} {_RUN_FROM} {where} ORDER BY r.paid_date DESC, r.run_id DESC LIMIT %s", (*params, size))
        found = _rows(cur)
    for item in found:
        item["reversed"] = item["reversed_timestamp"] is not None
    return found


def get_run(run_id: int) -> Optional[dict[str, Any]]:
    with db_cursor() as cur:
        cur.execute(f"SELECT {_RUN_COLUMNS} {_RUN_FROM} WHERE r.run_id = %s", (run_id,))
        found = _row(cur)
    if found:
        found["reversed"] = found["reversed_timestamp"] is not None
    return found


def _account(cur, account_id: Any) -> Optional[int]:
    """The account the salary was paid from. With several accounts it must be named; with one it is that one; with none it is kept as none (read as the
    first account once one exists)."""
    if account_id in (None, ""):
        cur.execute("SELECT account_id FROM orion_ods.bank_account ORDER BY account_id")
        found = [r[0] for r in cur.fetchall()]
        if len(found) > 1:
            raise PayrollError("Choose the account the salary was paid from.")
        return found[0] if found else None
    try:
        number = int(account_id)
    except (TypeError, ValueError):
        raise PayrollError("That account is not valid.") from None
    cur.execute("SELECT 1 FROM orion_ods.bank_account WHERE account_id = %s", (number,))
    if not cur.fetchone():
        raise PayrollError("That account does not exist.")
    return number


def record_run(
    user_id: Optional[int],
    *,
    confirm: bool = False,
    month_year: Any = None,
    line_codes: Any = None,
    seen_count: Any = None,
    seen_total: Any = None,
    paid_date: Any = None,
    account_id: Any = None,
    reference: Optional[str] = None,
    idem: Optional[Idempotency] = None,
    today: Optional[date] = None,
) -> dict[str, Any]:
    """Mark the chosen salary lines of a month paid, as one pay run: one transfer, on a day, from an account, with an optional bank reference.

    * ``confirm`` must be true: a request that did not come from the confirmation screen is refused;
    * ``seen_count`` and ``seen_total`` are what the person saw for the lines they chose; if the salary has changed since (a line paid by someone
      else, an amount edited), nothing is written;
    * only unpaid lines of that month with an amount can be paid, the day is not in the future, and with several accounts the account must be named.

    A day before the account's opening is allowed: that salary is already inside the opening balance, so it moves nothing (this is how months paid
    long ago are marked paid). With ``idem`` the same request arriving again records nothing and returns the first answer.
    """
    if not confirm:
        raise PayrollError("Confirm the payment to continue.")
    month = _month(month_year)
    today = today or date.today()
    day = _day(paid_date)
    if day > today:
        raise PayrollError("The day the salary was paid cannot be in the future. A pay run records money that has already gone out.")
    if not isinstance(line_codes, (list, tuple)) or not line_codes:
        raise PayrollError("Choose the salary lines that were paid.")
    codes = [str(c).strip() for c in line_codes if str(c).strip()]
    if not codes:
        raise PayrollError("Choose the salary lines that were paid.")
    if len(codes) > MAX_LINES or len(set(codes)) != len(codes):
        raise PayrollError(f"Choose each salary line once, and no more than {MAX_LINES} in a run.")
    if seen_count is None or seen_total is None:
        raise PayrollError("Reload the page and try again: it is not clear what you saw.")
    try:
        seen_n = int(seen_count)
    except (TypeError, ValueError):
        raise PayrollError("The number of lines you saw is not valid.") from None
    seen_sum = _amount(seen_total, "The total you saw")
    ref = " ".join(str(reference or "").split())[:REFERENCE_MAX] or None
    with db_cursor(commit=True) as cur:
        if idem is not None:
            prior = idem.claim(cur)
            if prior is not None:
                return prior
        cur.execute(
            """
            SELECT employee_transaction_code, month_year, salary_paid, salary_run_id, salary_amount
              FROM orion_ods.employee_transaction WHERE employee_transaction_code = ANY(%s) ORDER BY employee_transaction_code FOR UPDATE
            """,
            (codes,),
        )
        found = _rows(cur)
        if len(found) != len(codes):
            raise PayrollConflict("Some of those salary lines no longer exist. Reload the page to see where the month stands.")
        stale = [r for r in found if r["month_year"] != month or r["salary_paid"] != "No" or r["salary_run_id"] is not None or not r["salary_amount"] or r["salary_amount"] <= 0]
        if stale:
            raise PayrollConflict(f"{len(stale)} of those lines are no longer unpaid for {month} (someone else may have paid or changed them). Reload the page to see where the month stands.")
        total = sum((Decimal(str(r["salary_amount"])) for r in found), ZERO).quantize(CENT, rounding=ROUND_HALF_UP)
        if len(found) != seen_n or total != seen_sum:
            raise PayrollConflict(f"The salary changed while you had it open (it now comes to {_inr(total)} for {len(found)} lines). Reload the page to see where the month stands.")
        account = _account(cur, account_id)
        cur.execute(
            "INSERT INTO orion_ods.salary_run (month_year, paid_date, reference, account_id, recorded_by) VALUES (%s, %s, %s, %s, %s) RETURNING run_id",
            (month, day, ref, account, user_id),
        )
        run_id = cur.fetchone()[0]
        cur.execute(
            """
            UPDATE orion_ods.employee_transaction
               SET salary_paid = 'Yes', salary_run_id = %s, last_updated_timestamp = CURRENT_TIMESTAMP, last_updated_by = %s
             WHERE employee_transaction_code = ANY(%s)
            """,
            (run_id, user_id, codes),
        )
        result = {"run_id": run_id, "month_year": month, "paid_date": day.isoformat(), "account_id": account, "reference": ref, "lines": len(codes), "total": str(total)}
        if idem is not None:
            idem.remember(cur, result)
    return result


def reverse_run(run_id: int, user_id: Optional[int], *, confirm: bool = False, reason: Any = None) -> dict[str, Any]:
    """Take a pay run back, with the reason. It stays in the history, marked reversed, with who and when; its lines go back to unpaid and the money
    returns to the account it left."""
    if not confirm:
        raise PayrollError("Confirm the reversal to continue.")
    why = " ".join(str(reason or "").split())
    if len(why) < REASON_MIN:
        raise PayrollError(f"Say why the pay run is being reversed (at least {REASON_MIN} characters).")
    why = why[:REASON_MAX]
    with db_cursor(commit=True) as cur:
        cur.execute("SELECT run_id, month_year, reversed_timestamp FROM orion_ods.salary_run WHERE run_id = %s FOR UPDATE", (run_id,))
        found = _row(cur)
        if not found:
            raise PayrollError("That pay run does not exist.")
        if found["reversed_timestamp"] is not None:
            raise PayrollConflict("That pay run has already been reversed. Reload the page to see where it stands.")
        # The run is marked first: a line of a reversed run may be changed again (the database refuses to change a line of a run that stands).
        cur.execute(
            "UPDATE orion_ods.salary_run SET reversed_by = %s, reversed_timestamp = CURRENT_TIMESTAMP, reversal_reason = %s WHERE run_id = %s",
            (user_id, why, run_id),
        )
        cur.execute(
            """
            UPDATE orion_ods.employee_transaction
               SET salary_paid = 'No', salary_run_id = NULL, last_updated_timestamp = CURRENT_TIMESTAMP, last_updated_by = %s
             WHERE salary_run_id = %s
            """,
            (user_id, run_id),
        )
        lines = cur.rowcount
    return {"run_id": run_id, "month_year": found["month_year"], "lines": lines}
