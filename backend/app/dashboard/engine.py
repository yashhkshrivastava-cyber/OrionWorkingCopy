"""Measures, comparisons and KPI cards for the Orion dashboards, read from the warehouse.

``Dash`` is one request's worth of context: the cleaned filters, the windows to compare with, and every aggregate the
views and insights share, each worked out once on first use. The views only describe what to plot.

Revenue is the taxable value of issued bills, by the month the service was for. Cash is the payments recorded against
those bills, by the day they were received. Cost is payroll plus operating expenses. Money that clients still owe is a
snapshot as at the last warehouse load, so it follows the segment filters but not the period.
"""

from __future__ import annotations

from datetime import date, timedelta
from functools import cached_property
from typing import Any, Callable

from app.dashboard.filters import (
    BILL_AGE,
    BILL_OPEN,
    BUCKET_ORDER,
    SCOPES,
    clause,
    clean_filters,
    common,
    data_span,
    day_label,
    delta,
    inr,
    kpi,
    month_label,
    num,
    qty,
    rows,
)
from app.dashboard.kpi_help import KPI_HELP, SCOPE_PERIOD, SCOPE_SNAPSHOT
from app.dashboard.measures import category, merge_months, month_series, scalars
from app.dashboard.windows import comparison_windows, fy_label, parse_day, resolve_fy, selected_window, validate_filters

# ---- money expressions, written once -----------------------------------------------------------------------------
REVENUE = "COALESCE(SUM(b.taxable_total - COALESCE(b.credited_taxable, 0)), 0)"
BILLED = "COALESCE(SUM(b.grand_total - COALESCE(b.credited_amount, 0)), 0)"
GST = "COALESCE(SUM(b.cgst_amount + b.sgst_amount - COALESCE(b.credited_cgst, 0) - COALESCE(b.credited_sgst, 0)), 0)"
# What bills charged for EPFO and ESIC and has not been shown as paid over (paid is recorded on each bill, like GST). They stay inside Revenue; this is
# whether the money has gone to the authority (once paid over it is a cost, on the day paid, through orion_dw.expense_cost). A credit note does not lower it: what is owed follows the wages, not the bill.
EPF_UNPAID = "COALESCE(SUM(GREATEST(b.epf_amount - COALESCE(b.epf_paid_amount, 0), 0)), 0)"
ESIC_UNPAID = "COALESCE(SUM(GREATEST(b.esic_amount - COALESCE(b.esic_paid_amount, 0), 0)), 0)"
# Cash collected is what reached the bank: a payment's revenue entry holds the cash PLUS what the client held back (TDS and the like), so the cash is the entry
# less that. SETTLED is the whole (what the payment took off the bills), which is what a collection rate is measured with.
COLLECTED = "COALESCE(SUM(t.amount_after_tax_gst - COALESCE(t.deducted_amount, 0)), 0)"
SETTLED = "COALESCE(SUM(t.amount_after_tax_gst), 0)"
TDS_HELD = "COALESCE(SUM(COALESCE(t.deducted_amount, 0)), 0)"
CREDITED = "COALESCE(SUM(b.credited_amount), 0)"
# Input tax credit: the GST on costs that have happened and carry the supplier's GSTIN and invoice number (the same rule as Utility > GST).
ITC = (
    "COALESCE(SUM(e.gst) FILTER (WHERE e.transaction_status = 'Committed' AND COALESCE(e.gst, 0) > 0"
    " AND e.vendor_gstin IS NOT NULL AND e.vendor_invoice_no IS NOT NULL), 0)"
)
ITC_MISSING = (
    "COALESCE(SUM(e.gst) FILTER (WHERE e.transaction_status = 'Committed' AND COALESCE(e.gst, 0) > 0"
    " AND (e.vendor_gstin IS NULL OR e.vendor_invoice_no IS NULL)), 0)"
)
EXPENSE = "COALESCE(SUM(e.transaction_amount), 0)"
SALARY = "COALESCE(SUM(et.salary_amount), 0)"
OPEN = f"COALESCE(SUM({BILL_OPEN}), 0)"
KM = "COALESCE(SUM(ct.driven_km), 0)"
FLEET_COST = "COALESCE(SUM(ct.driven_km * COALESCE(car.per_km_price, 0)), 0)"

PERIOD_KEYS = ("month", "fy", "from", "to")
OPEN_STAGES = "('Proposal', 'Qualified', 'Technical Bid', 'Financial Bid')"
DECIDED_STAGES = "('Closed Won', 'Closed Lost', 'Disqualified')"

# Dimension -> (code expression, label expression). Every case-linked fact aliases its dimensions the same way, so one
# entry serves the bills, payroll and expense scopes alike.
DIMENSIONS: dict[str, tuple[str, str]] = {
    "business_domain": ("bd.business_domain_code", "bd.business_domain_name"),
    "capability": ("cap.capability_code", "cap.capability_name"),
    "client": ("cl.client_code", "cl.client_name"),
    "case": ("c.case_code", "c.case_name"),
    "client_type": ("cl.client_type", "cl.client_type"),
    "state": ("cl.client_location_state", "cl.client_location_state"),
    "priority": ("cl.firm_priority", "cl.firm_priority"),
}

UNALLOCATED = "Head office and unallocated"

_UNSET: Any = object()


def pct(part: float, whole: float) -> float:
    return part / whole * 100 if whole else 0.0


