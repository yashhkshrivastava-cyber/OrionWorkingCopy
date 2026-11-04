"""Attendance: who worked at a case in a month, and the pay that follows.

A **register** (``orion_ods.attendance_sheet``) is one case and one month, with a **line** for each person (``attendance_line``): the days present, the rate for a
day, an extra amount, a deduction and the amount to be paid. A person is an **employee** (from the employee table) or a **worker**: someone who works at the case but
is not an employee (casual labour), saved in ``attendance_worker`` so the next register finds them, and never added to the employee table.

Posting a register enters the pay, once, in the tables the rest of Orion already reads:

* each employee's line becomes a salary line (``employee_transaction``) for that month, worked at that case, not yet paid;
* each worker's line becomes an expense (``expense_transaction``, status Committed, with the expense type chosen on the register), not yet paid.

Paying stays where it is: salary in Bank > Payroll (a pay run), expenses in Bank > Payables. A posted register is not changed: **reopen** it (possible until
something it entered has been paid or has had a payment recorded), which takes the entries back, change it, and post it again. The entries carry the register line they
came from (``attendance_line_id``), and the generic forms refuse to change them (``entities.locked_reason``), so a register and the pay it entered never disagree.

This module is the only writer of the ``attendance_*`` tables and of the lines it enters. Posting is a deliberate act like marking salary paid: it needs the
confirmation, the count and total the person saw, and an ``Idempotency-Key``, and every step is kept in ``attendance_event``.
"""

from __future__ import annotations

import calendar
import logging
import re
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Optional

from psycopg2 import errors as pg_errors

from app.database import db_cursor
from app.db_utils import insert
from app.idempotency import Idempotency
from app.xlsx_io import read_first_sheet, write_xlsx

log = logging.getLogger(__name__)

ZERO = Decimal("0")
CENT = Decimal("0.01")
RATE_PLACES = Decimal("0.0001")
MONTH = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
MAX_LINES = 500
MAX_AMOUNT = Decimal("10000000")  # one crore for one person in one month
MAX_RATE = Decimal("1000000")
REASON_MIN = 5
REASON_MAX = 300
UPLOAD_LIMIT = 5 * 1024 * 1024
STATUSES = ("Draft", "Posted")

# The columns of the upload, the template and the export, in this order. A header is matched ignoring case and spaces.
COLUMNS = ("Employee Code", "Name", "Designation", "Days Present", "Rate per Day", "Extra", "Deduction", "Amount", "Remarks")


class AttendanceError(ValueError):
    """Something the person can fix: shown to them as it is."""


class AttendanceConflict(AttendanceError):
    """The register changed under the person, or the same thing was done twice."""


# --------------------------------------------------------------------------------------------------------------------
# Small helpers


def _rows(cur) -> list[dict[str, Any]]:
    names = [d[0] for d in cur.description]
    return [dict(zip(names, row)) for row in cur.fetchall()]


def _row(cur) -> Optional[dict[str, Any]]:
    found = _rows(cur)
    return found[0] if found else None


def month_of(value: Any) -> str:
    text = str(value or "").strip()
    if not MONTH.match(text):
        raise AttendanceError("Choose the month the register is for.")
    return text


def days_in(month: str) -> int:
    year, number = int(month[:4]), int(month[5:7])
    return calendar.monthrange(year, number)[1]


def month_bounds(month: str) -> tuple[date, date]:
    return date(int(month[:4]), int(month[5:7]), 1), date(int(month[:4]), int(month[5:7]), days_in(month))


def pay_date(month: str, today: Optional[date] = None) -> date:
    """The day the pay is entered on: the last day of the month, or today when the month is not over (a salary line is dated no later than today)."""
    today = today or date.today()
    return min(month_bounds(month)[1], today)


def _inr(value: Any) -> str:
    amount = Decimal(str(value)).quantize(CENT)
    whole, _, frac = f"{abs(amount):.2f}".partition(".")
    head, tail = whole[:-3], whole[-3:]
    groups: list[str] = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    return f"{'-' if amount < 0 else ''}₹{','.join(groups + [tail])}.{frac}"


def _decimal(value: Any, label: str, *, high: Decimal, places: Decimal = CENT) -> Decimal:
    """A number of at least nothing and at most ``high``, kept to ``places``. Empty means nothing."""
    if value is None or str(value).strip() == "":
        return ZERO
    try:
        number = Decimal(str(value).replace(",", "").strip())
        if not number.is_finite():
            raise InvalidOperation
        number = number.quantize(places, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError, TypeError):
        raise AttendanceError(f"{label} must be a number.") from None
    if number < 0:
        raise AttendanceError(f"{label} cannot be less than nothing.")
    if number > high:
        raise AttendanceError(f"{label} is more than {high:,} and cannot be right.")
    return number


def calculated_amount(rate: Decimal, days: Decimal, extra: Decimal, deduction: Decimal) -> Decimal:
    """What a line comes to before anyone changes it: the days at the rate, plus the extra, less the deduction (never below nothing)."""
    return max((rate * days + extra - deduction).quantize(CENT, rounding=ROUND_HALF_UP), ZERO).quantize(CENT)


def rate_from_salary(monthly_salary: Any, month: str) -> Decimal:
    """A day's pay from a monthly salary: the salary over the days of that month, so a full month pays exactly the salary."""
    if monthly_salary in (None, ""):
        return ZERO
    return (Decimal(str(monthly_salary)) / Decimal(days_in(month))).quantize(RATE_PLACES, rounding=ROUND_HALF_UP)


def _event(cur, sheet_id: int, action: str, note: Optional[str] = None, user_id: Optional[int] = None) -> None:
    cur.execute("INSERT INTO orion_ods.attendance_event (sheet_id, action, note, by_user) VALUES (%s, %s, %s, %s)", (sheet_id, action, note, user_id))


def _plain(item: dict[str, Any]) -> dict[str, Any]:
    return {key: (value.isoformat() if hasattr(value, "isoformat") else (str(value) if isinstance(value, Decimal) else value)) for key, value in item.items()}


