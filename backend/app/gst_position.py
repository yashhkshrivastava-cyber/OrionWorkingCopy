"""The GST position by month: the GST on the bills raised, the input tax credit on the costs, and what is left to pay.

Output GST is the CGST and SGST on the issued bills of the month (by the bill's date), less the GST on the credit notes dated in the month (a credit
note adjusts the tax in the month it is issued, not the month of the bill). Input tax credit is the GST on the costs that have happened
(the status Incurred) and carry the supplier's GSTIN and invoice number, by the cost's date. Net is the output less the credit notes less the credit; a month where the
credit is more than the tax is a credit carried forward, not money back. GST paid is what has been recorded as paid on bills (``bill_gst_payment``),
by the day it was paid.

This is a planning view of what the books say, not the return: reverse charge, blocked credits, credit notes' timing and the supplier's own filing
(a credit is allowed only once the supplier has filed) are outside Orion. The return is filed on the GST portal.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from app import billing
from app.database import db_cursor

ZERO = Decimal("0")
MONTH_NAMES = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def fy_months(start_year: int) -> list[date]:
    """The first day of each month of the financial year: April of the year to March of the next."""
    return [date(start_year, month, 1) for month in range(4, 13)] + [date(start_year + 1, month, 1) for month in range(1, 4)]


def build_position(
    start_year: int, output: dict[date, Decimal], credit: dict[date, Decimal], paid: dict[date, Decimal], today: date | None = None,
    notes: dict[date, Decimal] | None = None,
) -> dict[str, Any]:
    """The twelve months of a financial year from what was found in each (the first day of a month keys it). ``notes`` is the GST on approved credit
    notes by the month of the note, which comes off the output."""
    today = today or date.today()
    notes = notes or {}
    months, running = [], ZERO
    totals = {"output": ZERO, "notes": ZERO, "credit": ZERO, "net": ZERO, "paid": ZERO}
    for first in fy_months(start_year):
        out, adj, itc, pay = output.get(first, ZERO), notes.get(first, ZERO), credit.get(first, ZERO), paid.get(first, ZERO)
        net = out - adj - itc
        running += net
        months.append(
            {
                "month": first.isoformat(), "label": f"{MONTH_NAMES[first.month - 1]} {first.year}", "output": float(out), "notes": float(adj), "credit": float(itc),
                "net": float(net), "running_net": float(running), "paid": float(pay), "future": first > date(today.year, today.month, 1),
            }
        )
        totals["output"] += out
        totals["notes"] += adj
        totals["credit"] += itc
        totals["net"] += net
        totals["paid"] += pay
    return {"fy_start_year": start_year, "fy_label": billing.fy_label(start_year), "months": months, "totals": {k: float(v) for k, v in totals.items()}}


def _by_month(rows) -> dict[date, Decimal]:
    return {row[0]: Decimal(str(row[1] or 0)) for row in rows}


def position(start_year: int) -> dict[str, Any]:
    first, after = date(start_year, 4, 1), date(start_year + 1, 4, 1)
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT date_trunc('month', bill_date)::date, SUM(COALESCE(cgst_amount, 0) + COALESCE(sgst_amount, 0))
              FROM orion_ods.bill WHERE status = 'Issued' AND bill_date >= %s AND bill_date < %s GROUP BY 1
            """,
            (first, after),
        )
        output = _by_month(cur.fetchall())
        cur.execute(
            """
            SELECT date_trunc('month', transaction_date)::date, SUM(gst)
              FROM orion_ods.expense_transaction
             WHERE transaction_status = 'Committed' AND COALESCE(gst, 0) > 0 AND vendor_gstin IS NOT NULL AND vendor_invoice_no IS NOT NULL
               AND transaction_date >= %s AND transaction_date < %s GROUP BY 1
            """,
            (first, after),
        )
        credit = _by_month(cur.fetchall())
        cur.execute(
            """
            SELECT date_trunc('month', note_date)::date, SUM(cgst + sgst) FROM orion_ods.credit_note
             WHERE status = 'Approved' AND note_date >= %s AND note_date < %s GROUP BY 1
            """,
            (first, after),
        )
        notes = _by_month(cur.fetchall())
        cur.execute(
            """
            SELECT date_trunc('month', COALESCE(paid_date, recorded_timestamp::date))::date, SUM(amount)
              FROM orion_ods.bill_gst_payment
             WHERE reversed_timestamp IS NULL AND COALESCE(paid_date, recorded_timestamp::date) >= %s AND COALESCE(paid_date, recorded_timestamp::date) < %s
             GROUP BY 1
            """,
            (first, after),
        )
        paid = _by_month(cur.fetchall())
        cur.execute(
            """
            SELECT COUNT(*), COALESCE(SUM(gst), 0) FROM orion_ods.expense_transaction
             WHERE transaction_status = 'Committed' AND COALESCE(gst, 0) > 0 AND (vendor_gstin IS NULL OR vendor_invoice_no IS NULL)
               AND transaction_date >= %s AND transaction_date < %s
            """,
            (first, after),
        )
        without_count, without_gst = cur.fetchone()
        cur.execute(
            """
            SELECT vendor_gstin, COUNT(*), SUM(gst) FROM orion_ods.expense_transaction
             WHERE transaction_status = 'Committed' AND COALESCE(gst, 0) > 0 AND vendor_gstin IS NOT NULL AND vendor_invoice_no IS NOT NULL
               AND transaction_date >= %s AND transaction_date < %s
             GROUP BY vendor_gstin ORDER BY SUM(gst) DESC LIMIT 10
            """,
            (first, after),
        )
        suppliers = [{"gstin": g, "expenses": n, "credit": float(c)} for g, n, c in cur.fetchall()]
        cur.execute(
            """
            SELECT DISTINCT CASE WHEN EXTRACT(MONTH FROM d) >= 4 THEN EXTRACT(YEAR FROM d) ELSE EXTRACT(YEAR FROM d) - 1 END::int
              FROM (SELECT bill_date AS d FROM orion_ods.bill WHERE status = 'Issued'
                    UNION ALL SELECT transaction_date FROM orion_ods.expense_transaction WHERE COALESCE(gst, 0) > 0) x
             WHERE d IS NOT NULL ORDER BY 1 DESC
            """
        )
        years = [{"fy_start_year": y, "label": billing.fy_label(y)} for (y,) in cur.fetchall()]
    result = build_position(start_year, output, credit, paid, notes=notes)
    result["without_gstin"] = {"count": without_count, "gst": float(without_gst)}
    result["suppliers"] = suppliers
    result["years"] = years
    return result
