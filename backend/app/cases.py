"""A case's page: the site we serve, who works there, who we deal with, what has been spent on it and, for someone who may see billing, what has been billed and what is owed.

Read only. A case, its people and its expenses are changed in Operational Data; bills and payments in Billing. What is owed is the receivables report's own figure for the case's bills
(never a second calculation), and the money is only read for someone who may see billing.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from app import billing, receivables
from app.database import db_cursor

DIRECTORY_LIMIT = 500
RECENT = 8


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


def _money(value: Any) -> Decimal:
    return Decimal(str(value or 0))


def _owed_by_case() -> dict[str, dict[str, Any]]:
    """What each case owes, from the receivables report: the sum of the balances of its unpaid bills and the age of the oldest."""
    owed: dict[str, dict[str, Any]] = {}
    for client in receivables.list_receivables()["clients"]:
        for bill in client["bills"]:
            code = bill.get("case_code")
            if not code:
                continue
            entry = owed.setdefault(code, {"total": Decimal(0), "oldest_days": 0})
            entry["total"] += _money(bill["balance"])
            entry["oldest_days"] = max(entry["oldest_days"], int(bill["days"]))
    return owed


def directory(search: str | None, with_money: bool) -> list[dict[str, Any]]:
    """Every case with its client and how many people are on it (what each owes, for billing)."""
    needle = (search or "").strip()[:80]
    like = f"%{needle}%"
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT cs.case_code, cs.case_name, cs.case_status, cs.client_code, cl.client_name, cs.case_start_date,
                   (SELECT COUNT(*) FROM orion_ods.employee e WHERE e.employee_case_code = cs.case_code AND e.employee_status = 'Active') AS employees
              FROM orion_ods.case cs
              LEFT JOIN orion_ods.client cl ON cl.client_code = cs.client_code
             WHERE (%s = '' OR cs.case_name ILIKE %s OR cs.case_code ILIKE %s OR cl.client_name ILIKE %s)
             ORDER BY (cs.case_status = 'Active') DESC NULLS LAST, cs.case_name
             LIMIT %s
            """,
            (needle, like, like, like, DIRECTORY_LIMIT),
        )
        cases = [_clean(row) for row in _rows(cur)]
    if with_money:
        owed = _owed_by_case()
        for case in cases:
            entry = owed.get(case["case_code"])
            case["owed"] = float(entry["total"]) if entry else 0.0
            case["oldest_days"] = entry["oldest_days"] if entry else None
    return cases


def profile(case_code: str, with_money: bool) -> dict[str, Any] | None:
    """One case with its people, contacts, deposits and expenses, or None when there is no such case."""
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT cs.case_code, cs.case_name, cs.case_status, cs.case_start_date, cs.case_end_date, cs.monthly_expected_revenue, cs.monthly_allowed_km,
                   cs.client_code, cl.client_name, cap.capability_name, dom.business_domain_name
              FROM orion_ods.case cs
              LEFT JOIN orion_ods.client cl ON cl.client_code = cs.client_code
              LEFT JOIN orion_ods.capability cap ON cap.capability_code = cs.capability_code
              LEFT JOIN orion_ods.business_domain dom ON dom.business_domain_code = cs.business_domain_code
             WHERE cs.case_code = %s
            """,
            (case_code,),
        )
        found = _rows(cur)
        if not found:
            return None
        case = _clean(found[0])
        cur.execute(
            """
            SELECT employee_code, employee_name, employee_designation, employee_type, employee_status
              FROM orion_ods.employee
             WHERE employee_case_code = %s
             ORDER BY (employee_status = 'Active') DESC NULLS LAST, employee_name
            """,
            (case_code,),
        )
        people = [_clean(row) for row in _rows(cur)]
        cur.execute(
            """
            SELECT contact_code, contact_name, designation, contact_role, contact_status, is_primary_contact, email, phone, case_code
              FROM orion_ods.contact
             WHERE case_code = %s OR (case_code IS NULL AND client_code = %s AND is_primary_contact = 'Yes')
             ORDER BY (case_code IS NOT NULL) DESC, (contact_status = 'Active') DESC, contact_name
            """,
            (case_code, case["client_code"]),
        )
        contacts = [_clean(row) for row in _rows(cur)]
        cur.execute(
            """
            SELECT emd_code, tender_reference, emd_amount, emd_status, deposit_date, valid_until, refund_due_date
              FROM orion_ods.emd
             WHERE case_code = %s
             ORDER BY deposit_date DESC NULLS LAST, emd_code DESC
            """,
            (case_code,),
        )
        emds = [_clean(row) for row in _rows(cur)]
        cur.execute(
            """
            SELECT COALESCE(SUM(amount_after_tax_gst), 0) AS total, COUNT(*) AS count
              FROM orion_ods.expense_transaction
             WHERE case_code = %s AND transaction_status = 'Committed'
            """,
            (case_code,),
        )
        spent = _rows(cur)[0]
        cur.execute(
            """
            SELECT x.expense_code, x.transaction_date, x.amount_after_tax_gst AS amount, x.transaction_description AS description, t.expense_type_name AS expense_type
              FROM orion_ods.expense_transaction x
              LEFT JOIN orion_ods.expense_type t ON t.expense_type_code = x.expense_type_code
             WHERE x.case_code = %s AND x.transaction_status = 'Committed'
             ORDER BY x.transaction_date DESC NULLS LAST, x.expense_code DESC
             LIMIT %s
            """,
            (case_code, RECENT),
        )
        recent_expenses = [_clean(row) for row in _rows(cur)]
    result: dict[str, Any] = {
        "case": case,
        "people": people,
        "contacts": contacts,
        "emds": emds,
        "expenses": {"total": float(_money(spent["total"])), "count": int(spent["count"]), "recent": recent_expenses},
        "money": None,
    }
    if with_money:
        result["money"] = _money_block(case_code)
    return result


def _money_block(case_code: str) -> dict[str, Any]:
    bills = billing.list_bills(case_code=case_code, limit=2000)
    issued = [bill for bill in bills if bill["status"] == "Issued"]
    billed = sum((_money(bill["grand_total"]) for bill in issued), Decimal(0))
    received = sum((_money(bill["received_total"]) for bill in issued), Decimal(0))
    credited = sum((_money(bill.get("credited_amount")) for bill in issued), Decimal(0))
    entry = _owed_by_case().get(case_code)
    return {
        "bills": len(issued),
        "billed": float(billed),
        "received": float(received),
        "credited": float(credited),
        # What is owed is the receivables report's own balances for this case's bills, not billed minus received.
        "owed": float(entry["total"]) if entry else 0.0,
        "oldest_days": entry["oldest_days"] if entry else None,
        "recent": [
            {key: _plain(bill.get(key)) for key in ("id", "bill_number", "bill_date", "service_month", "case_name", "grand_total", "received_total", "credited_amount", "status", "gst_paid")}
            for bill in bills[:RECENT]
        ],
    }