def _range_text(start: date | None, end: date | None) -> str:
    if not start or not end:
        return ""
    if start == end:
        return day_label(start.isoformat())
    return f"{day_label(start.isoformat())} – {day_label(end.isoformat())}"


def _filters_range(filters: dict[str, str]) -> str:
    return _range_text(parse_day(filters.get("from")), parse_day(filters.get("to")))


def without_period(filters: dict[str, str]) -> dict[str, str]:
    """The segment filters alone: what a balance as at today still respects."""
    return {k: v for k, v in filters.items() if k not in PERIOD_KEYS and k != "status"}


# ------------------------------------------------------------------------------------------------------------------
# aggregates
# ------------------------------------------------------------------------------------------------------------------


def period_totals(cur, filters: dict[str, str]) -> dict[str, float]:
    """Every period figure for one selection."""
    bill = scalars(
        cur,
        "bill",
        filters,
        {
            "revenue": REVENUE,
            "billed": BILLED,
            "gst": GST,
            "bills": "COUNT(*)",
            "clients": "COUNT(DISTINCT cl.client_code)",
            "cases_billed": "COUNT(DISTINCT c.case_code)",
            "edited": "COUNT(*) FILTER (WHERE b.version_no > 1)",
            "credited": CREDITED,
            "credit_notes": "COUNT(*) FILTER (WHERE COALESCE(b.credited_amount, 0) > 0)",
            "gst_unpaid": "COALESCE(SUM(b.cgst_amount + b.sgst_amount - COALESCE(b.credited_cgst, 0) - COALESCE(b.credited_sgst, 0) - COALESCE(b.gst_paid_amount, 0)) FILTER (WHERE NOT b.gst_paid), 0)",
            "epf_unpaid": EPF_UNPAID,
            "esic_unpaid": ESIC_UNPAID,
            "days_to_collect": f"COALESCE(AVG(p.last_received - b.bill_date) FILTER (WHERE {BILL_OPEN} < 1 AND p.last_received IS NOT NULL), 0)",
        },
    )
    cancelled = scalars(
        cur,
        "bill",
        {k: v for k, v in filters.items() if k != "status"},
        {
            "cancelled": "COUNT(*) FILTER (WHERE b.status = 'Cancelled')",
            "cancelled_value": "COALESCE(SUM(b.grand_total) FILTER (WHERE b.status = 'Cancelled'), 0)",
        },
        include_cancelled=True,
    )
    cash = scalars(cur, "collection", filters, {"collected": COLLECTED, "settled": SETTLED, "tds_held": TDS_HELD, "receipts": "COUNT(*)"})
    spend = scalars(cur, "expense", filters, {"expenses": EXPENSE, "itc": ITC, "itc_missing": ITC_MISSING})
    pay = scalars(
        cur,
        "payroll",
        filters,
        {
            "payroll": SALARY,
            "salary_pending": "COALESCE(SUM(et.salary_amount) FILTER (WHERE et.salary_paid = 'No'), 0)",
            "pay_rows": "COUNT(*)",
            "pay_months": "COUNT(DISTINCT et.month_year)",
            "days_worked": "COALESCE(AVG(et.days_worked), 0)",
        },
    )
    # The margin is worked out on the dimensions revenue, expense and payroll all carry, so a selection only one of
    # them understands cannot shrink one side of the sum.
    shared = common(filters, "bill", "expense", "payroll")
    rev_c = scalars(cur, "bill", shared, {"v": REVENUE})["v"]
    exp_c = scalars(cur, "expense", shared, {"v": EXPENSE})["v"]
    pay_c = scalars(cur, "payroll", shared, {"v": SALARY})["v"]
    fleet = scalars(cur, "fleet", filters, {"km": KM, "fleet_cost": FLEET_COST, "days": "COUNT(DISTINCT ct.driving_date)"})
    opp = scalars(
        cur,
        "opportunity",
        filters,
        {
            "opps": "COUNT(*)",
            "won": "COUNT(*) FILTER (WHERE o.opportunity_status = 'Closed Won')",
            "decided": f"COUNT(*) FILTER (WHERE o.opportunity_status IN {DECIDED_STAGES})",
            "open_opps": f"COUNT(*) FILTER (WHERE o.opportunity_status IN {OPEN_STAGES})",
            "pipeline_staff": f"COALESCE(SUM(o.workers) FILTER (WHERE o.opportunity_status IN {OPEN_STAGES}), 0)",
        },
    )

    out: dict[str, float] = {**bill, **cancelled, **cash, **spend, **pay, **fleet, **opp}
    out["cost"] = out["payroll"] + out["expenses"]
    out["net_gst"] = out["gst"] - out["itc"]  # the GST on bills (after credit notes) less the credit on costs; below zero is a credit carried forward
    out["margin"] = rev_c - exp_c - pay_c
    out["margin_revenue"] = rev_c
    out["margin_pct"] = pct(out["margin"], rev_c)
    out["payroll_pct"] = pct(pay_c, rev_c)
    out["expense_pct"] = pct(exp_c, rev_c)
    out["avg_bill"] = out["billed"] / out["bills"] if out["bills"] else 0.0
    # Cash and billing are compared on the dimensions both carry: a payment-status or ageing filter narrows the bills
    # alone, and a ratio of the two would otherwise be nonsense.
    pair = common(filters, "bill", "collection")
    pair_billed = scalars(cur, "bill", pair, {"v": BILLED})["v"]
    pair_cash = scalars(cur, "collection", pair, {"v": SETTLED})["v"]  # cash and TDS: a bill paid net of TDS is paid
    out["collection_rate"] = pct(pair_cash, pair_billed)
    out["heads"] = out["pay_rows"] / out["pay_months"] if out["pay_months"] else 0.0
    out["rev_per_head"] = out["revenue"] / out["pay_rows"] if out["pay_rows"] else 0.0
    out["cost_per_km"] = out["fleet_cost"] / out["km"] if out["km"] else 0.0
    out["win_rate"] = pct(out["won"], out["decided"])
    return out