# --------------------------------------------------------------------------------------------------------------------
# Choosing a case, and who works there


def cases(query: str = "") -> list[dict[str, Any]]:
    """Cases to make a register for: active ones first, by name or client."""
    pattern = "%" + " ".join(str(query).split()).lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT c.case_code, c.case_name, c.case_status, cl.client_name
              FROM orion_ods."case" c LEFT JOIN orion_ods.client cl ON cl.client_code = c.client_code
             WHERE lower(c.case_name || ' ' || c.case_code || ' ' || COALESCE(cl.client_name, '')) LIKE %s
             ORDER BY (c.case_status = 'Active') DESC NULLS LAST, lower(c.case_name) LIMIT 300
            """,
            (pattern,),
        )
        return _rows(cur)


def expense_types() -> list[dict[str, Any]]:
    """The expense types a register's casual pay can be entered under (for example Casual wages)."""
    with db_cursor() as cur:
        cur.execute("SELECT expense_type_code AS code, expense_type_name AS name FROM orion_ods.expense_type ORDER BY lower(expense_type_name)")
        return _rows(cur)


def _case(cur, case_code: Any) -> dict[str, Any]:
    cur.execute(
        'SELECT c.case_code, c.case_name, cl.client_name FROM orion_ods."case" c LEFT JOIN orion_ods.client cl ON cl.client_code = c.client_code WHERE c.case_code = %s',
        (str(case_code or "").strip(),),
    )
    found = _row(cur)
    if not found:
        raise AttendanceError("Choose the case the register is for.")
    return found


def roster(case_code: Any, month_year: Any) -> dict[str, Any]:
    """Everyone to put on a case's register for a month: its employees (active, and employed during the month) with their day's pay worked from their salary, the
    saved people who have worked there, last month's figures to copy, and the register that already exists, if one does."""
    month = month_of(month_year)
    first, last = month_bounds(month)
    with db_cursor() as cur:
        case = _case(cur, case_code)
        cur.execute(
            """
            SELECT e.employee_code, e.employee_name AS name, e.employee_designation AS designation, e.monthly_salary
              FROM orion_ods.employee e
             WHERE e.employee_case_code = %s AND e.employee_status = 'Active'
               AND (e.emp_start_date IS NULL OR e.emp_start_date <= %s) AND (e.emp_end_date IS NULL OR e.emp_end_date >= %s)
             ORDER BY lower(e.employee_name), e.employee_code
            """,
            (case["case_code"], last, first),
        )
        employees = []
        for item in _rows(cur):
            salary = item.pop("monthly_salary")
            item["rate_per_day"] = str(rate_from_salary(salary, month))
            item["has_salary"] = salary is not None
            employees.append(item)
        cur.execute(
            """
            SELECT w.worker_code, w.worker_name AS name, w.designation, w.phone, w.default_rate AS rate_per_day
              FROM orion_ods.attendance_worker w
             WHERE w.worker_status = 'Active'
               AND (w.case_code = %(case)s OR EXISTS (SELECT 1 FROM orion_ods.attendance_line l JOIN orion_ods.attendance_sheet s ON s.sheet_id = l.sheet_id
                                                       WHERE l.worker_code = w.worker_code AND s.case_code = %(case)s))
             ORDER BY lower(w.worker_name), w.worker_code
            """,
            {"case": case["case_code"]},
        )
        workers = [_plain(item) for item in _rows(cur)]
        cur.execute(
            "SELECT sheet_id, sheet_code, month_year FROM orion_ods.attendance_sheet WHERE case_code = %s AND month_year < %s ORDER BY month_year DESC LIMIT 1",
            (case["case_code"], month),
        )
        before = _row(cur)
        previous = None
        if before:
            cur.execute(
                """SELECT employee_code, worker_code, days_present, rate_per_day, extra_amount, deduction_amount
                     FROM orion_ods.attendance_line WHERE sheet_id = %s ORDER BY line_no, line_id""",
                (before["sheet_id"],),
            )
            previous = {"sheet_code": before["sheet_code"], "month_year": before["month_year"], "lines": [_plain(item) for item in _rows(cur)]}
        cur.execute("SELECT sheet_code, sheet_status FROM orion_ods.attendance_sheet WHERE case_code = %s AND month_year = %s", (case["case_code"], month))
        existing = _row(cur)
    return {
        "case": case, "month_year": month, "days_in_month": days_in(month), "employees": employees, "workers": workers,
        "previous": previous, "existing": existing,
    }


def search_people(query: Any, kind: Any = "all", month_year: Any = None, limit: int = 20) -> dict[str, list[dict[str, Any]]]:
    """Active employees and saved workers whose name, code or phone matches, to add to a register. Employees come with a day's pay worked from their salary for
    the month (the salary itself is not sent)."""
    month = month_of(month_year) if month_year else date.today().strftime("%Y-%m")
    text = " ".join(str(query or "").split()).lower()
    if len(text) < 2:
        return {"employees": [], "workers": []}
    pattern = "%" + text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    size = min(max(int(limit), 1), 50)
    out: dict[str, list[dict[str, Any]]] = {"employees": [], "workers": []}
    with db_cursor() as cur:
        if kind in ("all", "employee"):
            cur.execute(
                """
                SELECT e.employee_code, e.employee_name AS name, e.employee_designation AS designation, e.monthly_salary, cs.case_name
                  FROM orion_ods.employee e LEFT JOIN orion_ods."case" cs ON cs.case_code = e.employee_case_code
                 WHERE e.employee_status = 'Active' AND lower(e.employee_name || ' ' || e.employee_code) LIKE %s
                 ORDER BY lower(e.employee_name) LIMIT %s
                """,
                (pattern, size),
            )
            out["employees"] = [
                {"employee_code": item["employee_code"], "name": item["name"], "designation": item["designation"], "case_name": item["case_name"],
                 "rate_per_day": str(rate_from_salary(item["monthly_salary"], month))}
                for item in _rows(cur)
            ]
        if kind in ("all", "worker"):
            cur.execute(
                """
                SELECT worker_code, worker_name AS name, designation, phone, default_rate AS rate_per_day
                  FROM orion_ods.attendance_worker
                 WHERE worker_status = 'Active' AND lower(worker_name || ' ' || worker_code || ' ' || COALESCE(phone, '')) LIKE %s
                 ORDER BY lower(worker_name) LIMIT %s
                """,
                (pattern, size),
            )
            out["workers"] = [_plain(item) for item in _rows(cur)]
    return out


