"""EPFO and ESIC by month: what the bills charged for them, what has been paid over, and which bills still have something to pay.

Charged is the EPFO and the ESIC on the issued bills of the month (by the bill's date). Paid is what has been recorded as paid on bills
(``bill_statutory_payment``, a reversed payment counts for nothing), by the day it was paid. A payment is for a bill, so a month can be paid more than it was
charged (the bills of earlier months are being paid) and a bill can be paid in a later financial year than it was raised in: the figures that answer "what is still
to pay" are therefore taken over all bills, not one year.

This does not change Revenue: EPFO and ESIC are inside the bills' taxable value, as before. It says whether the money has gone to the authority; once paid over it is a cost on the day paid (the view orion_dw.expense_cost). It is not the
return or the challan: those are made on the EPFO and ESIC portals.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from app import billing
from app.database import db_cursor
from app.gst_position import MONTH_NAMES, fy_months

ZERO = Decimal("0")
OLDEST = 50  # bills listed, oldest first: what to pay next

_LEFT_EPFO = "GREATEST(b.epf_amount - COALESCE(b.epf_paid_amount, 0), 0)"
_LEFT_ESIC = "GREATEST(b.esic_amount - COALESCE(b.esic_paid_amount, 0), 0)"
_OPEN = f"({_LEFT_EPFO} > 0.004 OR {_LEFT_ESIC} > 0.004)"


def build_position(
    start_year: int, charged: dict[date, tuple[Decimal, Decimal]], paid: dict[date, tuple[Decimal, Decimal]], today: date | None = None
) -> dict[str, Any]:
    """The twelve months of a financial year from what was found in each (the first day of a month keys it)."""
    today = today or date.today()
    months, running = [], ZERO
    totals = {"epfo_charged": ZERO, "esic_charged": ZERO, "epfo_paid": ZERO, "esic_paid": ZERO}
    for first in fy_months(start_year):
        epfo_c, esic_c = charged.get(first, (ZERO, ZERO))
        epfo_p, esic_p = paid.get(first, (ZERO, ZERO))
        net = (epfo_c + esic_c) - (epfo_p + esic_p)
        running += net
        months.append(
            {
                "month": first.isoformat(), "label": f"{MONTH_NAMES[first.month - 1]} {first.year}",
                "epfo_charged": float(epfo_c), "esic_charged": float(esic_c), "epfo_paid": float(epfo_p), "esic_paid": float(esic_p),
                "net": float(net), "running_net": float(running), "future": first > date(today.year, today.month, 1),
            }
        )
        totals["epfo_charged"] += epfo_c
        totals["esic_charged"] += esic_c
        totals["epfo_paid"] += epfo_p
        totals["esic_paid"] += esic_p
    return {
        "fy_start_year": start_year, "fy_label": billing.fy_label(start_year), "months": months,
        "totals": {key: float(value) for key, value in totals.items()},
    }


def position(start_year: int) -> dict[str, Any]:
    first, after = date(start_year, 4, 1), date(start_year + 1, 4, 1)
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT date_trunc('month', bill_date)::date, COALESCE(SUM(epf_amount), 0), COALESCE(SUM(esic_amount), 0)
              FROM orion_ods.bill WHERE status = 'Issued' AND bill_date >= %s AND bill_date < %s GROUP BY 1
            """,
            (first, after),
        )
        charged = {row[0]: (Decimal(str(row[1])), Decimal(str(row[2]))) for row in cur.fetchall()}
        cur.execute(
            """
            SELECT date_trunc('month', paid_date)::date,
                   COALESCE(SUM(amount) FILTER (WHERE component = 'EPFO'), 0), COALESCE(SUM(amount) FILTER (WHERE component = 'ESIC'), 0)
              FROM orion_ods.bill_statutory_payment
             WHERE reversed_timestamp IS NULL AND paid_date >= %s AND paid_date < %s GROUP BY 1
            """,
            (first, after),
        )
        paid = {row[0]: (Decimal(str(row[1])), Decimal(str(row[2]))) for row in cur.fetchall()}
        cur.execute(
            f"""
            SELECT COUNT(*) FILTER (WHERE {_OPEN}), COALESCE(SUM({_LEFT_EPFO}), 0), COALESCE(SUM({_LEFT_ESIC}), 0), MIN(b.bill_date) FILTER (WHERE {_OPEN})
              FROM orion_ods.bill b WHERE b.status = 'Issued'
            """
        )
        open_bills, open_epfo, open_esic, oldest_day = cur.fetchone()
        cur.execute(
            f"""
            SELECT b.bill_code, b.bill_number, b.bill_date, COALESCE(cl.client_name, b.party_name), {_LEFT_EPFO}, {_LEFT_ESIC}
              FROM orion_ods.bill b LEFT JOIN orion_ods.client cl ON cl.client_code = b.client_code
             WHERE b.status = 'Issued' AND {_OPEN}
             ORDER BY b.bill_date, b.bill_seq LIMIT {OLDEST}
            """
        )
        oldest = [
            {"id": code, "bill_number": number, "bill_date": day.isoformat(), "client": client, "epfo": float(epfo), "esic": float(esic)}
            for code, number, day, client, epfo, esic in cur.fetchall()
        ]
        cur.execute(
            """
            SELECT DISTINCT CASE WHEN EXTRACT(MONTH FROM bill_date) >= 4 THEN EXTRACT(YEAR FROM bill_date) ELSE EXTRACT(YEAR FROM bill_date) - 1 END::int
              FROM orion_ods.bill WHERE status = 'Issued' AND bill_date IS NOT NULL ORDER BY 1 DESC
            """
        )
        years = [{"fy_start_year": y, "label": billing.fy_label(y)} for (y,) in cur.fetchall()]
    result = build_position(start_year, charged, paid)
    result["open"] = {
        "bills": int(open_bills or 0), "epfo": float(open_epfo or 0), "esic": float(open_esic or 0),
        "oldest_bill_date": oldest_day.isoformat() if oldest_day else None,
    }
    result["oldest"] = oldest
    result["years"] = years
    return result
