"""An employee's page: who they are, where they work, who they report to and who reports to them and, for someone who may see payroll, what they have been paid lately.

Read only, and it never carries the private columns (Aadhaar, PAN, the agreed salary): `orion_ods.employee` has them, but nothing here selects them. Pay history is the employee's salary lines, and
only for someone with bank access (the same people who run payroll); papers are kept and opened in the Document Center.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.database import db_cursor

DIRECTORY_LIMIT = 500
PAY_MONTHS = 6


def _rows(cur) -> list[dict[str, Any]]:
    columns = [col.name for col in cur.description]
    return [dict(zip(columns, row)) for row in cur.fetchall()]


def _plain(value: Any) -> Any:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


def _clean(row: dict[str, Any]) -> dict[str, Any]:
    return {key: _plain(value) for key, value in row.items()}


def directory(search: str | None) -> list[dict[str, Any]]:
    """Every employee with their designation, case and client; active people first."""
    needle = (search or "").strip()[:80]
    like = f"%{needle}%"
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT e.employee_code, e.employee_name, e.employee_designation, e.employee_type, e.employee_status, e.client_facing,
                   e.employee_case_code AS case_code, cs.case_name, cl.client_name, m.employee_name AS manager_name
              FROM orion_ods.employee e
              LEFT JOIN orion_ods.case cs ON cs.case_code = e.employee_case_code
              LEFT JOIN orion_ods.client cl ON cl.client_code = cs.client_code
              LEFT JOIN orion_ods.employee m ON m.employee_code = e.manager_code
             WHERE (%s = '' OR e.employee_name ILIKE %s OR e.employee_code ILIKE %s OR e.employee_designation ILIKE %s OR cs.case_name ILIKE %s OR cl.client_name ILIKE %s)
             ORDER BY (e.employee_status = 'Active') DESC NULLS LAST, e.employee_name
             LIMIT %s
            """,
            (needle, like, like, like, like, like, DIRECTORY_LIMIT),
        )
        return [_clean(row) for row in _rows(cur)]


def profile(employee_code: str, with_pay: bool) -> dict[str, Any] | None:
    """One employee, or None when there is no such employee. Pay is read only when asked for."""
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT e.employee_code, e.employee_name, e.employee_designation, e.employee_type, e.employee_status, e.client_facing,
                   e.emp_start_date, e.emp_end_date, e.manager_code, m.employee_name AS manager_name,
                   e.employee_case_code AS case_code, cs.case_name, cs.client_code, cl.client_name
              FROM orion_ods.employee e
              LEFT JOIN orion_ods.employee m ON m.employee_code = e.manager_code
              LEFT JOIN orion_ods.case cs ON cs.case_code = e.employee_case_code
              LEFT JOIN orion_ods.client cl ON cl.client_code = cs.client_code
             WHERE e.employee_code = %s
            """,
            (employee_code,),
        )
        found = _rows(cur)
        if not found:
            return None
        employee = _clean(found[0])
        cur.execute(
            """
            SELECT employee_code, employee_name, employee_designation, employee_status
              FROM orion_ods.employee
             WHERE manager_code = %s
             ORDER BY (employee_status = 'Active') DESC NULLS LAST, employee_name
            """,
            (employee_code,),
        )
        reports = [_clean(row) for row in _rows(cur)]
        cur.execute(
            """
            SELECT contact_code, contact_name, client_code
              FROM orion_ods.contact
             WHERE relationship_owner_code = %s AND contact_status = 'Active'
             ORDER BY contact_name
            """,
            (employee_code,),
        )
        owns = [_clean(row) for row in _rows(cur)]
        pay = None
        if with_pay:
            cur.execute(
                """
                SELECT month_year, days_worked, salary_amount, salary_paid
                  FROM orion_ods.employee_transaction
                 WHERE employee_code = %s
                 ORDER BY transaction_date DESC NULLS LAST, employee_transaction_code DESC
                 LIMIT %s
                """,
                (employee_code, PAY_MONTHS),
            )
            pay = [_clean(row) for row in _rows(cur)]
    return {"employee": employee, "reports": reports, "relationships": owns, "pay": pay}
