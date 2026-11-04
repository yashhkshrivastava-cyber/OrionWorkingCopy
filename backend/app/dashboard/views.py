"""One builder per dashboard tab, over the Orion warehouse.

A builder takes the request's ``Dash`` and returns the blocks the tab plots: ``categories``, ``series``, ``tables``,
and any figures only that tab has (``kpis``). The shared figures and the insights are added around it in
``dashboard.build_view``. Blocks are read by id on the page, for example ``series('trend')``.
"""

from __future__ import annotations

from typing import Any

from app.dashboard.blocks import (
    case_meta,
    count_col,
    financial_years,
    money_col,
    pct_col,
    ranked,
    stacked_months,
    table,
    text_col,
    bill_col,
)
from app.dashboard.engine import (
    BILLED,
    OPEN,
    REVENUE,
    Dash,
    owed_by,
    pct,
    without_period,
)
from app.dashboard.filters import (
    BILL_AGE,
    BILL_OPEN,
    PAY_ORDER,
    SCOPES,
    clause,
    day_label,
    num,
    rows,
)
from app.dashboard.measures import category
from app.dashboard.views_cash import cash
from app.dashboard.views_ops import controls, fleet, people, pipeline, profitability

# Which client takes how long to pay, over fully paid bills.
DAYS_TO_PAY = f"COALESCE(AVG(p.last_received - b.bill_date) FILTER (WHERE {BILL_OPEN} < 1 AND p.last_received IS NOT NULL), 0)"


# --------------------------------------------------------------------------- overview


def overview(d: Dash) -> dict[str, Any]:
    t = d.totals
    cases = d.cases_pnl
    meta = case_meta(d.cur)
    owed_domain = {r["code"]: r for r in owed_by(d.cur, d.filters, "business_domain")}

    domain_rows = []
    for r in d.domains_pnl:
        owed = owed_domain.get(r["code"], {})
        domain_rows.append({**r, "outstanding": owed.get("owed", 0.0)})

    attention = []
    for r in sorted((c for c in cases if c["revenue"] > 0), key=lambda c: c["margin_pct"])[:10]:
        info = meta.get(r["code"], {})
        attention.append({**r, "client": info.get("client", "—"), "status": info.get("status", "—")})

    split_base = t["margin_revenue"]
    cost_split = [
        {"code": "payroll", "label": "Payroll", "value": round(t["payroll_pct"] * split_base / 100, 2)},
        {"code": "expenses", "label": "Running costs", "value": round(t["expense_pct"] * split_base / 100, 2)},
        {"code": "margin", "label": "Margin", "value": round(max(t["margin"], 0.0), 2)},
    ]
    fy_rows = financial_years(d.cur, d.filters)

    return {
        "series": {"trend": d.monthly, "cash": d.cash_monthly},
        "categories": {
            "cost_split": [c for c in cost_split if c["value"] > 0],
            "top_clients": ranked(d.client_revenue, "revenue", 10),
            "by_domain": ranked(d.domains_pnl, "revenue"),
            "ageing": d.snapshot["buckets"],
        },
        "tables": {
            "domains": table(
                [
                    text_col("label", "Business domain"),
                    money_col("revenue", "Revenue"),
                    pct_col("share", "Share"),
                    money_col("margin", "Margin"),
                    pct_col("margin_pct", "Margin %"),
                    money_col("collected", "Collected"),
                    money_col("outstanding", "Owed"),
                ],
                domain_rows,
                filter_key="business_domain",
                totals={
                    "revenue": t["revenue"], "share": 100.0 if t["revenue"] else 0.0, "margin": t["margin"],
                    "margin_pct": t["margin_pct"], "collected": t["collected"],
                    "outstanding": d.snapshot["outstanding"],
                },
            ),
            "fy": table(
                [
                    text_col("fy", "Financial year"),
                    money_col("revenue", "Revenue"),
                    pct_col("growth", "Growth"),
                    money_col("cost", "Cost"),
                    money_col("margin", "Margin"),
                    pct_col("margin_pct", "Margin %"),
                    money_col("collected", "Collected"),
                    count_col("heads", "Avg staff"),
                    count_col("cases", "Cases"),
                    count_col("clients", "Clients"),
                ],
                fy_rows,
                filter_key="fy",
            ),
            "attention": table(
                [
                    text_col("label", "Case"),
                    text_col("client", "Client"),
                    money_col("revenue", "Revenue"),
                    money_col("cost", "Cost"),
                    money_col("margin", "Margin"),
                    pct_col("margin_pct", "Margin %"),
                ],
                attention,
                filter_key="case",
            ),
        },
    }