def snapshot_totals(cur, filters: dict[str, str]) -> dict[str, Any]:
    """Balances as at the last load: what is owed, what is running, who is employed."""
    seg = without_period(filters)
    owed = scalars(
        cur,
        "bill",
        seg,
        {
            "outstanding": OPEN,
            "open_bills": f"COUNT(*) FILTER (WHERE {BILL_OPEN} >= 1)",
            "over30": f"COALESCE(SUM({BILL_OPEN}) FILTER (WHERE {BILL_AGE} > 30), 0)",
            "over60": f"COALESCE(SUM({BILL_OPEN}) FILTER (WHERE {BILL_AGE} > 60), 0)",
            "over90": f"COALESCE(SUM({BILL_OPEN}) FILTER (WHERE {BILL_AGE} > 90), 0)",
        },
    )
    # Days of billing outstanding must not be narrowed by an ageing or payment filter on one side only.
    plain = {k: v for k, v in seg.items() if k not in ("bucket", "pay_status")}
    recent = scalars(cur, "bill", plain, {"billed": BILLED}, extra=[f"{BILL_AGE} <= 90"])["billed"]
    owed_all = scalars(cur, "bill", plain, {"v": OPEN})["v"]
    cases = scalars(
        cur,
        "case",
        seg,
        {
            "active_cases": "COUNT(*) FILTER (WHERE c.case_status = 'Active')",
            "run_rate": "COALESCE(SUM(c.monthly_expected_revenue) FILTER (WHERE c.case_status = 'Active'), 0)",
        },
    )
    heads = scalars(cur, "employee", seg, {"headcount": "COUNT(*) FILTER (WHERE emp.employee_status = 'Active')"})
    out: dict[str, Any] = {**owed, **cases, **heads}
    out["dso"] = owed_all / recent * 90 if recent else 0.0
    out["overdue_pct"] = pct(out["over90"], out["outstanding"])
    out["buckets"] = category(
        cur,
        scope="bill",
        filters=seg,
        dimension="bucket",
        code=SCOPES["bill"]["fields"]["bucket"],
        value=OPEN,
        having=f"{OPEN} > 0",
        order_by_list=BUCKET_ORDER,
    )
    out["unbilled"] = unbilled_cases(cur, seg)
    return out


def unbilled_cases(cur, filters: dict[str, str]) -> dict[str, Any]:
    """Active cases that were billed for the month before the latest service month but not for the latest one."""
    latest = rows(cur, "SELECT MAX(service_month) FROM orion_dw.fact_bill WHERE is_current AND NOT is_expired")[0][0]
    if not latest:
        return {"count": 0, "names": [], "month": ""}
    where, params = clause("case", filters, extra=["c.case_status = 'Active'"])
    sql = (
        f"SELECT c.case_code, c.case_name FROM {SCOPES['case']['from']}{where}"
        " AND EXISTS (SELECT 1 FROM orion_dw.fact_bill pb WHERE pb.case_code = c.case_code AND pb.is_current AND NOT pb.is_expired"
        " AND pb.status = 'Issued' AND pb.service_month = (%s::date - INTERVAL '1 month')::date)"
        " AND NOT EXISTS (SELECT 1 FROM orion_dw.fact_bill lb WHERE lb.case_code = c.case_code AND lb.is_current AND NOT lb.is_expired"
        " AND lb.status = 'Issued' AND lb.service_month = %s::date)"
        " ORDER BY c.case_name"
    )
    found = rows(cur, sql, [*params, latest, latest])
    return {
        "count": len(found),
        "names": [r[1] for r in found],
        "codes": [r[0] for r in found],
        "month": month_label(latest.strftime("%Y-%m")),
    }


def trend(cur, filters: dict[str, str]) -> list[dict[str, Any]]:
    """Revenue, cash, cost and margin by month. Every month stays in view so a click can be undone."""
    shared = common(filters, "bill", "collection", "expense", "payroll")
    bills = month_series(
        cur, scope="bill", filters=shared,
        metrics={"revenue": REVENUE, "billed": BILLED, "gst": GST, "bills": "COUNT(*)"},
    )
    cash = month_series(cur, scope="collection", filters=shared, metrics={"collected": COLLECTED, "settled": SETTLED})
    spend = month_series(cur, scope="expense", filters=shared, metrics={"expenses": EXPENSE})
    pay = month_series(cur, scope="payroll", filters=shared, metrics={"payroll": SALARY, "heads": "COUNT(*)"})
    # A trailing month with only cash in it is the month in progress; leave it to the collections charts.
    service_months = set(bills) | set(pay) | set(spend)
    last = max(service_months) if service_months else ""

    def derive(point: dict[str, Any]) -> dict[str, Any]:
        cost = point["payroll"] + point["expenses"]
        margin = point["revenue"] - cost
        return {
            "cost": round(cost, 2),
            "margin": round(margin, 2),
            "margin_pct": round(pct(margin, point["revenue"]), 1),
            "collection_rate": round(pct(point["settled"], point["billed"]), 1) if point["billed"] else None,
        }

    points = merge_months(bills, cash, spend, pay, derive=derive)
    return [p for p in points if not last or p["code"] <= last]