# --------------------------------------------------------------------------------------------------------------------
# Saved people (workers who are not employees)


def _worker_fields(raw: dict[str, Any]) -> dict[str, Any]:
    name = " ".join(str(raw.get("name") if "name" in raw else raw.get("worker_name") or "").split())
    if not name:
        raise AttendanceError("Give the person's name.")
    if len(name) > 100:
        raise AttendanceError("A name can be at most 100 characters.")
    phone = " ".join(str(raw.get("phone") or "").split()) or None
    if phone and not re.fullmatch(r"[0-9 +()./-]{7,20}", phone):
        raise AttendanceError("The phone number is not valid. Use digits, with spaces or + - ( ) if wanted.")
    designation = " ".join(str(raw.get("designation") or "").split())[:60] or None
    rate = None
    if raw.get("rate_per_day") not in (None, "") or raw.get("default_rate") not in (None, ""):
        rate = _decimal(raw.get("rate_per_day") if raw.get("rate_per_day") not in (None, "") else raw.get("default_rate"), "The day's pay", high=MAX_RATE, places=RATE_PLACES)
    return {"worker_name": name, "phone": phone, "designation": designation, "default_rate": rate}


def _find_worker(cur, name: str, phone: Optional[str]) -> Optional[str]:
    cur.execute("SELECT worker_code FROM orion_ods.attendance_worker WHERE lower(worker_name) = lower(%s) AND COALESCE(phone, '') = %s", (name, phone or ""))
    found = cur.fetchone()
    return found[0] if found else None


def _make_worker(cur, fields: dict[str, Any], case_code: Optional[str], user_id: Optional[int]) -> str:
    """Save a person who is not an employee. Someone with the same name and phone is not saved twice: the saved one is used."""
    found = _find_worker(cur, fields["worker_name"], fields["phone"])
    if found:
        return found
    code = insert(
        "orion_ods.attendance_worker", ["worker_name", "phone", "designation", "default_rate", "case_code"],
        [fields["worker_name"], fields["phone"], fields["designation"], fields["default_rate"], case_code], user_id=user_id, returning="worker_code", cur=cur,
    )
    return code


def list_workers(query: Any = "", status: Any = "Active", limit: int = 200) -> list[dict[str, Any]]:
    pattern = "%" + " ".join(str(query or "").split()).lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    where, params = "lower(w.worker_name || ' ' || w.worker_code || ' ' || COALESCE(w.phone, '')) LIKE %s", [pattern]
    if status in ("Active", "Inactive"):
        where += " AND w.worker_status = %s"
        params.append(status)
    with db_cursor() as cur:
        cur.execute(
            f"""
            SELECT w.worker_code, w.worker_name AS name, w.phone, w.designation, w.default_rate AS rate_per_day, w.case_code, cs.case_name, w.worker_status AS status, w.notes,
                   (SELECT COUNT(*) FROM orion_ods.attendance_line l WHERE l.worker_code = w.worker_code) AS registers
              FROM orion_ods.attendance_worker w LEFT JOIN orion_ods."case" cs ON cs.case_code = w.case_code
             WHERE {where} ORDER BY lower(w.worker_name) LIMIT %s
            """,
            (*params, min(max(int(limit), 1), 500)),
        )
        return [_plain(item) for item in _rows(cur)]


def create_worker(user_id: Optional[int], raw: dict[str, Any]) -> dict[str, Any]:
    fields = _worker_fields(raw)
    case_code = str(raw.get("case_code") or "").strip() or None
    with db_cursor(commit=True) as cur:
        if case_code:
            _case(cur, case_code)
        if _find_worker(cur, fields["worker_name"], fields["phone"]):
            raise AttendanceConflict("That person is already saved.")
        code = _make_worker(cur, fields, case_code, user_id)
    return {"worker_code": code}


def update_worker(user_id: Optional[int], worker_code: str, raw: dict[str, Any]) -> bool:
    fields = _worker_fields(raw)
    status = raw.get("status") if raw.get("status") in ("Active", "Inactive") else None
    case_code = str(raw.get("case_code") or "").strip() or None
    with db_cursor(commit=True) as cur:
        if case_code:
            _case(cur, case_code)
        try:
            cur.execute(
                """
                UPDATE orion_ods.attendance_worker SET worker_name = %s, phone = %s, designation = %s, default_rate = %s, case_code = %s,
                       worker_status = COALESCE(%s, worker_status), last_updated_by = %s, last_updated_timestamp = CURRENT_TIMESTAMP
                 WHERE worker_code = %s
                """,
                (fields["worker_name"], fields["phone"], fields["designation"], fields["default_rate"], case_code, status, user_id, worker_code),
            )
        except pg_errors.UniqueViolation:
            raise AttendanceConflict("Another saved person has that name and phone.") from None
        return cur.rowcount > 0


# --------------------------------------------------------------------------------------------------------------------
# Registers