# --------------------------------------------------------------------------- revenue


def _vintage(d: Dash) -> list[dict[str, Any]]:
    """Revenue split by how long the client has been billed: its first bill in the warehouse to the bill's month."""
    where, params = clause("bill", d.filters, exclude=("client",))
    band = (
        "CASE WHEN b.service_month >= (fb.first_month + INTERVAL '12 months') "
        "THEN CASE WHEN b.service_month >= (fb.first_month + INTERVAL '24 months') THEN '2+ years' ELSE '1-2 years' END "
        "ELSE 'First year' END"
    )
    sql = (
        f"SELECT {band}, {REVENUE} FROM {SCOPES['bill']['from']}"
        " JOIN (SELECT client_code, MIN(service_month) AS first_month FROM orion_dw.fact_bill"
        " WHERE is_current AND NOT is_expired AND status = 'Issued' GROUP BY client_code) fb ON fb.client_code = b.client_code"
        f"{where} GROUP BY 1"
    )
    order = ["First year", "1-2 years", "2+ years"]
    found = {r[0]: num(r[1]) for r in rows(d.cur, sql, params)}
    return [{"code": k, "label": k, "value": round(found.get(k, 0.0), 2)} for k in order if found.get(k)]


def _new_client_share(d: Dash) -> float | None:
    """Revenue share of clients whose first bill is within the last 12 months of the data."""
    if not d.hi:
        return None
    where, params = clause("bill", d.filters)
    sql = (
        f"SELECT {REVENUE}, COALESCE(SUM(b.taxable_total - COALESCE(b.credited_taxable, 0)) FILTER (WHERE fb.first_month > (%s::date - INTERVAL '12 months')), 0)"
        f" FROM {SCOPES['bill']['from']}"
        " JOIN (SELECT client_code, MIN(service_month) AS first_month FROM orion_dw.fact_bill"
        " WHERE is_current AND NOT is_expired AND status = 'Issued' GROUP BY client_code) fb ON fb.client_code = b.client_code"
        f"{where}"
    )
    total, fresh = rows(d.cur, sql, [d.hi, *params])[0]
    return pct(num(fresh), num(total)) if num(total) else None


def _bill_sizes(d: Dash) -> list[dict[str, Any]]:
    bands = [
        ("Under ₹1 L", "b.grand_total < 100000"),
        ("₹1 – 2 L", "b.grand_total >= 100000 AND b.grand_total < 200000"),
        ("₹2 – 5 L", "b.grand_total >= 200000 AND b.grand_total < 500000"),
        ("₹5 – 10 L", "b.grand_total >= 500000 AND b.grand_total < 1000000"),
        ("₹10 L and above", "b.grand_total >= 1000000"),
    ]
    sel = ", ".join(f"COUNT(*) FILTER (WHERE {cond})" for _l, cond in bands)
    val = ", ".join(f"COALESCE(SUM(b.grand_total) FILTER (WHERE {cond}), 0)" for _l, cond in bands)
    where, params = clause("bill", d.filters)
    row = rows(d.cur, f"SELECT {sel}, {val} FROM {SCOPES['bill']['from']}{where}", params)[0]
    n = len(bands)
    return [
        {"code": label, "label": label, "value": num(row[i]), "amount": num(row[n + i])}
        for i, (label, _c) in enumerate(bands)
    ]