def cash_trend(cur, filters: dict[str, str]) -> list[dict[str, Any]]:
    """Billed against collected by month, including the month in progress."""
    shared = common(filters, "bill", "collection")
    bills = month_series(cur, scope="bill", filters=shared, metrics={"billed": BILLED})
    cash = month_series(cur, scope="collection", filters=shared, metrics={"collected": COLLECTED, "settled": SETTLED, "tds": TDS_HELD})
    return merge_months(
        bills, cash, derive=lambda p: {"rate": round(pct(p["settled"], p["billed"]), 1) if p["billed"] else None, "gap": round(p["billed"] - p["settled"], 2)}
    )


def pnl_by(cur, filters: dict[str, str], dimension: str, *, limit: int | None = None) -> list[dict[str, Any]]:
    """Revenue, cash, cost and margin for each value of a dimension, on the dimensions the facts share."""
    code, label = DIMENSIONS[dimension]
    shared = common(filters, "bill", "expense", "payroll", "collection")

    def grouped(scope: str, metrics: dict[str, str], **kw) -> dict[str, dict[str, Any]]:
        where, params = clause(scope, shared, exclude=(dimension,), **kw)
        select = ", ".join(metrics.values())
        sql = f"SELECT {code}, {label}, {select} FROM {SCOPES[scope]['from']}{where} GROUP BY 1, 2"
        out: dict[str, dict[str, Any]] = {}
        for row in rows(cur, sql, params):
            # Cost with no case behind it (head office staff) is kept, under an empty code, so the rows add up to the total.
            key = "" if row[0] is None else str(row[0])
            entry = {"label": row[1] or row[0] or UNALLOCATED}
            for index, name in enumerate(metrics):
                entry[name] = num(row[2 + index])
            out[key] = entry
        return out

    bills = grouped("bill", {"revenue": REVENUE, "billed": BILLED, "bills": "COUNT(*)"})
    cash = grouped("collection", {"collected": COLLECTED})
    spend = grouped("expense", {"expenses": EXPENSE})
    pay = grouped("payroll", {"payroll": SALARY, "pay_rows": "COUNT(*)"})
    codes = set(bills) | set(spend) | set(pay)
    total_revenue = sum(v["revenue"] for v in bills.values())
    result = []
    for key in codes:
        r = bills.get(key, {})
        revenue = r.get("revenue", 0.0)
        payroll = pay.get(key, {}).get("payroll", 0.0)
        expenses = spend.get(key, {}).get("expenses", 0.0)
        margin = revenue - payroll - expenses
        label_text = (UNALLOCATED if key == "" else r.get("label") or pay.get(key, {}).get("label") or spend.get(key, {}).get("label") or key)
        result.append(
            {
                "code": key,
                "label": label_text,
                "revenue": round(revenue, 2),
                "billed": round(r.get("billed", 0.0), 2),
                "bills": int(r.get("bills", 0)),
                "collected": round(cash.get(key, {}).get("collected", 0.0), 2),
                "payroll": round(payroll, 2),
                "expenses": round(expenses, 2),
                "cost": round(payroll + expenses, 2),
                "margin": round(margin, 2),
                "margin_pct": round(pct(margin, revenue), 1),
                "share": round(pct(revenue, total_revenue), 1),
                "heads": round(pay.get(key, {}).get("pay_rows", 0.0), 0),
            }
        )
    result.sort(key=lambda row: row["revenue"], reverse=True)
    return result[:limit] if limit else result


def client_revenue_map(cur, filters: dict[str, str]) -> dict[str, tuple[str, float]]:
    """Revenue by client code for one selection, for finding which clients moved the total."""
    where, params = clause("bill", filters, exclude=("client",))
    sql = f"SELECT cl.client_code, cl.client_name, {REVENUE} FROM {SCOPES['bill']['from']}{where} GROUP BY 1, 2"
    return {str(r[0]): (str(r[1] or r[0]), num(r[2])) for r in rows(cur, sql, params) if r[0]}


def owed_by(cur, filters: dict[str, str], dimension: str, limit: int | None = None) -> list[dict[str, Any]]:
    """Outstanding by a dimension, with the age of the oldest unpaid bill."""
    code, label = DIMENSIONS[dimension]
    where, params = clause("bill", without_period(filters), exclude=(dimension,))
    sql = (
        f"SELECT {code}, {label}, {OPEN} AS owed,"
        f" COALESCE(SUM({BILL_OPEN}) FILTER (WHERE {BILL_AGE} > 90), 0) AS over90,"
        f" COUNT(*) FILTER (WHERE {BILL_OPEN} >= 1) AS open_bills,"
        f" COALESCE(MAX({BILL_AGE}) FILTER (WHERE {BILL_OPEN} >= 1), 0) AS oldest"
        f" FROM {SCOPES['bill']['from']}{where} GROUP BY 1, 2 HAVING {OPEN} >= 1 ORDER BY owed DESC"
    )
    out = [
        {
            "code": str(r[0]),
            "label": r[1] or r[0],
            "owed": round(num(r[2]), 2),
            "over90": round(num(r[3]), 2),
            "open_bills": int(r[4]),
            "oldest": int(r[5]),
        }
        for r in rows(cur, sql, params)
        if r[0] is not None
    ]
    return out[:limit] if limit else out


