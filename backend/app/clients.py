"""A client's page: who they are, the cases and people at them and, for someone who may see billing, what has been billed to them and what they still owe.

Read only. Clients, cases and contacts are changed in Operational Data; bills and payments in Billing. Nothing here writes, and the money is never calculated a second time:
what is owed is the receivables report's figure for the client, and the totals are the sums of the same bill rows the bills register lists.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from app import billing, receivables
from app.database import db_cursor

RECENT_BILLS = 8
DIRECTORY_LIMIT = 500


def _rows(cur) -> list[dict[str, Any]]:
    columns = [col.name for col in cur.description]
    return [dict(zip(columns, row)) for row in cur.fetchall()]


def _plain(value: Any) -> Any:
    """Dates as ISO text and numbers as numbers, the way the rest of the API answers."""
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


def _clean(row: dict[str, Any]) -> dict[str, Any]:
    return {key: _plain(value) for key, value in row.items()}


def _money(value: Any) -> Decimal:
    return Decimal(str(value or 0))


def directory(search: str | None, with_money: bool) -> list[dict[str, Any]]:
    """Every client, active ones first, with how many cases it has and (for billing) what it owes."""
    needle = (search or "").strip()[:80]
    like = f"%{needle}%"
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT c.client_code, c.client_name, c.client_status, c.client_type, c.firm_priority,
                   c.client_location_city, c.client_location_state, g.client_name AS group_name,
                   (SELECT COUNT(*) FROM orion_ods.case cs WHERE cs.client_code = c.client_code) AS cases,
                   (SELECT COUNT(*) FROM orion_ods.case cs WHERE cs.client_code = c.client_code AND cs.case_status = 'Active') AS active_cases
              FROM orion_ods.client c
              LEFT JOIN orion_ods.client g ON g.client_code = c.client_group_code
             WHERE (%s = '' OR c.client_name ILIKE %s OR c.client_code ILIKE %s OR g.client_name ILIKE %s)
             ORDER BY (c.client_status = 'Active') DESC NULLS LAST, c.client_name
             LIMIT %s
            """,
            (needle, like, like, like, DIRECTORY_LIMIT),
        )
        clients = [_clean(row) for row in _rows(cur)]
    if with_money:
        owed = {entry["client_code"]: entry for entry in receivables.list_receivables()["clients"]}
        for client in clients:
            entry = owed.get(client["client_code"])
            client["owed"] = float(_money(entry["total"])) if entry else 0.0
            client["oldest_days"] = entry["oldest_days"] if entry else None
    return clients


def profile(client_code: str, with_money: bool) -> dict[str, Any] | None:
    """One client with its cases and contacts, or None when there is no such client."""
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT c.client_code, c.client_name, c.client_status, c.client_type, c.firm_priority, c.client_start_date, c.client_end_date,
                   c.client_onboarded, c.client_location_state, c.client_location_city, c.billing_name, c.gstin, c.billing_address,
                   c.client_group_code, g.client_name AS group_name
              FROM orion_ods.client c
              LEFT JOIN orion_ods.client g ON g.client_code = c.client_group_code
             WHERE c.client_code = %s
            """,
            (client_code,),
        )
        found = _rows(cur)
        if not found:
            return None
        client = _clean(found[0])
        cur.execute(
            """
            SELECT cs.case_code, cs.case_name, cs.case_status, cs.case_start_date, cs.case_end_date, cs.monthly_expected_revenue,
                   (SELECT COUNT(*) FROM orion_ods.employee e WHERE e.employee_case_code = cs.case_code AND e.employee_status = 'Active') AS employees
              FROM orion_ods.case cs
             WHERE cs.client_code = %s
             ORDER BY (cs.case_status = 'Active') DESC NULLS LAST, cs.case_name
            """,
            (client_code,),
        )
        cases = [_clean(row) for row in _rows(cur)]
        cur.execute(
            """
            SELECT contact_code, contact_name, designation, contact_role, contact_status, is_primary_contact, email, phone, case_code
              FROM orion_ods.contact
             WHERE client_code = %s
             ORDER BY (is_primary_contact = 'Yes') DESC, (contact_status = 'Active') DESC, contact_name
            """,
            (client_code,),
        )
        contacts = [_clean(row) for row in _rows(cur)]
        cur.execute(
            "SELECT client_code, client_name, client_status FROM orion_ods.client WHERE client_group_code = %s ORDER BY client_name",
            (client_code,),
        )
        members = [_clean(row) for row in _rows(cur)]
    result: dict[str, Any] = {"client": client, "cases": cases, "contacts": contacts, "members": members, "money": None}
    if with_money:
        result["money"] = _money_block(client_code)
    return result


def _money_block(client_code: str) -> dict[str, Any]:
    bills = billing.list_bills(client_code=client_code, limit=2000)
    issued = [bill for bill in bills if bill["status"] == "Issued"]
    billed = sum((_money(bill["grand_total"]) for bill in issued), Decimal(0))
    received = sum((_money(bill["received_total"]) for bill in issued), Decimal(0))
    credited = sum((_money(bill.get("credited_amount")) for bill in issued), Decimal(0))
    statement = receivables.client_statement(client_code)
    return {
        "bills": len(issued),
        "billed": float(billed),
        "received": float(received),
        "credited": float(credited),
        # What is owed is the receivables report's own figure for the client, not a second calculation.
        "owed": float(_money(statement["total"])) if statement else 0.0,
        "oldest_days": statement["oldest_days"] if statement else None,
        "buckets": [float(_money(value)) for value in statement["buckets"]] if statement else [],
        "bucket_labels": statement["bucket_labels"] if statement else [],
        "last_reminder": statement.get("last_reminder") if statement else None,
        "recent": [
            {key: _plain(bill.get(key)) for key in ("id", "bill_number", "bill_date", "service_month", "case_name", "grand_total", "received_total", "credited_amount", "status", "gst_paid")}
            for bill in bills[:RECENT_BILLS]
        ],
    }