def _clean_line(raw: dict[str, Any], month: str) -> dict[str, Any]:
    """One line as the person sent it, checked. The amount is the one sent (the person may change it) or, when none was sent, what the figures come to."""
    employee = str(raw.get("employee_code") or "").strip() or None
    worker = str(raw.get("worker_code") or "").strip() or None
    new_worker = raw.get("new_worker") if isinstance(raw.get("new_worker"), dict) else None
    if sum(1 for chosen in (employee, worker, new_worker) if chosen) != 1:
        raise AttendanceError("Each line is one person: an employee, a saved person or a new person.")
    days = _decimal(raw.get("days_present"), "Days present", high=Decimal(days_in(month)), places=Decimal("0.1"))
    rate = _decimal(raw.get("rate_per_day"), "The day's pay", high=MAX_RATE, places=RATE_PLACES)
    extra = _decimal(raw.get("extra_amount"), "The extra", high=MAX_AMOUNT)
    deduction = _decimal(raw.get("deduction_amount"), "The deduction", high=MAX_AMOUNT)
    if raw.get("amount") in (None, ""):
        amount = calculated_amount(rate, days, extra, deduction)
    else:
        amount = _decimal(raw.get("amount"), "The amount", high=MAX_AMOUNT)
    remarks = " ".join(str(raw.get("remarks") or "").split())[:200] or None
    return {
        "employee_code": employee, "worker_code": worker, "new_worker": _worker_fields(new_worker) if new_worker else None, "days_present": days, "rate_per_day": rate,
        "extra_amount": extra, "deduction_amount": deduction, "amount": amount, "remarks": remarks,
    }


def _clean_lines(lines: Any, month: str) -> list[dict[str, Any]]:
    if not isinstance(lines, (list, tuple)):
        raise AttendanceError("Add the people who worked.")
    if len(lines) > MAX_LINES:
        raise AttendanceError(f"A register can have at most {MAX_LINES} people.")
    cleaned = []
    seen: set[tuple[str, str]] = set()
    for index, raw in enumerate(lines, start=1):
        try:
            line = _clean_line(raw if isinstance(raw, dict) else {}, month)
        except AttendanceError as exc:
            raise AttendanceError(f"Line {index}: {exc}") from None
        who = ("employee", line["employee_code"]) if line["employee_code"] else ("worker", line["worker_code"]) if line["worker_code"] else ("new", f"{line['new_worker']['worker_name'].lower()}|{line['new_worker']['phone'] or ''}")
        if who in seen:
            raise AttendanceError(f"Line {index}: that person is already on this register.")
        seen.add(who)
        cleaned.append(line)
    return cleaned


def _lock_sheet(cur, sheet_code: Any) -> Optional[dict[str, Any]]:
    cur.execute(
        """SELECT sheet_id, sheet_code, case_code, month_year, sheet_status, expense_type_code FROM orion_ods.attendance_sheet WHERE sheet_code = %s FOR UPDATE""",
        (str(sheet_code or "").strip(),),
    )
    return _row(cur)