def _contract_gap(d: Dash, meta: dict[str, dict[str, Any]], limit: int = 12) -> list[dict[str, Any]]:
    """Active cases: what the contract expects each month against what has been billed in the last three months."""
    latest = rows(d.cur, "SELECT MAX(service_month) FROM orion_dw.fact_bill WHERE is_current AND NOT is_expired")[0][0]
    if not latest:
        return []
    seg = without_period(d.filters)
    where, params = clause("bill", seg, exclude=("case",), extra=[
        "b.service_month > (%s::date - INTERVAL '3 months')", "b.service_month <= %s::date",
    ])
    sql = (
        f"SELECT c.case_code, SUM(b.grand_total - COALESCE(b.credited_amount, 0)), COUNT(DISTINCT b.service_month) FROM {SCOPES['bill']['from']}{where}"
        " GROUP BY 1"
    )
    out = []
    for code, billed, months in rows(d.cur, sql, [*params, latest, latest]):
        info = meta.get(str(code))
        if not info or info["status"] != "Active" or not info["expected"] or not months:
            continue
        monthly = num(billed) / int(months)
        gap = info["expected"] - monthly
        out.append(
            {
                "code": str(code), "label": info["case"], "client": info["client"], "expected": round(info["expected"], 2),
                "billed": round(monthly, 2), "gap": round(gap, 2), "gap_pct": round(pct(gap, info["expected"]), 1),
            }
        )
    return sorted(out, key=lambda r: abs(r["gap"]), reverse=True)[:limit]


def revenue(d: Dash) -> dict[str, Any]:
    cur, f = d.cur, d.filters
    cap_points, cap_keys = stacked_months(
        cur, scope="bill", filters=d.context_filters, code="cap.capability_code", label="cap.capability_name", value=REVENUE
    )
    meta = case_meta(d.cur)
    clients = d.client_revenue
    cumulative = 0.0
    total = d.totals["revenue"]
    concentration = []
    for r in sorted(clients, key=lambda c: c["revenue"], reverse=True)[:15]:
        cumulative += r["revenue"]
        concentration.append({**r, "cumulative": round(pct(cumulative, total), 1)})
    hhi = sum((pct(c["revenue"], total) / 100) ** 2 for c in clients) * 10000 if total else 0.0

    def by(dimension: str, code: str, label: str | None = None, limit: int | None = None):
        return category(
            cur, scope="bill", filters=f, dimension=dimension, code=code, label=label, value=REVENUE,
            having=f"{REVENUE} > 0", limit=limit,
        )

    flds = SCOPES["bill"]["fields"]
    recent_where, recent_params = clause("bill", f)
    recent = [
        {
            "code": r[0], "bill_code": r[0], "number": r[1], "date": day_label(r[2].isoformat()), "client": r[3] or "—", "case": r[4] or "—",
            "billed": num(r[5]), "status": r[6],
        }
        for r in rows(
            cur,
            "SELECT b.bill_code, b.bill_number, b.bill_date, cl.client_name, c.case_name, b.grand_total,"
            f" {flds['pay_status']} FROM {SCOPES['bill']['from']}{recent_where}"
            " ORDER BY b.bill_date DESC, b.bill_number DESC LIMIT 15",
            recent_params,
        )
    ]
    return {
        "series": {"trend": d.monthly, "by_capability": cap_points},
        "categories": {
            "capability_keys": cap_keys,
            "by_client_type": by("client_type", "cl.client_type"),
            "by_priority": by("priority", "cl.firm_priority"),
            "by_state": by("state", "cl.client_location_state"),
            "by_domain": by("business_domain", "bd.business_domain_code", "bd.business_domain_name"),
            "by_capability": by("capability", "cap.capability_code", "cap.capability_name"),
            "top_clients": ranked(clients, "revenue", 12),
            "vintage": _vintage(d),
            "bill_size": [{"code": s["code"], "label": s["label"], "value": s["value"]} for s in _bill_sizes(d)],
            "bill_size_value": [{"code": s["code"], "label": s["label"], "value": s["amount"]} for s in _bill_sizes(d)],
        },
        "tables": {
            "concentration": table(
                [
                    text_col("label", "Client"),
                    money_col("revenue", "Revenue"),
                    pct_col("share", "Share"),
                    pct_col("cumulative", "Cumulative"),
                    count_col("bills", "Bills"),
                ],
                concentration,
                filter_key="client",
                totals={"revenue": total, "bills": d.totals["bills"]},
            ),
            "contract_gap": table(
                [
                    text_col("label", "Case"),
                    text_col("client", "Client"),
                    money_col("expected", "Contract / month"),
                    money_col("billed", "Billed / month"),
                    money_col("gap", "Gap"),
                    pct_col("gap_pct", "Gap %"),
                ],
                _contract_gap(d, meta),
                filter_key="case",
            ),
            "recent_bills": table(
                [
                    bill_col("number", "Bill"),
                    text_col("date", "Date"),
                    text_col("client", "Client"),
                    text_col("case", "Case"),
                    money_col("billed", "Amount"),
                    text_col("status", "Payment"),
                ],
                recent,
            ),
        },
        "extra": {"hhi": round(hhi, 0), "new_client_share": _new_client_share(d), "underbilled": _underbilled(d, meta)},
    }


