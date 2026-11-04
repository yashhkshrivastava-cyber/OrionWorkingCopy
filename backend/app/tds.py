"""TDS that clients held back from payments: the ledger of it by financial year, and matching it to Form 26AS.

A client that pays a bill usually deducts TDS and pays the rest. The deduction is recorded WITH the payment, in ``billing.record_payment`` (the only
writer of ``bill_payment_deduction``: what it says is never changed, and a payment's reversal reverses it). This module reads them as a ledger the
accounts person can check against the client's Form 26AS, and writes only one thing: the tick that a TDS deduction was found in the 26AS
(``matched_26as_*`` and the certificate reference). The tax credit itself is claimed in the income-tax return, outside Orion.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from app import billing
from app.database import db_cursor

MAX_ROWS = 5000
MATCH_FILTERS = ("all", "matched", "unmatched")


class TdsError(ValueError):
    """Something the person can fix: said in words."""


def quarter(day: date) -> str:
    """The income-tax quarter a day falls in: Q1 April-June, Q2 July-September, Q3 October-December, Q4 January-March."""
    return f"Q{((day.month - 4) % 12) // 3 + 1}"


def sections() -> list[dict[str, Any]]:
    return [{"code": code, "label": label, "rate": float(rate)} for code, label, rate in billing.TDS_SECTIONS]


def suggestion(client_code: str | None = None, bill_code: str | None = None) -> dict[str, Any]:
    """The section and rate to suggest when a client's payment is recorded: what that client was last deducted under, else the usual one.

    It is only a hint for the person typing: the amount the client actually held back is what is recorded."""
    with db_cursor() as cur:
        if bill_code and not client_code:
            cur.execute("SELECT client_code FROM orion_ods.bill WHERE bill_code = %s", (bill_code,))
            row = cur.fetchone()
            client_code = row[0] if row else None
        if client_code:
            cur.execute(
                """
                SELECT d.section, d.rate
                  FROM orion_ods.bill_payment_deduction d
                  JOIN orion_ods.bill b ON b.bill_code = d.bill_code
                 WHERE d.kind = 'TDS' AND d.reversed_timestamp IS NULL AND b.client_code = %s AND d.rate IS NOT NULL
                 ORDER BY d.deduction_id DESC LIMIT 1
                """,
                (client_code,),
            )
            row = cur.fetchone()
            if row:
                return {"section": row[0], "rate": float(row[1]), "source": "last", "sections": sections()}
    code, _label, rate = billing.DEFAULT_TDS_SECTION
    return {"section": code, "rate": float(rate), "source": "default", "sections": sections()}


def _row(cur, row) -> dict[str, Any]:
    out = {col.name: value for col, value in zip(cur.description, row)}
    for key in ("amount", "rate"):
        if out.get(key) is not None:
            out[key] = float(out[key])
    out["received_date"] = out["received_date"].isoformat() if out.get("received_date") else None
    out["matched"] = out.pop("matched_26as_timestamp") is not None
    out["quarter"] = quarter(date.fromisoformat(out["received_date"])) if out["received_date"] else None
    out["fy_label"] = billing.fy_label(out["fy_start_year"])
    return out


def ledger(
    fy: int | None = None, client_code: str | None = None, section: str | None = None, match: str = "all", quarter_filter: str | None = None,
) -> dict[str, Any]:
    """Every TDS deduction not reversed, newest first, with the totals the 26AS check needs: all of it, what has been found in the 26AS and
    what has not yet, by client and by quarter."""
    if match not in MATCH_FILTERS:
        raise TdsError("Choose all, matched or not matched.")
    where = ["d.kind = 'TDS'", "d.reversed_timestamp IS NULL"]
    params: list[Any] = []
    if fy:
        where.append("d.fy_start_year = %s")
        params.append(fy)
    if client_code:
        where.append("b.client_code = %s")
        params.append(client_code)
    if section:
        where.append("d.section = %s")
        params.append(section.strip().upper()[:8])
    if match == "matched":
        where.append("d.matched_26as_timestamp IS NOT NULL")
    elif match == "unmatched":
        where.append("d.matched_26as_timestamp IS NULL")
    with db_cursor() as cur:
        cur.execute(
            f"""
            SELECT d.deduction_id, d.bill_code, b.bill_number, b.client_code, cl.client_name, d.received_date, d.fy_start_year, d.section, d.rate,
                   d.amount, d.transaction_code, d.matched_26as_timestamp, d.certificate_ref, mu.display_name AS matched_by_name
              FROM orion_ods.bill_payment_deduction d
              JOIN orion_ods.bill b ON b.bill_code = d.bill_code
              LEFT JOIN orion_ods.client cl ON cl.client_code = b.client_code
              LEFT JOIN orion_ods.app_user mu ON mu.id = d.matched_26as_by
             WHERE {' AND '.join(where)}
             ORDER BY d.received_date DESC, d.deduction_id DESC
             LIMIT %s
            """,
            (*params, MAX_ROWS),
        )
        rows = [_row(cur, row) for row in cur.fetchall()]
        cur.execute(
            "SELECT DISTINCT fy_start_year FROM orion_ods.bill_payment_deduction WHERE kind = 'TDS' AND reversed_timestamp IS NULL ORDER BY 1 DESC"
        )
        years = [{"fy_start_year": year, "label": billing.fy_label(year)} for (year,) in cur.fetchall()]
    if quarter_filter:
        rows = [row for row in rows if row["quarter"] == quarter_filter]
    total = sum((Decimal(str(row["amount"])) for row in rows), Decimal("0"))
    matched = sum((Decimal(str(row["amount"])) for row in rows if row["matched"]), Decimal("0"))
    by_client: dict[str, dict[str, Any]] = {}
    by_quarter: dict[str, Decimal] = {}
    for row in rows:
        entry = by_client.setdefault(row["client_code"] or "", {"client_code": row["client_code"], "client_name": row["client_name"], "total": Decimal("0"), "unmatched": Decimal("0"), "count": 0})
        entry["total"] += Decimal(str(row["amount"]))
        entry["count"] += 1
        if not row["matched"]:
            entry["unmatched"] += Decimal(str(row["amount"]))
        if row["quarter"]:
            by_quarter[row["quarter"]] = by_quarter.get(row["quarter"], Decimal("0")) + Decimal(str(row["amount"]))
    return {
        "rows": rows,
        "years": years,
        "totals": {"total": float(total), "matched": float(matched), "unmatched": float(total - matched), "count": len(rows)},
        "by_client": sorted(
            ({**entry, "total": float(entry["total"]), "unmatched": float(entry["unmatched"])} for entry in by_client.values()),
            key=lambda entry: (-entry["total"], entry["client_name"] or ""),
        ),
        "by_quarter": [{"quarter": q, "total": float(by_quarter[q])} for q in sorted(by_quarter)],
        "truncated": len(rows) >= MAX_ROWS,
    }


def set_matched(deduction_id: int, matched: bool, certificate_ref: Any, user_id: int | None) -> dict[str, Any]:
    """Tick a TDS deduction as found in the client's Form 26AS (with the certificate or 26AS reference, if the person has it), or take the tick off.

    Only a TDS deduction that has not been reversed can be ticked; nothing about the deduction itself changes."""
    ref = " ".join(str(certificate_ref or "").split())[:120] or None
    with db_cursor(commit=True) as cur:
        cur.execute(
            "SELECT kind, reversed_timestamp IS NOT NULL FROM orion_ods.bill_payment_deduction WHERE deduction_id = %s FOR UPDATE", (deduction_id,)
        )
        row = cur.fetchone()
        if not row:
            raise TdsError("That deduction does not exist.")
        if row[0] != "TDS":
            raise TdsError("Only TDS is matched to Form 26AS.")
        if row[1]:
            raise TdsError("That payment was reversed, so there is no deduction to match.")
        if matched:
            cur.execute(
                """
                UPDATE orion_ods.bill_payment_deduction
                   SET matched_26as_by = %s, matched_26as_timestamp = CURRENT_TIMESTAMP, certificate_ref = %s
                 WHERE deduction_id = %s
                """,
                (user_id, ref, deduction_id),
            )
        else:
            cur.execute(
                """
                UPDATE orion_ods.bill_payment_deduction
                   SET matched_26as_by = NULL, matched_26as_timestamp = NULL, certificate_ref = NULL
                 WHERE deduction_id = %s
                """,
                (deduction_id,),
            )
    return {"deduction_id": deduction_id, "matched": bool(matched), "certificate_ref": ref if matched else None}