def save_sheet(
    user_id: Optional[int], *, sheet_code: Any = None, case_code: Any = None, month_year: Any = None, lines: Any = None, remarks: Any = None, expense_type_code: Any = None,
) -> dict[str, Any]:
    """Make a register, or save a draft one again with exactly these lines. A register that is posted is not changed here: reopen it first."""
    text = " ".join(str(remarks or "").split())[:500] or None
    expense_type = str(expense_type_code or "").strip() or None
    with db_cursor(commit=True) as cur:
        if sheet_code:
            sheet = _lock_sheet(cur, sheet_code)
            if not sheet:
                raise AttendanceError("That register does not exist.")
            if sheet["sheet_status"] != "Draft":
                raise AttendanceConflict("This register has been posted. Reopen it to change it.")
            month, case = sheet["month_year"], sheet["case_code"]
        else:
            month = month_of(month_year)
            case = _case(cur, case_code)["case_code"]
        cleaned = _clean_lines(lines, month)
        if expense_type:
            cur.execute("SELECT 1 FROM orion_ods.expense_type WHERE expense_type_code = %s", (expense_type,))
            if not cur.fetchone():
                raise AttendanceError("That expense type does not exist.")
        if sheet_code:
            cur.execute(
                "UPDATE orion_ods.attendance_sheet SET remarks = %s, expense_type_code = %s, last_updated_by = %s, last_updated_timestamp = CURRENT_TIMESTAMP WHERE sheet_id = %s",
                (text, expense_type, user_id, sheet["sheet_id"]),
            )
            sheet_id, code, action = sheet["sheet_id"], sheet["sheet_code"], "saved"
            cur.execute("DELETE FROM orion_ods.attendance_line WHERE sheet_id = %s", (sheet_id,))
        else:
            try:
                cur.execute(
                    """INSERT INTO orion_ods.attendance_sheet (case_code, month_year, expense_type_code, remarks, created_by, last_updated_by)
                       VALUES (%s, %s, %s, %s, %s, %s) RETURNING sheet_id, sheet_code""",
                    (case, month, expense_type, text, user_id, user_id),
                )
            except pg_errors.UniqueViolation:
                raise AttendanceConflict("There is already a register for that case and month. Open it from the list.") from None
            sheet_id, code = cur.fetchone()
            action = "created"
        for number, line in enumerate(cleaned, start=1):
            employee, worker = line["employee_code"], line["worker_code"]
            if employee:
                cur.execute("SELECT employee_name, employee_designation FROM orion_ods.employee WHERE employee_code = %s", (employee,))
                found = cur.fetchone()
                if not found:
                    raise AttendanceError(f"Line {number}: that employee does not exist.")
                name, designation = found
            elif worker:
                cur.execute("SELECT worker_name, designation FROM orion_ods.attendance_worker WHERE worker_code = %s", (worker,))
                found = cur.fetchone()
                if not found:
                    raise AttendanceError(f"Line {number}: that saved person does not exist.")
                name, designation = found
            else:
                fields = line["new_worker"]
                worker = _make_worker(cur, {**fields, "default_rate": fields["default_rate"] if fields["default_rate"] is not None else (line["rate_per_day"] or None)}, case, user_id)
                name, designation = fields["worker_name"], fields["designation"]
            cur.execute(
                """INSERT INTO orion_ods.attendance_line
                       (sheet_id, line_no, employee_code, worker_code, person_name, designation, days_present, rate_per_day, extra_amount, deduction_amount, amount, remarks)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (sheet_id, number, employee, worker, name, designation, line["days_present"], line["rate_per_day"], line["extra_amount"], line["deduction_amount"], line["amount"], line["remarks"]),
            )
        _event(cur, sheet_id, action, f"{len(cleaned)} people", user_id)
    return {"sheet_code": code, "lines": len(cleaned)}


def _warnings(cur, sheet: dict[str, Any], lines: list[dict[str, Any]]) -> dict[int, list[str]]:
    """Per line: reasons to look twice. An employee who already has pay for the month somewhere else, or who is on another register for it, may be paid twice."""
    found: dict[int, list[str]] = {}
    employees = [line["employee_code"] for line in lines if line["employee_code"]]
    if not employees:
        return found
    cur.execute(
        """
        SELECT t.employee_code, t.employee_transaction_code, l.sheet_id
          FROM orion_ods.employee_transaction t LEFT JOIN orion_ods.attendance_line l ON l.line_id = t.attendance_line_id
         WHERE t.month_year = %s AND t.employee_code = ANY(%s) AND (t.attendance_line_id IS NULL OR l.sheet_id <> %s)
        """,
        (sheet["month_year"], employees, sheet["sheet_id"]),
    )
    pay = {}
    for employee, code, _other in cur.fetchall():
        pay.setdefault(employee, []).append(code)
    cur.execute(
        """
        SELECT l.employee_code, s.sheet_code, cs.case_name
          FROM orion_ods.attendance_line l JOIN orion_ods.attendance_sheet s ON s.sheet_id = l.sheet_id JOIN orion_ods."case" cs ON cs.case_code = s.case_code
         WHERE s.month_year = %s AND l.employee_code = ANY(%s) AND s.sheet_id <> %s
        """,
        (sheet["month_year"], employees, sheet["sheet_id"]),
    )
    other = {}
    for employee, code, case_name in cur.fetchall():
        other.setdefault(employee, []).append(f"{code} ({case_name})")
    for line in lines:
        notes = []
        if line["employee_code"] in pay:
            notes.append(f"Already has pay for {sheet['month_year']} ({', '.join(pay[line['employee_code']])}).")
        if line["employee_code"] in other:
            notes.append(f"Also on register {', '.join(other[line['employee_code']])}.")
        if notes:
            found[line["line_id"]] = notes
    return found


def get_sheet(sheet_code: Any) -> Optional[dict[str, Any]]:
    """A register with its lines, what posting it entered (and whether that has been paid), and reasons to look twice. None when there is no such register."""
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT s.sheet_id, s.sheet_code, s.case_code, cs.case_name, cl.client_name, s.month_year, s.sheet_status AS status, s.expense_type_code, et.expense_type_name,
                   s.remarks, s.posted_timestamp, pu.display_name AS posted_by_name, s.created_timestamp, s.last_updated_timestamp, cu.display_name AS created_by_name
              FROM orion_ods.attendance_sheet s
              JOIN orion_ods."case" cs ON cs.case_code = s.case_code
              LEFT JOIN orion_ods.client cl ON cl.client_code = cs.client_code
              LEFT JOIN orion_ods.expense_type et ON et.expense_type_code = s.expense_type_code
              LEFT JOIN orion_ods.app_user pu ON pu.id = s.posted_by
              LEFT JOIN orion_ods.app_user cu ON cu.id = s.created_by
             WHERE s.sheet_code = %s
            """,
            (str(sheet_code or "").strip(),),
        )
        sheet = _row(cur)
        if not sheet:
            return None
        cur.execute(
            """
            SELECT l.line_id, l.line_no, l.employee_code, l.worker_code, l.person_name AS name, l.designation, l.days_present, l.rate_per_day, l.extra_amount,
                   l.deduction_amount, l.amount, l.remarks,
                   t.employee_transaction_code AS salary_code, (t.salary_run_id IS NOT NULL) AS salary_paid,
                   x.expense_code, EXISTS (SELECT 1 FROM orion_ods.expense_payment p WHERE p.expense_code = x.expense_code) AS expense_paid
              FROM orion_ods.attendance_line l
              LEFT JOIN orion_ods.employee_transaction t ON t.attendance_line_id = l.line_id
              LEFT JOIN orion_ods.expense_transaction x ON x.attendance_line_id = l.line_id
             WHERE l.sheet_id = %s ORDER BY l.line_no, l.line_id
            """,
            (sheet["sheet_id"],),
        )
        lines = _rows(cur)
        warnings = _warnings(cur, sheet, lines) if sheet["status"] == "Draft" else {}
        cur.execute(
            """SELECT e.action, e.note, e.at, u.display_name AS by_name FROM orion_ods.attendance_event e LEFT JOIN orion_ods.app_user u ON u.id = e.by_user
                WHERE e.sheet_id = %s ORDER BY e.id DESC LIMIT 50""",
            (sheet["sheet_id"],),
        )
        events = [_plain(item) for item in _rows(cur)]
    total = ZERO
    for line in lines:
        line["calculated"] = str(calculated_amount(line["rate_per_day"], line["days_present"], line["extra_amount"], line["deduction_amount"]))
        line["warnings"] = warnings.get(line["line_id"], [])
        line["paid"] = bool(line["salary_paid"] or line["expense_paid"])
        total += line["amount"]
    sheet["days_in_month"] = days_in(sheet["month_year"])
    sheet["totals"] = {
        "people": len(lines), "employees": sum(1 for line in lines if line["employee_code"]), "workers": sum(1 for line in lines if line["worker_code"]),
        "amount": str(total.quantize(CENT)), "payable": sum(1 for line in lines if line["amount"] > 0),
        "employee_amount": str(sum((line["amount"] for line in lines if line["employee_code"]), ZERO).quantize(CENT)),
        "worker_amount": str(sum((line["amount"] for line in lines if line["worker_code"]), ZERO).quantize(CENT)),
    }
    sheet["lines"] = [_plain(line) for line in lines]
    sheet["events"] = events
    return _plain(sheet)