# ------------------------------------------------------------------------------------------------------------------
# KPI cards
# ------------------------------------------------------------------------------------------------------------------


def full_change(
    current: float | None,
    base: float | None,
    *,
    label: str,
    value: str,
    range_text: str = "",
    higher_is_better: bool = True,
    points: bool = False,
) -> dict[str, Any] | None:
    """How a figure stands against the whole of the year before: the change as text and as a number, which way is good,
    and the figure it is set against. None when there is nothing to set it against."""
    if current is None or base is None:
        return None
    if points:
        diff = current - base
        if abs(diff) < 0.05:
            text, kind = "flat", "neutral"
        else:
            text, kind = f"{diff:+.1f} pts", "positive" if (diff > 0) == higher_is_better else "negative"
        pct_change = None
    else:
        if not base:
            return None
        text, kind = delta(current, base)
        if not higher_is_better and kind != "neutral":
            kind = "negative" if kind == "positive" else "positive"
        pct_change = round((current - base) / abs(base) * 100, 1)
    return {"delta": text, "delta_type": kind, "delta_pct": pct_change, "compare": label, "value": value, "range": range_text}


def make_kpi(
    key: str,
    label: str,
    value: str,
    *,
    current: float | None = None,
    previous: float | None = None,
    yoy: float | None = None,
    compare: str = "",
    yoy_label: str = "",
    higher_is_better: bool = True,
    spark: dict[str, Any] | None = None,
    detail: dict[str, Any] | None = None,
    scope: str = "period",
    change: str = "",
    change_type: str = "neutral",
    hint: str = "",
    tone: str = "blue",
) -> dict[str, Any]:
    """The shared KPI shape plus what the card needs: numeric change, sparkline, and plain-language help."""
    out = kpi(key, label, value, change=change, change_type=change_type, hint=hint, tone=tone)
    change_pct = None
    if current is not None and previous:
        change_pct = round((current - previous) / abs(previous) * 100, 1)
        out["delta"], out["delta_type"] = delta(current, previous)
        if not higher_is_better and out["delta_type"] != "neutral":
            out["delta_type"] = "negative" if out["delta_type"] == "positive" else "positive"
    yoy_pct = None
    if current is not None and yoy:
        yoy_pct = round((current - yoy) / abs(yoy) * 100, 1)
    out.update(
        {
            "delta_pct": change_pct,
            "compare": compare if (change_pct is not None or change) else "",
            "yoy_pct": yoy_pct,
            "yoy_label": yoy_label if yoy_pct is not None else "",
            "higher_is_better": higher_is_better,
            "spark": spark["values"] if spark else [],
            "spark_labels": spark["labels"] if spark else [],
            "spark_kind": spark["kind"] if spark else "money",
            "scope": scope,
            "about": {
                **KPI_HELP.get(key, {"means": hint, "calc": ""}),
                "scope": SCOPE_SNAPSHOT if scope == "snapshot" else SCOPE_PERIOD,
            },
            "detail": detail,
        }
    )
    return out