def _underbilled(d: Dash, meta: dict[str, dict[str, Any]]) -> dict[str, Any]:
    from app.dashboard.insights import UNDERBILL_FLAG_PCT

    short = [r for r in _contract_gap(d, meta, limit=200) if r["gap_pct"] >= UNDERBILL_FLAG_PCT]
    if not short:
        return {"count": 0}
    worst = max(short, key=lambda r: r["gap"])
    return {"count": len(short), "gap": sum(r["gap"] for r in short), "worst": {"code": worst["code"], "label": worst["label"], "gap": worst["gap"]}}


# --------------------------------------------------------------------------- collections


def collections(d: Dash) -> dict[str, Any]:
    cur, f = d.cur, d.filters
    seg = without_period(f)
    flds = SCOPES["bill"]["fields"]
    over_where, over_params = clause("bill", seg, extra=[f"{BILL_OPEN} >= 1"])
    overdue = [
        {
            "code": r[0], "bill_code": r[0], "number": r[1], "client": r[2] or "—", "case": r[3] or "—", "date": day_label(r[4].isoformat()),
            "age": int(r[5]), "billed": num(r[6]), "paid": num(r[7]), "open": num(r[8]), "bucket": r[9],
        }
        for r in rows(
            cur,
            "SELECT b.bill_code, b.bill_number, cl.client_name, c.case_name, b.bill_date, "
            f"{BILL_AGE}, b.grand_total, COALESCE(p.collected, 0), {BILL_OPEN}, {flds['bucket']}"
            f" FROM {SCOPES['bill']['from']}{over_where} ORDER BY b.bill_date, b.bill_number LIMIT 200",
            over_params,
        )
    ]
    owed = owed_by(cur, f, "client")
    days_where, days_params = clause("bill", f, exclude=("client",))
    pay_days = {
        str(r[0]): (num(r[1]), int(r[2]))
        for r in rows(
            cur,
            f"SELECT cl.client_code, {DAYS_TO_PAY}, COUNT(*) FILTER (WHERE {BILL_OPEN} < 1)"
            f" FROM {SCOPES['bill']['from']}{days_where} GROUP BY 1",
            days_params,
        )
    }
    client_rows = []
    for r in owed:
        days, paid_bills = pay_days.get(r["code"], (0.0, 0))
        client_rows.append({**r, "days_to_pay": round(days, 0) if paid_bills else None})

    paid_days = [(c, v[0], v[1]) for c, v in pay_days.items() if v[1] >= 3]
    slow = None
    if paid_days:
        worst = max(paid_days, key=lambda x: x[1])
        average = sum(v for _c, v, _n in paid_days) / len(paid_days)
        names = {r["code"]: r["label"] for r in d.client_revenue}
        slow = {"code": worst[0], "label": names.get(worst[0], worst[0]), "days": worst[1], "average": average}

    receipts_where, receipts_params = clause("collection", f)
    receipts = [
        {
            "code": r[0], "date": day_label(r[1].isoformat()), "client": r[2] or "—", "case": r[3] or "—", "amount": num(r[4]),
            "bill": r[5] or "—", "tds": num(r[6]),
        }
        for r in rows(
            cur,
            "SELECT t.transaction_code, COALESCE(t.received_date, t.transaction_date), cl.client_name, c.case_name,"
            f" t.amount_after_tax_gst - COALESCE(t.deducted_amount, 0), rb.bill_number, COALESCE(t.deducted_amount, 0) FROM {SCOPES['collection']['from']}"
            f" LEFT JOIN orion_dw.fact_bill rb ON rb.bill_sk = t.bill_sk{receipts_where}"
            " ORDER BY COALESCE(t.received_date, t.transaction_date) DESC, t.transaction_code DESC LIMIT 15",
            receipts_params,
        )
    ]
    pay_status = category(
        cur, scope="bill", filters=f, dimension="pay_status", code=flds["pay_status"], value=BILLED, order_by_list=PAY_ORDER
    )
    gst_where, gst_params = clause("bill", f)
    gst_rows = rows(
        cur,
        "SELECT 'Paid', COALESCE(SUM(COALESCE(b.gst_paid_amount, 0)), 0)"
        f" FROM {SCOPES['bill']['from']}{gst_where}"
        " UNION ALL"
        f" SELECT 'Not paid', COALESCE(SUM(b.cgst_amount + b.sgst_amount - COALESCE(b.credited_cgst, 0) - COALESCE(b.credited_sgst, 0) - COALESCE(b.gst_paid_amount, 0)), 0)"
        f" FROM {SCOPES['bill']['from']}{gst_where}",
        [*gst_params, *gst_params],
    )
    by_type_where, by_type_params = clause("bill", f, exclude=("client_type",))
    days_by_type = [
        {"code": str(r[0]), "label": str(r[0]), "value": round(num(r[1]), 1)}
        for r in rows(
            cur,
            f"SELECT cl.client_type, {DAYS_TO_PAY} FROM {SCOPES['bill']['from']}{by_type_where}"
            " GROUP BY 1 HAVING COUNT(*) FILTER (WHERE " + BILL_OPEN + " < 1) > 0 ORDER BY 2 DESC",
            by_type_params,
        )
        if r[0]
    ]
    return {
        "series": {"cash": d.cash_monthly},
        "categories": {
            "ageing": d.snapshot["buckets"],
            "pay_status": pay_status,
            "owed_clients": [
                {"code": r["code"], "label": r["label"], "value": r["owed"]} for r in owed[:10]
            ],
            "owed_type": category(
                cur, scope="bill", filters=seg, dimension="client_type", code="cl.client_type", value=OPEN, having=f"{OPEN} >= 1"
            ),
            "owed_domain": category(
                cur, scope="bill", filters=seg, dimension="business_domain", code="bd.business_domain_code",
                label="bd.business_domain_name", value=OPEN, having=f"{OPEN} >= 1",
            ),
            "days_by_type": days_by_type,
            "gst": [{"code": r[0], "label": r[0], "value": round(num(r[1]), 2)} for r in gst_rows],
        },
        "tables": {
            "owed_clients": table(
                [
                    text_col("label", "Client"),
                    count_col("open_bills", "Unpaid bills"),
                    money_col("owed", "Owed"),
                    money_col("over90", "Over 90 days"),
                    count_col("oldest", "Oldest (days)"),
                    count_col("days_to_pay", "Pays in (days)"),
                ],
                client_rows,
                filter_key="client",
                totals={
                    "open_bills": d.snapshot["open_bills"], "owed": d.snapshot["outstanding"], "over90": d.snapshot["over90"],
                },
            ),
            "overdue": table(
                [
                    bill_col("number", "Bill"),
                    text_col("client", "Client"),
                    text_col("case", "Case"),
                    text_col("date", "Bill date"),
                    count_col("age", "Age (days)"),
                    money_col("billed", "Billed"),
                    money_col("paid", "Received"),
                    money_col("open", "Owed"),
                ],
                overdue,
                truncated=len(overdue) >= 200,
                totals=None if len(overdue) >= 200 else {"billed": sum(r["billed"] for r in overdue), "paid": sum(r["paid"] for r in overdue),
                                                         "open": sum(r["open"] for r in overdue)},
            ),
            "receipts": table(
                [
                    text_col("date", "Received"),
                    text_col("client", "Client"),
                    text_col("case", "Case"),
                    bill_col("bill", "Bill"),
                    money_col("amount", "Cash received"),
                    money_col("tds", "TDS held back"),
                ],
                receipts,
            ),
        },
        "extra": {"slow_payer": slow},
    }


VIEWS = {
    "overview": overview,
    "revenue": revenue,
    "collections": collections,
    "profitability": profitability,
    "people": people,
    "pipeline": pipeline,
    "fleet": fleet,
    "controls": controls,
    "cash": cash,
}