def list_sheets(*, case_code: Any = None, month_year: Any = None, status: Any = None, query: Any = "", limit: int = 200) -> list[dict[str, Any]]:
    where, params = ["TRUE"], []
    if case_code:
        where.append("s.case_code = %s")
        params.append(str(case_code))
    if month_year:
        where.append("s.month_year = %s")
        params.append(month_of(month_year))
    if status:
        if status not in STATUSES:
            raise AttendanceError("Status is Draft or Posted.")
        where.append("s.sheet_status = %s")
        params.append(status)
    needle = " ".join(str(query or "").split()).lower()
    if needle:
        where.append("lower(s.sheet_code || ' ' || cs.case_name || ' ' || COALESCE(cl.client_name, '')) LIKE %s")
        params.append("%" + needle.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%")
    with db_cursor() as cur:
        cur.execute(
            f"""
            SELECT s.sheet_code, s.case_code, cs.case_name, cl.client_name, s.month_year, s.sheet_status AS status, s.posted_timestamp, s.last_updated_timestamp,
                   COUNT(l.line_id) AS people, COUNT(l.line_id) FILTER (WHERE l.employee_code IS NOT NULL) AS employees,
                   COUNT(l.line_id) FILTER (WHERE l.worker_code IS NOT NULL) AS workers, COALESCE(SUM(l.amount), 0) AS amount
              FROM orion_ods.attendance_sheet s
              JOIN orion_ods."case" cs ON cs.case_code = s.case_code
              LEFT JOIN orion_ods.client cl ON cl.client_code = cs.client_code
              LEFT JOIN orion_ods.attendance_line l ON l.sheet_id = s.sheet_id
             WHERE {' AND '.join(where)}
             GROUP BY s.sheet_id, cs.case_name, cl.client_name
             ORDER BY s.month_year DESC, lower(cs.case_name) LIMIT %s
            """,
            (*params, min(max(int(limit), 1), 500)),
        )
        return [_plain(item) for item in _rows(cur)]


def delete_sheet(user_id: Optional[int], sheet_code: Any) -> bool:
    """Delete a draft register. A posted one has entered pay and is reopened, not deleted."""
    with db_cursor(commit=True) as cur:
        sheet = _lock_sheet(cur, sheet_code)
        if not sheet:
            return False
        if sheet["sheet_status"] != "Draft":
            raise AttendanceConflict("A posted register cannot be deleted. Reopen it first.")
        cur.execute("DELETE FROM orion_ods.attendance_sheet WHERE sheet_id = %s", (sheet["sheet_id"],))
        cur.execute("INSERT INTO orion_ods.record_deleted (table_name, record_code, deleted_by) VALUES ('orion_ods.attendance_sheet', %s, %s)", (sheet["sheet_code"], user_id))
    return True


def post_sheet(
    user_id: Optional[int], sheet_code: Any, *, confirm: bool = False, seen_count: Any = None, seen_total: Any = None, idem: Optional[Idempotency] = None, today: Optional[date] = None,
) -> dict[str, Any]:
    """Enter the pay of a register: a salary line for each employee and an expense for each worker, in one step. It needs the confirmation, and the number
    of people to be paid and the total the person saw, so a register changed meanwhile is not posted by mistake. With ``idem`` the same request arriving again
    enters nothing and returns the first answer."""
    if not confirm:
        raise AttendanceError("Confirm the posting to continue.")
    today = today or date.today()
    if seen_count is None or seen_total is None:
        raise AttendanceError("Reload the page and try again: it is not clear what you saw.")
    try:
        seen_n = int(seen_count)
    except (TypeError, ValueError):
        raise AttendanceError("The number of people you saw is not valid.") from None
    seen_sum = _decimal(seen_total, "The total you saw", high=MAX_AMOUNT * MAX_LINES)
    with db_cursor(commit=True) as cur:
        if idem is not None:
            prior = idem.claim(cur)
            if prior is not None:
                return prior
        sheet = _lock_sheet(cur, sheet_code)
        if not sheet:
            raise AttendanceError("That register does not exist.")
        if sheet["sheet_status"] != "Draft":
            raise AttendanceConflict("This register has already been posted. Reload the page to see where it stands.")
        first, _last = month_bounds(sheet["month_year"])
        if first > today:
            raise AttendanceError("That month has not started yet, so there is no attendance to post.")
        cur.execute(
            """SELECT line_id, employee_code, worker_code, person_name, days_present, amount FROM orion_ods.attendance_line
                WHERE sheet_id = %s ORDER BY line_no, line_id""",
            (sheet["sheet_id"],),
        )
        lines = _rows(cur)
        payable = [line for line in lines if line["amount"] > 0]
        if not payable:
            raise AttendanceError("Nobody on this register has an amount to pay.")
        total = sum((line["amount"] for line in payable), ZERO).quantize(CENT)
        if len(payable) != seen_n or total != seen_sum:
            raise AttendanceConflict(f"The register changed while you had it open (it now comes to {_inr(total)} for {len(payable)} people). Reload the page to see it.")
        workers = [line for line in payable if line["worker_code"]]
        if workers and not sheet["expense_type_code"]:
            raise AttendanceError("Choose the expense type for the people who are not employees (for example casual wages), then post again.")
        day = pay_date(sheet["month_year"], today)
        month_label = sheet["month_year"]
        for line in payable:
            if line["employee_code"]:
                insert(
                    "orion_ods.employee_transaction",
                    ["employee_code", "transaction_date", "month_year", "days_worked", "salary_amount", "salary_paid", "case_code", "attendance_line_id"],
                    [line["employee_code"], day, month_label, line["days_present"], line["amount"], "No", sheet["case_code"], line["line_id"]],
                    user_id=user_id, cur=cur,
                )
            else:
                days = f"{line['days_present']:f}".rstrip("0").rstrip(".") or "0"
                insert(
                    "orion_ods.expense_transaction",
                    ["case_code", "transaction_date", "transaction_amount", "tax", "gst", "amount_after_tax_gst", "transaction_status", "expense_type_code", "is_regular_expense",
                     "transaction_description", "attendance_line_id"],
                    [sheet["case_code"], day, line["amount"], 0, 0, line["amount"], "Committed", sheet["expense_type_code"], "Yes",
                     f"Attendance {sheet['sheet_code']} · {line['person_name']} · {month_label} · {days} days", line["line_id"]],
                    user_id=user_id, cur=cur,
                )
        cur.execute(
            "UPDATE orion_ods.attendance_sheet SET sheet_status = 'Posted', posted_by = %s, posted_timestamp = CURRENT_TIMESTAMP, last_updated_by = %s, last_updated_timestamp = CURRENT_TIMESTAMP WHERE sheet_id = %s",
            (user_id, user_id, sheet["sheet_id"]),
        )
        _event(cur, sheet["sheet_id"], "posted", f"{len(payable)} people, {_inr(total)}", user_id)
        result = {
            "sheet_code": sheet["sheet_code"], "salary_lines": len(payable) - len(workers), "expenses": len(workers), "total": str(total), "pay_date": day.isoformat(),
        }
        if idem is not None:
            idem.remember(cur, result)
    return result


def reopen_sheet(user_id: Optional[int], sheet_code: Any, *, confirm: bool = False, reason: Any = None) -> dict[str, Any]:
    """Take a posted register back to a draft, with the reason: what it entered is removed. Refused when any of it has been paid (a pay run, or a payment
    recorded on an expense, even one that was later reversed): that money has moved, and the register cannot be undone from here."""
    if not confirm:
        raise AttendanceError("Confirm that you want to reopen the register.")
    why = " ".join(str(reason or "").split())
    if len(why) < REASON_MIN:
        raise AttendanceError(f"Say why the register is being reopened (at least {REASON_MIN} characters).")
    with db_cursor(commit=True) as cur:
        sheet = _lock_sheet(cur, sheet_code)
        if not sheet:
            raise AttendanceError("That register does not exist.")
        if sheet["sheet_status"] != "Posted":
            raise AttendanceConflict("This register is not posted. Reload the page to see where it stands.")
        cur.execute(
            """
            SELECT t.employee_transaction_code FROM orion_ods.employee_transaction t JOIN orion_ods.attendance_line l ON l.line_id = t.attendance_line_id
             WHERE l.sheet_id = %s AND (t.salary_run_id IS NOT NULL OR t.salary_paid = 'Yes') FOR UPDATE OF t
            """,
            (sheet["sheet_id"],),
        )
        paid_salary = [r[0] for r in cur.fetchall()]
        cur.execute(
            """
            SELECT x.expense_code FROM orion_ods.expense_transaction x JOIN orion_ods.attendance_line l ON l.line_id = x.attendance_line_id
             WHERE l.sheet_id = %s AND EXISTS (SELECT 1 FROM orion_ods.expense_payment p WHERE p.expense_code = x.expense_code) FOR UPDATE OF x
            """,
            (sheet["sheet_id"],),
        )
        paid_expenses = [r[0] for r in cur.fetchall()]
        if paid_salary or paid_expenses:
            kinds = [f"{len(paid_salary)} salary line{'s' if len(paid_salary) != 1 else ''} already paid in a pay run" if paid_salary else "",
                     f"{len(paid_expenses)} expense{'s' if len(paid_expenses) != 1 else ''} with a payment recorded" if paid_expenses else ""]
            raise AttendanceConflict(
                "This register cannot be reopened: " + " and ".join(k for k in kinds if k) + ". Reverse those payments in Bank (Payroll, Payables) first."
            )
        removed = 0
        for table, code_column, name in (
            ("orion_ods.employee_transaction", "employee_transaction_code", "orion_ods.employee_transaction"),
            ("orion_ods.expense_transaction", "expense_code", "orion_ods.expense_transaction"),
        ):
            cur.execute(
                f"DELETE FROM {table} t USING orion_ods.attendance_line l WHERE l.line_id = t.attendance_line_id AND l.sheet_id = %s RETURNING t.{code_column}",  # noqa: S608 - fixed names
                (sheet["sheet_id"],),
            )
            for (code,) in cur.fetchall():
                cur.execute("INSERT INTO orion_ods.record_deleted (table_name, record_code, deleted_by) VALUES (%s, %s, %s)", (name, code, user_id))
                removed += 1
        cur.execute(
            """UPDATE orion_ods.attendance_sheet SET sheet_status = 'Draft', posted_by = NULL, posted_timestamp = NULL, last_updated_by = %s,
                      last_updated_timestamp = CURRENT_TIMESTAMP WHERE sheet_id = %s""",
            (user_id, sheet["sheet_id"]),
        )
        _event(cur, sheet["sheet_id"], "reopened", why[:REASON_MAX], user_id)
    return {"sheet_code": sheet["sheet_code"], "removed": removed}


# --------------------------------------------------------------------------------------------------------------------
# Excel: a template to fill, an export, and reading a filled sheet back


def _number(value: Any) -> Any:
    return float(value) if isinstance(value, Decimal) else value


def template_file(case_code: Any, month_year: Any) -> tuple[str, bytes]:
    """A workbook with the case's employees and saved people already listed, for the days to be filled in and uploaded."""
    found = roster(case_code, month_year)
    rows: list[list[object]] = [list(COLUMNS)]
    for person in found["employees"]:
        rows.append([person["employee_code"], person["name"], person["designation"] or "", None, _number(Decimal(person["rate_per_day"])) if Decimal(person["rate_per_day"]) else None, None, None, None, None])
    for person in found["workers"]:
        rows.append(["", person["name"], person["designation"] or "", None, _number(Decimal(person["rate_per_day"])) if person.get("rate_per_day") else None, None, None, None, None])
    guide = [
        ["How to fill this in"],
        ["One row for each person. Leave Employee Code empty for someone who is not an employee: the name is looked up among the people saved at this case, and a new name is added."],
        ["Days Present can be a half (12.5). Rate per Day is the pay for a day. Extra adds to the pay, Deduction takes from it."],
        ["Amount is optional: leave it empty and it is worked out as days x rate + extra - deduction."],
    ]
    name = f"attendance_{found['case']['case_code']}_{found['month_year']}.xlsx"
    return name, write_xlsx({"Attendance": rows, "Guide": guide})


def sheet_file(sheet_code: Any) -> Optional[tuple[str, bytes]]:
    sheet = get_sheet(sheet_code)
    if not sheet:
        return None
    rows: list[list[object]] = [list(COLUMNS)]
    for line in sheet["lines"]:
        rows.append([
            line["employee_code"] or "", line["name"], line["designation"] or "", float(line["days_present"]), float(line["rate_per_day"]), float(line["extra_amount"]),
            float(line["deduction_amount"]), float(line["amount"]), line["remarks"] or "",
        ])
    rows.append([])
    rows.append(["", "Total", "", None, None, None, None, float(sheet["totals"]["amount"]), ""])
    return f"attendance_{sheet['sheet_code']}_{sheet['case_code']}_{sheet['month_year']}.xlsx", write_xlsx({"Attendance": rows})


def _key(text: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(text or "").lower())


def parse_upload(case_code: Any, month_year: Any, content: bytes) -> dict[str, Any]:
    """Read a filled attendance workbook into lines for the register (nothing is saved). A person is matched by employee code, then by name among this case's
    employees and saved people, then among every active employee; a name that matches nobody is a new person, to be saved with the register. Rows that cannot be
    read are returned with the reason, so one bad row does not stop the others."""
    if not content:
        raise AttendanceError("The uploaded file is empty.")
    if len(content) > UPLOAD_LIMIT:
        raise AttendanceError("The file is larger than 5 MB.")
    month = month_of(month_year)
    try:
        sheet = read_first_sheet(content)
    except ValueError:
        raise AttendanceError("That is not an Excel (.xlsx) file.") from None
    if not sheet:
        raise AttendanceError("The workbook has nothing in it.")
    headers = {_key(cell): index for index, cell in enumerate(sheet[0]) if cell not in (None, "")}
    wanted = {_key(c): c for c in COLUMNS}
    missing = [wanted[k] for k in ("dayspresent",) if k not in headers]
    if missing or ("name" not in headers and "employeecode" not in headers):
        raise AttendanceError("The first row must have the headings Employee Code or Name, and Days Present. Download the template to see them.")
    found = roster(case_code, month)
    on_case = {p["employee_code"]: p for p in found["employees"]}
    by_name = {_key(p["name"]): ("employee", p) for p in found["employees"]}
    for p in found["workers"]:
        by_name.setdefault(_key(p["name"]), ("worker", p))
    out, problems = [], []

    def cell(row: list[object], column: str) -> Any:
        index = headers.get(_key(column))
        return row[index] if index is not None and index < len(row) else None

    with db_cursor() as cur:
        everyone: dict[str, dict[str, Any]] = {}
        cur.execute("SELECT employee_code, employee_name, employee_designation, monthly_salary FROM orion_ods.employee WHERE employee_status = 'Active'")
        for code, name, designation, salary in cur.fetchall():
            everyone[code.lower()] = {"employee_code": code, "name": name, "designation": designation, "rate_per_day": str(rate_from_salary(salary, month))}
    by_any_name = {_key(p["name"]): p for p in everyone.values()}
    for number, row in enumerate(sheet[1:], start=2):
        if not any(value not in (None, "") for value in row):
            continue
        try:
            code, name = str(cell(row, "Employee Code") or "").strip(), " ".join(str(cell(row, "Name") or "").split())
            if not code and not name:
                raise AttendanceError("Give an employee code or a name.")
            line: dict[str, Any] = {
                "days_present": cell(row, "Days Present"), "rate_per_day": cell(row, "Rate per Day"), "extra_amount": cell(row, "Extra"),
                "deduction_amount": cell(row, "Deduction"), "amount": cell(row, "Amount"), "remarks": cell(row, "Remarks"),
            }
            person: Optional[dict[str, Any]] = None
            if code:
                person = on_case.get(code) or everyone.get(code.lower())
                if not person:
                    raise AttendanceError(f"There is no active employee with the code {code}.")
                line["employee_code"] = person["employee_code"]
            else:
                kind, person = by_name.get(_key(name), (None, None))
                if kind == "employee":
                    line["employee_code"] = person["employee_code"]
                elif kind == "worker":
                    line["worker_code"] = person["worker_code"]
                elif _key(name) in by_any_name:
                    person = by_any_name[_key(name)]
                    line["employee_code"] = person["employee_code"]
                else:
                    line["new_worker"] = {"name": name, "designation": cell(row, "Designation")}
            if line.get("rate_per_day") in (None, "") and person and person.get("rate_per_day") and Decimal(str(person["rate_per_day"])) > 0:
                line["rate_per_day"] = person["rate_per_day"]
            checked = _clean_line(line, month)
            shown = {
                "employee_code": checked["employee_code"], "worker_code": checked["worker_code"],
                "new_worker": checked["new_worker"] and {"name": checked["new_worker"]["worker_name"], "phone": checked["new_worker"]["phone"], "designation": checked["new_worker"]["designation"]},
                "name": (person or {}).get("name") or name, "designation": (person or {}).get("designation") or (line.get("new_worker") or {}).get("designation") or "",
                "days_present": str(checked["days_present"]), "rate_per_day": str(checked["rate_per_day"]), "extra_amount": str(checked["extra_amount"]),
                "deduction_amount": str(checked["deduction_amount"]), "amount": str(checked["amount"]), "remarks": checked["remarks"] or "", "row": number,
                "calculated": str(calculated_amount(checked["rate_per_day"], checked["days_present"], checked["extra_amount"], checked["deduction_amount"])),
            }
            out.append(shown)
        except AttendanceError as exc:
            problems.append({"row": number, "message": str(exc)})
    seen: set[str] = set()
    unique = []
    for item in out:
        who = item["employee_code"] or item["worker_code"] or f"new:{_key(item['name'])}"
        if who in seen:
            problems.append({"row": item["row"], "message": f"{item['name']} is on the sheet more than once; only the first row is used."})
            continue
        seen.add(who)
        unique.append(item)
    return {"lines": unique, "problems": problems}