class Dash:
    """One request: cleaned filters, comparison windows, and the aggregates every view shares."""

    def __init__(self, cur, raw_filters: dict[str, Any]):
        self.cur = cur
        self.bounds = data_span(cur)
        self.lo, self.hi = parse_day(self.bounds["min"]), parse_day(self.bounds["max"])
        # "This financial year" and "every year" are asked for by name and become a year (or nothing) here.
        self.filters, self.invalid = validate_filters(clean_filters(resolve_fy(dict(raw_filters), self.hi)))
        self.windows = comparison_windows(self.filters, self.lo, self.hi)
        self.window = selected_window(self.filters, self.lo, self.hi)

    # -- aggregates -------------------------------------------------------------------------------------------------
    @cached_property
    def context_filters(self) -> dict[str, str]:
        """The selection with the clicked month removed, for charts that show every month."""
        return {k: v for k, v in self.filters.items() if k != "month"}

    @cached_property
    def totals(self) -> dict[str, float]:
        return period_totals(self.cur, self.filters)

    @cached_property
    def previous(self) -> tuple[dict[str, float], str] | None:
        win = self.windows["previous"]
        if not win:
            return None
        found = period_totals(self.cur, win["filters"])
        return (found, win["label"]) if (found["bills"] or found["payroll"]) else None

    @cached_property
    def yoy(self) -> tuple[dict[str, float], str] | None:
        win = self.windows["yoy"]
        if not win:
            return None
        found = period_totals(self.cur, win["filters"])
        return (found, win["label"]) if (found["bills"] or found["payroll"]) else None

    @cached_property
    def full(self) -> tuple[dict[str, float], str] | None:
        """The whole of the year before, for a financial year still in progress."""
        win = self.windows["full"]
        if not win:
            return None
        found = period_totals(self.cur, win["filters"])
        return (found, win["label"]) if (found["bills"] or found["payroll"]) else None

    @cached_property
    def snapshot(self) -> dict[str, Any]:
        return snapshot_totals(self.cur, self.filters)

    @cached_property
    def monthly(self) -> list[dict[str, Any]]:
        return trend(self.cur, self.context_filters)

    @cached_property
    def cash_monthly(self) -> list[dict[str, Any]]:
        return cash_trend(self.cur, self.context_filters)

    @cached_property
    def cases_pnl(self) -> list[dict[str, Any]]:
        return pnl_by(self.cur, self.filters, "case")

    @cached_property
    def domains_pnl(self) -> list[dict[str, Any]]:
        return pnl_by(self.cur, self.filters, "business_domain")

    @cached_property
    def client_revenue(self) -> list[dict[str, Any]]:
        return pnl_by(self.cur, self.filters, "client")

    # -- text -------------------------------------------------------------------------------------------------------
    @cached_property
    def current_range(self) -> str:
        if self.window:
            return _range_text(self.window[0], min(self.window[1], self.hi) if self.hi else self.window[1])
        if self.lo and self.hi:
            return "All time, " + _range_text(self.lo, self.hi)
        return ""

    @cached_property
    def no_compare(self) -> str:
        if self.previous is not None:
            return ""
        if not self.window:
            return (
                "All time is selected, so there is no earlier period to compare with. "
                "Choose a month, financial year or date range to see a change."
            )
        return "The data does not reach back far enough to compare this selection with an earlier one."

    # -- KPI factory ------------------------------------------------------------------------------------------------
    def spark(self, key: str, kind: str = "money", rows_: list[dict[str, Any]] | None = None) -> dict[str, Any] | None:
        source = (rows_ if rows_ is not None else self.monthly)[-12:]
        values = [round(float(r.get(key, 0)), 2) for r in source]
        if len(values) < 3:
            return None
        return {"values": values, "labels": [r["label"] for r in source], "kind": kind}

    def period_kpi(
        self,
        key: str,
        label: str,
        field: str,
        *,
        fmt=inr,
        value: float | None = None,
        spark: dict[str, Any] | None = None,
        points: bool = False,
        higher_is_better: bool = True,
        at: Callable[[dict[str, str]], float] | None = None,
        **extra: Any,
    ) -> dict[str, Any]:
        """A figure that follows the period and carries its change against the earlier period and last year.

        ``points`` is for percentages: the change is a difference in percentage points, not a percentage of a percent.
        ``at`` is for a figure that is not one of the totals: it is worked out for a selection (given as filters), and is
        asked for each comparison window that has data, so such a figure is compared the same way the totals are.
        """
        current = self.totals[field] if value is None else value
        prev_totals, prev_label = self.previous or (None, "")
        yoy_totals, yoy_label = self.yoy or (None, "")
        full_totals, full_label = self.full or (None, "")

        def other(which: str, totals: dict[str, float] | None) -> float | None:
            if totals is None:
                return None
            return totals.get(field) if at is None else at(self.windows[which]["filters"])

        prev, old, whole = other("previous", prev_totals), other("yoy", yoy_totals), other("full", full_totals)
        shown = fmt(current)
        detail: dict[str, Any] = {"current_range": self.current_range}
        prev_range = _filters_range(self.windows["previous"]["filters"]) if prev_totals and self.windows["previous"] else ""
        yoy_range = _filters_range(self.windows["yoy"]["filters"]) if yoy_totals and self.windows["yoy"] else ""
        if prev_totals is not None and prev is not None:
            detail.update(compare=prev_label, current_value=shown, previous_value=fmt(prev), previous_range=prev_range)
        if yoy_totals is not None and old is not None:
            detail.update(yoy_label=yoy_label, current_value=shown, yoy_value=fmt(old), yoy_range=yoy_range)
        full_range = _filters_range(self.windows["full"]["filters"]) if full_totals and self.windows["full"] else ""
        if full_totals is not None and whole is not None:
            detail.update(full_label=full_label, full_value=fmt(whole), full_range=full_range)
        if prev_totals is None and yoy_totals is None and full_totals is None:
            detail["note"] = self.no_compare
        against_whole = full_change(
            current, whole, label=full_label, value=fmt(whole) if whole is not None else "", range_text=full_range,
            higher_is_better=higher_is_better, points=points,
        )
        if points:
            change, change_type = "", "neutral"
            if prev_totals is not None and prev is not None:
                diff = current - prev
                if abs(diff) >= 0.05:
                    good = (diff > 0) == higher_is_better
                    change, change_type = f"{diff:+.1f} pts", "positive" if good else "negative"
                else:
                    change = "flat"
            card = make_kpi(
                key, label, shown, compare=prev_label if change else "", change=change, change_type=change_type,
                higher_is_better=higher_is_better, spark=spark, detail=detail,
                yoy=None, **extra,
            )
        else:
            card = make_kpi(
                key, label, shown, current=current, previous=prev if prev else None, yoy=old if old else None,
                compare=prev_label, yoy_label=yoy_label, higher_is_better=higher_is_better, spark=spark, detail=detail, **extra,
            )
        card["full"] = against_whole
        return card

    def snapshot_kpi(self, key: str, label: str, value: str, **extra: Any) -> dict[str, Any]:
        card = make_kpi(key, label, value, scope="snapshot", **extra)
        card["full"] = None
        return card

    def kpis(self) -> list[dict[str, Any]]:
        """Every figure any tab may show, in no particular order. The views pick and order theirs."""
        t, s = self.totals, self.snapshot
        spark = self.spark
        cash = self.cash_monthly
        k: list[dict[str, Any]] = [
            self.period_kpi("revenue", "Revenue", "revenue", spark=spark("revenue"), tone="teal",
                            hint="Taxable value billed, before GST, after credit notes"),
            self.period_kpi("billed", "Billed", "billed", spark=spark("billed"), tone="blue",
                            hint="Invoice value including GST, after credit notes"),
            self.period_kpi("gst", "GST on bills", "gst", spark=spark("gst"), tone="violet",
                            hint=f"After credit notes; {inr(t['gst_unpaid'])} not yet marked paid"),
            self.period_kpi("credit_notes", "Credit notes", "credited", higher_is_better=False, tone="rose",
                            hint=f"On {qty(t['credit_notes'])} bills in the period"),
            self.period_kpi("itc", "Input tax credit", "itc", tone="emerald",
                            hint=(f"{inr(t['itc_missing'])} of GST on costs has no supplier GSTIN or invoice" if t["itc_missing"] else "GST on costs with supplier details")),
            self.period_kpi("net_gst", "Net GST to pay", "net_gst", higher_is_better=False, tone="violet",
                            hint="GST on bills less input tax credit"),
            self.period_kpi("bills", "Bills raised", "bills", fmt=qty, spark=spark("bills", "number"), tone="slate",
                            hint=f"{qty(t['edited'])} edited after issue"),
            self.period_kpi("avg_bill", "Average bill", "avg_bill", tone="blue", hint="Billed ÷ bills"),
            self.period_kpi("clients", "Clients billed", "clients", fmt=qty, tone="amber", hint="Distinct clients"),
            self.period_kpi("cases_billed", "Cases billed", "cases_billed", fmt=qty, tone="teal", hint="Distinct sites"),
            self.period_kpi("collected", "Cash collected", "collected", spark=spark("collected", rows_=cash), tone="emerald",
                            hint=f"{qty(t['receipts'])} payments received, in the bank"),
            self.period_kpi("tds_held", "TDS held back", "tds_held", tone="amber",
                            hint="Deducted by clients, not in the bank"),
            self.period_kpi("collection_rate", "Collection rate", "collection_rate", fmt=lambda v: f"{v:.0f}%", points=True,
                            tone="emerald", hint="Cash and TDS settled ÷ billed in the period"),
            self.period_kpi("payroll", "Payroll", "payroll", spark=spark("payroll"), higher_is_better=False, tone="amber",
                            hint=f"{inr(t['salary_pending'])} not yet paid"),
            self.period_kpi("expenses", "Operating expenses", "expenses", spark=spark("expenses"), higher_is_better=False,
                            tone="rose", hint="Before GST"),
            self.period_kpi("cost", "Total cost", "cost", spark=spark("cost"), higher_is_better=False, tone="rose",
                            hint="Payroll plus expenses"),
            self.period_kpi("margin", "Operating margin", "margin", spark=spark("margin"), tone="violet",
                            hint="Revenue less payroll and running costs"),
            self.period_kpi("margin_pct", "Operating margin %", "margin_pct", fmt=lambda v: f"{v:.1f}%", points=True,
                            spark=spark("margin_pct", "number"), tone="violet", hint="Of revenue"),
            self.period_kpi("payroll_pct", "Payroll share", "payroll_pct", fmt=lambda v: f"{v:.1f}%", points=True,
                            higher_is_better=False, tone="amber", hint="Payroll ÷ revenue"),
            self.period_kpi("expense_pct", "Expense share", "expense_pct", fmt=lambda v: f"{v:.1f}%", points=True,
                            higher_is_better=False, tone="rose", hint="Expenses ÷ revenue"),
            self.period_kpi("heads", "Staff on payroll", "heads", fmt=qty, spark=spark("heads", "number"), tone="blue",
                            hint="Average per month"),
            self.period_kpi("rev_per_head", "Revenue per employee", "rev_per_head", tone="emerald", hint="Per month on payroll"),
            self.period_kpi("days_worked", "Days worked", "days_worked", fmt=lambda v: f"{v:.1f}", tone="slate",
                            hint="Average per employee-month"),
            self.period_kpi("salary_pending", "Salary pending", "salary_pending", higher_is_better=False, tone="amber",
                            hint="Payroll lines not marked paid"),
            self.period_kpi("km", "Kilometres", "km", fmt=qty, tone="blue", hint="Driven by the fleet"),
            self.period_kpi("fleet_cost", "Fleet cost", "fleet_cost", higher_is_better=False, tone="teal",
                            hint="Km × per-km price"),
            self.period_kpi("cost_per_km", "Cost per km", "cost_per_km", fmt=lambda v: f"₹{v:.1f}", higher_is_better=False,
                            tone="teal", hint="Fleet cost ÷ km"),
            self.period_kpi("opps", "Opportunities", "opps", fmt=qty, tone="violet", hint="Opened in the period"),
            self.period_kpi("won", "Won", "won", fmt=qty, tone="emerald", hint="Closed Won"),
            self.period_kpi("win_rate", "Win rate", "win_rate", fmt=lambda v: f"{v:.0f}%", points=True, tone="emerald",
                            hint=f"{qty(t['won'])} of {qty(t['decided'])} decided"),
            self.period_kpi("open_pipeline", "Open opportunities", "open_opps", fmt=qty, tone="blue", hint="Still being worked"),
            self.period_kpi("pipeline_staff", "Staff to be hired", "pipeline_staff", fmt=qty, tone="slate",
                            hint="Workers the open tenders need"),
            self.period_kpi("days_to_collect", "Days to collect", "days_to_collect", fmt=lambda v: f"{v:.0f} days",
                            higher_is_better=False, tone="amber", hint="Bill date to last payment, paid bills"),
            self.period_kpi("cancelled_bills", "Cancelled bills", "cancelled", fmt=qty, higher_is_better=False, tone="rose",
                            hint=f"Worth {inr(t['cancelled_value'])}"),
            self.period_kpi("edited_bills", "Edited bills", "edited", fmt=qty, higher_is_better=False, tone="amber",
                            hint="On version 2 or later"),
            self.period_kpi("gst_unpaid", "GST not marked paid", "gst_unpaid", higher_is_better=False, tone="violet",
                            hint="On bills in the period"),
            self.period_kpi("epf_unpaid", "EPFO not marked paid", "epf_unpaid", higher_is_better=False, tone="amber",
                            hint="Charged on bills in the period, not yet paid over"),
            self.period_kpi("esic_unpaid", "ESIC not marked paid", "esic_unpaid", higher_is_better=False, tone="amber",
                            hint="Charged on bills in the period, not yet paid over"),
            self.snapshot_kpi("outstanding", "Outstanding", inr(s["outstanding"]), tone="rose",
                              hint=f"{qty(s['open_bills'])} unpaid bills", higher_is_better=False),
            self.snapshot_kpi("overdue_90", "Overdue 90+ days", inr(s["over90"]), tone="rose",
                              hint=f"{s['overdue_pct']:.0f}% of what is owed", higher_is_better=False),
            self.snapshot_kpi("overdue_pct", "Share overdue", f"{s['overdue_pct']:.0f}%", tone="rose",
                              hint="Over 90 days ÷ outstanding", higher_is_better=False),
            self.snapshot_kpi("dso", "Days sales outstanding", f"{s['dso']:.0f} days", tone="amber",
                              hint="Outstanding ÷ last 90 days' billing", higher_is_better=False),
            self.snapshot_kpi("open_bills", "Unpaid bills", qty(s["open_bills"]), tone="slate", hint="With a balance"),
            self.snapshot_kpi("active_cases", "Active cases", qty(s["active_cases"]), tone="teal", hint="Running now"),
            self.snapshot_kpi("run_rate", "Contracted monthly billing", inr(s["run_rate"]), tone="blue",
                              hint="Expected, active cases"),
            self.snapshot_kpi("headcount", "Employees", qty(s["headcount"]), tone="blue", hint="Active now"),
            self.snapshot_kpi("unbilled_cases", "Cases not yet billed", qty(s["unbilled"]["count"]), tone="amber",
                              hint=f"For {s['unbilled']['month']}" if s["unbilled"]["month"] else "", higher_is_better=False),
        ]
        return k

    # -- filter options ---------------------------------------------------------------------------------------------
    def filter_options(self) -> dict[str, list[dict[str, str]]]:
        cur = self.cur

        def options(sql: str) -> list[dict[str, str]]:
            return [{"id": str(r[0]), "label": str(r[1] or r[0])} for r in rows(cur, sql) if r[0] is not None]

        live = "is_current AND NOT is_expired"
        fys = [
            {"id": str(int(r[0])), "label": fy_label(int(r[0]))}
            for r in rows(
                cur,
                "SELECT DISTINCT (EXTRACT(YEAR FROM service_month)::int - CASE WHEN EXTRACT(MONTH FROM service_month) < 4 THEN 1 ELSE 0 END) y"
                f" FROM orion_dw.fact_bill WHERE {live} ORDER BY y DESC",
            )
        ]
        return {
            "fys": fys,
            "clients": options(f"SELECT client_code, client_name FROM orion_dw.dim_client WHERE {live} ORDER BY client_name"),
            "domains": options(
                f"SELECT business_domain_code, business_domain_name FROM orion_dw.dim_business_domain WHERE {live} ORDER BY 2"
            ),
            "capabilities": options(f"SELECT capability_code, capability_name FROM orion_dw.dim_capability WHERE {live} ORDER BY 2"),
            "cases": options(f"SELECT case_code, case_name FROM orion_dw.dim_case WHERE {live} ORDER BY case_name"),
            "states": options(
                f"SELECT DISTINCT client_location_state, client_location_state FROM orion_dw.dim_client WHERE {live} ORDER BY 1"
            ),
            "client_types": options(
                f"SELECT DISTINCT client_type, client_type FROM orion_dw.dim_client WHERE {live} AND client_type IS NOT NULL ORDER BY 1"
            ),
            "priorities": options(
                f"SELECT DISTINCT firm_priority, firm_priority FROM orion_dw.dim_client WHERE {live} AND firm_priority IS NOT NULL ORDER BY 1"
            ),
        }


def next_month(day: date) -> date:
    return (day.replace(day=1) + timedelta(days=32)).replace(day=1)
