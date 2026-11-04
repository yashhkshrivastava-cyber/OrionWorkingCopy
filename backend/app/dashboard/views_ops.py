"""The profitability, people, pipeline, fleet and controls tabs. See ``views`` for the shape each builder returns."""

from __future__ import annotations

from typing import Any

from app.dashboard.blocks import (
    case_meta,
    count_col,
    money_col,
    pct_col,
    stacked_months,
    table,
    text_col,
    bill_col,
)
from app.dashboard.engine import (
    DIMENSIONS,
    EXPENSE,
    FLEET_COST,
    KM,
    PERIOD_KEYS,
    REVENUE,
    SALARY,
    Dash,
    pct,
    pnl_by,
    unbilled_cases,
    without_period,
)
from app.dashboard.pnl import profit_and_loss
from app.dashboard.filters import (
    EXPENSE_TYPE_CODE,
    EXPENSE_TYPE_NAME,
    BILL_AGE,
    SCOPES,
    STAGE_ORDER,
    clause,
    common,
    day_label,
    inr,
    month_label,
    num,
    qty,
    rows,
)
from app.dashboard.insights import STALE_DAYS
from app.dashboard.measures import category, merge_months, month_series, scalars

# ------------------------------------------------------------------------------------------------------------------
# profitability
# ------------------------------------------------------------------------------------------------------------------


def _margin_heat(d: Dash, dimension: str, limit: int = 10) -> dict[str, Any]:
    """Margin % of each dimension value in each financial year."""
    code, label = DIMENSIONS[dimension]
    shared = common(d.filters, "bill", "expense", "payroll")

    def grouped(scope: str, metric: str) -> dict[tuple[str, str], tuple[str, float]]:
        fy = SCOPES[scope]["fields"]["fy"]
        where, params = clause(scope, shared, exclude=(dimension, "fy", "month"))
        sql = f"SELECT {code}, {label}, {fy}, {metric} FROM {SCOPES[scope]['from']}{where} GROUP BY 1, 2, 3"
        return {(str(r[0]), str(r[2])): (str(r[1] or r[0]), num(r[3])) for r in rows(d.cur, sql, params) if r[0] and r[2]}

    bills = grouped("bill", REVENUE)
    spend = grouped("expense", EXPENSE)
    pay = grouped("payroll", SALARY)
    years = sorted({fy for _c, fy in bills})
    totals: dict[str, float] = {}
    for (c, _fy), (_n, v) in bills.items():
        totals[c] = totals.get(c, 0.0) + v
    lead = [c for c, _v in sorted(totals.items(), key=lambda kv: kv[1], reverse=True)[:limit]]
    out_rows = []
    for c in lead:
        name = next(n for (cc, _fy), (n, _v) in bills.items() if cc == c)
        row: dict[str, Any] = {"code": c, "label": name}
        for fy in years:
            rev = bills.get((c, fy), ("", 0.0))[1]
            cost = spend.get((c, fy), ("", 0.0))[1] + pay.get((c, fy), ("", 0.0))[1]
            row[f"fy{fy}"] = round(pct(rev - cost, rev), 1) if rev else None
        out_rows.append(row)
    columns = [text_col("label", dimension.replace("_", " ").title())] + [
        {"key": f"fy{fy}", "label": f"FY {fy}-{str(int(fy) + 1)[2:]}", "format": "percent", "align": "right"} for fy in years
    ]
    return table(columns, out_rows, filter_key=dimension)


def profitability(d: Dash) -> dict[str, Any]:
    cur, f = d.cur, d.filters
    meta = case_meta(cur)
    cases = []
    for r in d.cases_pnl:
        info = meta.get(r["code"], {})
        cases.append(
            {
                **r,
                "client": info.get("client", "—"),
                "domain": info.get("domain", "—"),
                "capability": info.get("capability", "—"),
                "status": info.get("status", "—"),
                "expected": info.get("expected", 0.0),
            }
        )
    cases.sort(key=lambda c: c["revenue"], reverse=True)
    loss = [c for c in cases if c["revenue"] > 0 and c["margin"] < 0]
    expense_points, expense_keys = stacked_months(
        cur, scope="expense", filters=d.context_filters, code=EXPENSE_TYPE_CODE, label=EXPENSE_TYPE_NAME, value=EXPENSE, top=5
    )

    def margin_cat(dimension: str, limit: int | None = None) -> list[dict[str, Any]]:
        items = [r for r in pnl_by(cur, f, dimension) if r["revenue"] > 0]
        items.sort(key=lambda r: r["margin_pct"], reverse=True)
        return [{"code": r["code"], "label": r["label"], "value": r["margin_pct"]} for r in (items[:limit] if limit else items)]

    cols = [
        text_col("label", "Name"),
        money_col("revenue", "Revenue"),
        money_col("payroll", "Payroll"),
        money_col("expenses", "Expenses"),
        money_col("margin", "Margin"),
        pct_col("margin_pct", "Margin %"),
        pct_col("share", "Share of revenue"),
    ]
    caps = pnl_by(cur, f, "capability")
    types = pnl_by(cur, f, "client_type")
    return {
        "series": {"trend": d.monthly, "expense_by_type": expense_points},
        "categories": {
            "expense_keys": expense_keys,
            "cost_mix": [
                {"code": "payroll", "label": "Payroll", "value": round(d.totals["payroll"], 2)},
                {"code": "expenses", "label": "Running costs", "value": round(d.totals["expenses"], 2)},
            ],
            "margin_domain": margin_cat("business_domain"),
            "margin_capability": margin_cat("capability"),
            "margin_type": margin_cat("client_type"),
            "margin_state": margin_cat("state", 8),
            "expense_mix": category(
                cur, scope="expense", filters=f, dimension="expense_type", code=EXPENSE_TYPE_CODE, label=EXPENSE_TYPE_NAME,
                value=EXPENSE, having=f"{EXPENSE} > 0",
            ),
            "recurring": category(
                cur, scope="expense", filters=f, dimension="is_regular", code="e.is_regular_expense", value=EXPENSE,
                having=f"{EXPENSE} > 0",
            ),
            "loss_cases": [{"code": c["code"], "label": c["label"], "value": -c["margin"]} for c in sorted(loss, key=lambda x: x["margin"])[:10]],
        },
        "tables": {
            "pnl": profit_and_loss(d, bool(getattr(d, "bank_access", False))),
            "cases": table(
                [
                    text_col("label", "Case"),
                    text_col("client", "Client"),
                    text_col("domain", "Domain"),
                    money_col("revenue", "Revenue"),
                    money_col("payroll", "Payroll"),
                    money_col("expenses", "Expenses"),
                    money_col("margin", "Margin"),
                    pct_col("margin_pct", "Margin %"),
                    pct_col("share", "Share"),
                    text_col("status", "Status"),
                ],
                cases,
                filter_key="case",
                totals={
                    "revenue": d.totals["revenue"], "payroll": d.totals["payroll"], "expenses": d.totals["expenses"],
                    "margin": d.totals["margin"], "margin_pct": d.totals["margin_pct"],
                },
            ),
            "capabilities": table(cols, caps, filter_key="capability"),
            "client_types": table(cols, types, filter_key="client_type"),
            "heat_domain": _margin_heat(d, "business_domain"),
            "heat_capability": _margin_heat(d, "capability"),
        },
        "extra": {"loss_cases": loss, "domains": d.domains_pnl},
    }


# ------------------------------------------------------------------------------------------------------------------
# people
# ------------------------------------------------------------------------------------------------------------------


def _roster_filters(d: Dash) -> dict[str, str]:
    return {k: v for k, v in d.filters.items() if k not in PERIOD_KEYS}


def _headcount_series(d: Dash) -> list[dict[str, Any]]:
    months = [p["code"] for p in d.monthly]
    if not months:
        return []
    roster = _roster_filters(d)
    where, params = clause("employee", roster)
    active_sql = (
        "SELECT to_char(g.m, 'YYYY-MM'), COUNT(*) FROM generate_series(%s::date, %s::date, INTERVAL '1 month') g(m)"
        f" CROSS JOIN {SCOPES['employee']['from']}{where}"
        " AND emp.emp_start_date <= (g.m + INTERVAL '1 month - 1 day')::date"
        " AND (emp.emp_end_date IS NULL OR emp.emp_end_date >= g.m) GROUP BY 1 ORDER BY 1"
    )
    active = {r[0]: int(r[1]) for r in rows(d.cur, active_sql, [f"{months[0]}-01", f"{months[-1]}-01", *params])}
    joined = {
        r[0]: int(r[1])
        for r in rows(
            d.cur,
            f"SELECT to_char(emp.emp_start_date, 'YYYY-MM'), COUNT(*) FROM {SCOPES['employee']['from']}{where} GROUP BY 1",
            params,
        )
        if r[0]
    }
    left = {
        r[0]: int(r[1])
        for r in rows(
            d.cur,
            f"SELECT to_char(emp.emp_end_date, 'YYYY-MM'), COUNT(*) FROM {SCOPES['employee']['from']}{where}"
            " AND emp.emp_end_date IS NOT NULL GROUP BY 1",
            params,
        )
        if r[0]
    }
    out = []
    for m in months:
        out.append({"code": m, "label": month_label(m), "headcount": active.get(m, 0), "joiners": joined.get(m, 0), "leavers": left.get(m, 0)})
    return out


def people(d: Dash) -> dict[str, Any]:
    cur, f = d.cur, d.filters
    roster = _roster_filters(d)
    headcount = _headcount_series(d)
    in_window = headcount
    if d.window:
        lo, hi = d.window[0].strftime("%Y-%m"), d.window[1].strftime("%Y-%m")
        in_window = [p for p in headcount if lo <= p["code"] <= hi]
    leavers = sum(p["leavers"] for p in in_window)
    joiners = sum(p["joiners"] for p in in_window)
    avg_heads = sum(p["headcount"] for p in in_window) / len(in_window) if in_window else 0.0
    attrition = leavers / avg_heads * 12 / len(in_window) * 100 if avg_heads and in_window else 0.0
    now = d.snapshot["headcount"]

    def attrition_at(window: dict[str, str]) -> float:
        """Annualised attrition for a comparison window, from the same monthly series."""
        start, end = window.get("from", "")[:7], window.get("to", "")[:7]
        months_in = [p for p in headcount if (not start or p["code"] >= start) and (not end or p["code"] <= end)]
        heads = sum(p["headcount"] for p in months_in) / len(months_in) if months_in else 0.0
        gone = sum(p["leavers"] for p in months_in)
        return gone / heads * 12 / len(months_in) * 100 if heads and months_in else 0.0

    pay_trend = [
        {**p, "per_head": round(p["payroll"] / p["heads"], 2) if p["heads"] else 0.0} for p in d.monthly
    ]

    where, params = clause("employee", roster, extra=["emp.employee_status = 'Active'"])
    tenure_sql = (
        "SELECT CASE WHEN CURRENT_DATE - emp.emp_start_date < 365 THEN 'Under 1 year'"
        " WHEN CURRENT_DATE - emp.emp_start_date < 730 THEN '1-2 years'"
        " WHEN CURRENT_DATE - emp.emp_start_date < 1095 THEN '2-3 years' ELSE '3+ years' END, COUNT(*)"
        f" FROM {SCOPES['employee']['from']}{where} GROUP BY 1"
    )
    tenure_found = {r[0]: int(r[1]) for r in rows(cur, tenure_sql, params)}
    tenure = [
        {"code": k, "label": k, "value": tenure_found[k]}
        for k in ("Under 1 year", "1-2 years", "2-3 years", "3+ years")
        if tenure_found.get(k)
    ]

    heads_by_designation = category(
        cur, scope="employee", filters=roster, dimension="designation", code="emp.employee_designation",
        value="COUNT(*)", extra=["emp.employee_status = 'Active'"],
    )
    pay_by_designation = category(
        cur, scope="payroll", filters=f, dimension="designation", code="emp.employee_designation", value=SALARY,
        having=f"{SALARY} > 0",
    )
    where_p, params_p = clause("payroll", f, exclude=("designation",))
    designation_pay = {
        str(r[0]): (num(r[1]), int(r[2]), num(r[3]))
        for r in rows(
            cur,
            f"SELECT emp.employee_designation, {SALARY}, COUNT(*), COALESCE(AVG(et.days_worked), 0)"
            f" FROM {SCOPES['payroll']['from']}{where_p} GROUP BY 1",
            params_p,
        )
        if r[0]
    }
    where_r, params_r = clause("employee", roster, exclude=("designation",))
    roster_rows = {
        str(r[0]): (int(r[1]), int(r[2]))
        for r in rows(
            d.cur,
            f"SELECT emp.employee_designation, COUNT(*) FILTER (WHERE emp.employee_status = 'Active'),"
            f" COUNT(*) FILTER (WHERE emp.employee_status <> 'Active') FROM {SCOPES['employee']['from']}{where_r} GROUP BY 1",
            params_r,
        )
        if r[0]
    }
    total_pay = d.totals["payroll"]
    designations = []
    for name in sorted(set(designation_pay) | set(roster_rows)):
        payroll, lines, days = designation_pay.get(name, (0.0, 0, 0.0))
        active, gone = roster_rows.get(name, (0, 0))
        designations.append(
            {
                "code": name, "label": name, "headcount": active, "left": gone, "payroll": round(payroll, 2),
                "share": round(pct(payroll, total_pay), 1), "avg_salary": round(payroll / lines, 0) if lines else 0.0,
                "days": round(days, 1),
            }
        )
    designations.sort(key=lambda r: r["payroll"], reverse=True)

    cases_pnl = {r["code"]: r for r in d.cases_pnl}
    where_c, params_c = clause("employee", roster, extra=["emp.employee_status = 'Active'", "c.case_code IS NOT NULL"])
    by_case = []
    for r in rows(
        cur,
        f"SELECT c.case_code, c.case_name, COUNT(*) FROM {SCOPES['employee']['from']}{where_c} GROUP BY 1, 2 ORDER BY 3 DESC LIMIT 15",
        params_c,
    ):
        pnl = cases_pnl.get(str(r[0]), {})
        by_case.append(
            {
                "code": str(r[0]), "label": r[1], "headcount": int(r[2]), "payroll": pnl.get("payroll", 0.0), "revenue": pnl.get("revenue", 0.0),
                "per_head": round(pnl.get("revenue", 0.0) / pnl["heads"], 0) if pnl.get("heads") else 0.0,
            }
        )

    where_m, params_m = clause("employee", roster, extra=["emp.employee_status = 'Active'", "emp.manager_code IS NOT NULL"])
    managers = [
        {"code": str(r[0]), "label": r[1] or r[0], "reports": int(r[2])}
        for r in rows(
            cur,
            f"SELECT emp.manager_code, mg.employee_name, COUNT(*) FROM {SCOPES['employee']['from']}"
            " LEFT JOIN orion_dw.dim_employee mg ON mg.employee_code = emp.manager_code AND mg.is_current AND NOT mg.is_expired"
            f"{where_m} GROUP BY 1, 2 ORDER BY 3 DESC LIMIT 12",
            params_m,
        )
    ]

    attrition_kpi = d.period_kpi(
        "attrition", "Annual attrition", "", fmt=lambda v: f"{v:.0f}%", value=attrition, points=True, higher_is_better=False,
        at=attrition_at, tone="rose", hint=f"{leavers} left, {joiners} joined",
    )
    return {
        "kpis": [attrition_kpi],
        "series": {"headcount": headcount, "payroll": pay_trend},
        "categories": {
            "headcount_designation": heads_by_designation,
            "payroll_designation": pay_by_designation,
            "employee_type": category(
                cur, scope="employee", filters=roster, dimension="employee_type", code="emp.employee_type", value="COUNT(*)",
                extra=["emp.employee_status = 'Active'"],
            ),
            "tenure": tenure,
        },
        "tables": {
            "designations": table(
                [
                    text_col("label", "Designation"),
                    count_col("headcount", "Active"),
                    count_col("left", "Left"),
                    money_col("payroll", "Payroll"),
                    pct_col("share", "Share"),
                    money_col("avg_salary", "Avg monthly pay"),
                    count_col("days", "Avg days"),
                ],
                designations,
                filter_key="designation",
                totals={"headcount": now, "payroll": total_pay},
            ),
            "cases": table(
                [
                    text_col("label", "Case"),
                    count_col("headcount", "Staff"),
                    money_col("revenue", "Revenue"),
                    money_col("payroll", "Payroll"),
                    money_col("per_head", "Revenue / employee-month"),
                ],
                by_case,
                filter_key="case",
            ),
            "managers": table([text_col("label", "Manager"), count_col("reports", "Direct reports")], managers),
        },
        "extra": {"people": {"attrition": attrition, "leavers": leavers, "joiners": joiners, "headcount": now}},
    }


# ------------------------------------------------------------------------------------------------------------------
# pipeline
# ------------------------------------------------------------------------------------------------------------------


EMD_ORDER = ["Deposited", "Refund requested", "Refunded", "Adjusted against security deposit", "Forfeited"]
# An EMD is still with the authority until it is refunded, adjusted against the security deposit or forfeited.
EMD_OPEN = "e.emd_status IN ('Deposited', 'Refund requested')"
EMD_LOST = "CASE WHEN e.emd_status = 'Forfeited' THEN e.emd_amount ELSE COALESCE(e.deduction_amount, 0) END"
EMD_SOON_DAYS = 30


def _emd_block(d: Dash) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """The earnest money tiles, the chart of EMD by status and the table of what is still to come back.

    The tiles and the table are as at today (the segment filters apply, the period does not): money held does not depend on the month
    it was deposited in. The chart follows the period, by deposit date."""
    cur, f = d.cur, d.filters
    now = without_period(f)
    held = scalars(
        cur, "emd", now,
        {
            "amount": "COALESCE(SUM(e.emd_amount), 0)", "n": "COUNT(*)",
            "late": "COALESCE(SUM(e.emd_amount) FILTER (WHERE e.refund_due_date < CURRENT_DATE), 0)",
            "late_n": "COUNT(*) FILTER (WHERE e.refund_due_date < CURRENT_DATE)",
        },
        extra=[EMD_OPEN],
    )
    lost = scalars(cur, "emd", now, {"amount": f"COALESCE(SUM({EMD_LOST}), 0)", "n": f"COUNT(*) FILTER (WHERE {EMD_LOST} > 0)"})
    kpis = [
        d.snapshot_kpi("emd_held", "EMD held by clients", inr(held["amount"]), tone="amber", higher_is_better=False,
                       hint=f"{qty(held['n'])} deposit{'' if held['n'] == 1 else 's'} to come back"),
        d.snapshot_kpi("emd_overdue", "EMD refund overdue", inr(held["late"]), tone="rose", higher_is_better=False,
                       hint=f"{qty(held['late_n'])} past the refund due date"),
        d.snapshot_kpi("emd_lost", "EMD forfeited or deducted", inr(lost["amount"]), tone="slate", higher_is_better=False,
                       hint=f"{qty(lost['n'])} deposit{'' if lost['n'] == 1 else 's'} not returned in full"),
    ]
    by_status = category(
        cur, scope="emd", filters=f, dimension="emd_status", code="e.emd_status", value="COALESCE(SUM(e.emd_amount), 0)", order_by_list=EMD_ORDER,
    )
    where, params = clause("emd", now, extra=[EMD_OPEN])
    coming_back = []
    for r in rows(
        cur,
        "SELECT e.emd_code, c.case_name, cl.client_name, e.emd_amount, e.payment_mode, e.deposit_date, e.refund_due_date, e.valid_until,"
        " e.emd_status, (e.refund_due_date - CURRENT_DATE), (e.valid_until - CURRENT_DATE)"
        f" FROM {SCOPES['emd']['from']}{where} ORDER BY e.refund_due_date NULLS LAST, e.deposit_date LIMIT 100",
        params,
    ):
        flag = ""
        if r[9] is not None and int(r[9]) < 0:
            flag = "Refund overdue"
        elif r[10] is not None and 0 <= int(r[10]) <= EMD_SOON_DAYS:
            flag = "Instrument ends soon"
        elif r[10] is not None and int(r[10]) < 0:
            flag = "Instrument expired"
        coming_back.append(
            {
                "code": r[0], "label": r[1] or "—", "client": r[2] or "—", "amount": num(r[3]), "mode": r[4] or "—",
                "deposited": day_label(r[5].isoformat()) if r[5] else "—", "due": day_label(r[6].isoformat()) if r[6] else "Not set",
                "valid_until": day_label(r[7].isoformat()) if r[7] else "—", "status": r[8], "flag": flag,
            }
        )
    block = table(
        [text_col("label", "Case"), text_col("client", "Client"), money_col("amount", "Amount"), text_col("mode", "Paid by"),
         text_col("deposited", "Deposited"), text_col("due", "Refund due"), text_col("valid_until", "Instrument valid till"),
         text_col("status", "Status"), text_col("flag", "")],
        coming_back,
    )
    return kpis, by_status, block


def pipeline(d: Dash) -> dict[str, Any]:
    cur, f = d.cur, d.filters
    fo = SCOPES["opportunity"]["fields"]
    trend = month_series(
        cur, scope="opportunity", filters=d.context_filters,
        metrics={
            "opps": "COUNT(*)",
            "won": "COUNT(*) FILTER (WHERE o.opportunity_status = 'Closed Won')",
            "lost": "COUNT(*) FILTER (WHERE o.opportunity_status IN ('Closed Lost', 'Disqualified'))",
        },
    )
    where_fy, params_fy = clause("opportunity", f, exclude=("fy", "month"))
    fy_rows = []
    for r in rows(
        cur,
        f"SELECT {fo['fy']}, COUNT(*), COUNT(*) FILTER (WHERE o.opportunity_status = 'Closed Won'),"
        " COUNT(*) FILTER (WHERE o.opportunity_status IN ('Closed Lost', 'Disqualified')),"
        " COALESCE(AVG(o.opportunity_end_date - o.opportunity_start_date) FILTER (WHERE o.opportunity_status IN"
        " ('Closed Won', 'Closed Lost', 'Disqualified')), 0)"
        f" FROM {SCOPES['opportunity']['from']}{where_fy} GROUP BY 1 ORDER BY 1",
        params_fy,
    ):
        if r[0] is None:
            continue
        decided = int(r[2]) + int(r[3])
        fy_rows.append(
            {
                "code": str(r[0]), "fy": f"FY {r[0]}-{str(int(r[0]) + 1)[2:]}", "opps": int(r[1]), "won": int(r[2]), "lost": int(r[3]),
                "win_rate": round(pct(int(r[2]), decided), 1), "cycle": round(num(r[4]), 0),
            }
        )

    where_open, params_open = clause("opportunity", f, extra=["o.opportunity_status IN ('Proposal', 'Qualified', 'Technical Bid', 'Financial Bid')"])
    open_rows = []
    for r in rows(
        cur,
        "SELECT o.opportunity_code, o.opportunity_name, o.opportunity_status, o.state, o.city, o.opportunity_start_date, o.workers,"
        " (CURRENT_DATE - o.opportunity_start_date),"
        " (CURRENT_DATE - COALESCE(o.last_sub_stage_change_date, o.opportunity_start_date))"
        f" FROM {SCOPES['opportunity']['from']}{where_open} ORDER BY o.opportunity_start_date LIMIT 100",
        params_open,
    ):
        stale = int(r[8] or 0) > STALE_DAYS
        open_rows.append(
            {
                "code": r[0], "label": r[1], "stage": r[2], "place": ", ".join(x for x in (r[4], r[3]) if x), "started": day_label(r[5].isoformat()) if r[5] else "—",
                "age": int(r[7] or 0), "workers": num(r[6]), "flag": "Stale" if stale else "",
            }
        )
    stale_count = sum(1 for r in open_rows if r["flag"])

    where_won, params_won = clause("opportunity", f, exclude=("stage",), extra=["o.opportunity_status = 'Closed Won'", "o.opportunity_case_code IS NOT NULL"])
    won_rows = [
        {
            "code": r[0], "label": r[1], "case": r[2] or "—", "awarded": day_label(r[3].isoformat()) if r[3] else "—",
            "first_bill": month_label(r[4].strftime("%Y-%m")) if r[4] else "Not billed yet", "months": int(r[5] or 0), "revenue": num(r[6]),
        }
        for r in rows(
            cur,
            "SELECT o.opportunity_code, o.opportunity_name, c.case_name, o.opportunity_end_date, fb.first_month, fb.months, fb.revenue"
            f" FROM {SCOPES['opportunity']['from']}"
            " LEFT JOIN (SELECT case_code, MIN(service_month) AS first_month, COUNT(DISTINCT service_month) AS months,"
            " SUM(taxable_total - COALESCE(credited_taxable, 0)) AS revenue FROM orion_dw.fact_bill WHERE is_current AND NOT is_expired AND status = 'Issued'"
            f" GROUP BY case_code) fb ON fb.case_code = o.opportunity_case_code{where_won}"
            " ORDER BY fb.revenue DESC NULLS LAST LIMIT 30",
            params_won,
        )
    ]
    loss = category(
        cur, scope="opportunity", filters=f, dimension="stage", code="o.reason", value="COUNT(*)",
        extra=["o.opportunity_status IN ('Closed Lost', 'Disqualified')", "o.reason IS NOT NULL"], limit=8,
    )
    t = d.totals
    cycle_sql = {
        "cycle": "COALESCE(AVG(o.opportunity_end_date - o.opportunity_start_date) FILTER (WHERE o.opportunity_status IN ('Closed Won', 'Closed Lost', 'Disqualified')), 0)"
    }
    stats = scalars(cur, "opportunity", f, cycle_sql)
    cycle_kpi = d.period_kpi(
        "cycle_days", "Days to decide", "", fmt=lambda v: f"{v:.0f} days", value=stats["cycle"], higher_is_better=False,
        at=lambda window: scalars(cur, "opportunity", window, cycle_sql)["cycle"], tone="slate", hint="Start to close, decided tenders",
    )
    stale_all = scalars(
        cur, "opportunity", without_period(f),
        {"n": "COUNT(*)"},
        extra=["o.opportunity_status IN ('Proposal', 'Qualified', 'Technical Bid', 'Financial Bid')",
               f"(CURRENT_DATE - COALESCE(o.last_sub_stage_change_date, o.opportunity_start_date)) > {STALE_DAYS}"],
    )["n"]
    emd_kpis, emd_by_status, emd_table = _emd_block(d)
    return {
        "kpis": [cycle_kpi, *emd_kpis],
        "series": {"trend": merge_months(trend)},
        "categories": {
            "emd_by_status": emd_by_status,
            "funnel": category(cur, scope="opportunity", filters=f, dimension="stage", code=fo["stage"], value="COUNT(*)", order_by_list=STAGE_ORDER),
            "by_state": category(cur, scope="opportunity", filters=f, dimension="state", code=fo["state"], value="COUNT(*)", limit=10),
            "by_type": category(cur, scope="opportunity", filters=f, dimension="opp_type", code=fo["opp_type"], value="COUNT(*)"),
            "loss_reasons": loss,
        },
        "tables": {
            "emd": emd_table,
            "fy": table(
                [text_col("fy", "Financial year"), count_col("opps", "Opened"), count_col("won", "Won"), count_col("lost", "Lost"),
                 pct_col("win_rate", "Win rate"), count_col("cycle", "Days to decide")],
                fy_rows, filter_key="fy",
            ),
            "open": table(
                [text_col("label", "Opportunity"), text_col("stage", "Stage"), text_col("place", "Where"), text_col("started", "Started"),
                 count_col("age", "Age (days)"), count_col("workers", "Workers"), text_col("flag", "")],
                open_rows,
            ),
            "won": table(
                [text_col("label", "Opportunity"), text_col("case", "Became case"), text_col("awarded", "Awarded"),
                 text_col("first_bill", "First billed"), count_col("months", "Months billed"), money_col("revenue", "Revenue to date")],
                won_rows,
            ),
        },
        "extra": {
            "pipeline": {
                "decided": t["decided"], "won": t["won"], "win_rate": t["win_rate"], "open": t["open_opps"], "stale": stale_all or stale_count,
                "top_loss": loss[0] if loss else None,
            }
        },
    }


# ------------------------------------------------------------------------------------------------------------------
# fleet
# ------------------------------------------------------------------------------------------------------------------


def fleet(d: Dash) -> dict[str, Any]:
    cur, f = d.cur, d.filters
    trend = month_series(
        cur, scope="fleet", filters=d.context_filters,
        metrics={"km": KM, "cost": FLEET_COST, "days": "COUNT(DISTINCT ct.driving_date)", "cars": "COUNT(DISTINCT ct.car_code)"},
    )
    points = merge_months(trend, derive=lambda p: {"per_km": round(p["cost"] / p["km"], 2) if p["km"] else 0.0})

    where, params = clause("fleet", f)
    cars = [
        {
            "code": r[0], "label": r[1], "model": r[2], "case": r[3] or "—", "driver": r[4] or "—", "km": num(r[5]), "days": int(r[6]),
            "km_day": round(num(r[5]) / int(r[6]), 0) if r[6] else 0.0, "cost": num(r[7]),
            "per_km": round(num(r[7]) / num(r[5]), 1) if num(r[5]) else 0.0,
        }
        for r in rows(
            cur,
            f"SELECT car.car_code, car.car_number, car.car_model, c.case_name, drv.employee_name, {KM}, COUNT(DISTINCT ct.driving_date), {FLEET_COST}"
            f" FROM {SCOPES['fleet']['from']}{where} GROUP BY 1, 2, 3, 4, 5 ORDER BY 6 DESC",
            params,
        )
    ]
    where_a, params_a = clause("fleet", f, exclude=("case",))
    allowance = []
    over = []
    sql = (
        f"SELECT c.case_code, c.case_name, {KM}, COUNT(DISTINCT to_char(ct.driving_date, 'YYYY-MM')),"
        f" MAX(cc.monthly_allowed_km), {FLEET_COST} FROM {SCOPES['fleet']['from']}{where_a} GROUP BY 1, 2"
    )
    for r in rows(cur, sql, params_a):
        if r[0] is None:
            continue
        months = int(r[3] or 0)
        avg = num(r[2]) / months if months else 0.0
        allowed = num(r[4])
        used = round(pct(avg, allowed), 1) if allowed else None
        row = {
            "code": str(r[0]), "label": r[1], "km": num(r[2]), "avg_km": round(avg, 0), "allowed": allowed, "utilisation": used,
            "cost": num(r[5]),
        }
        allowance.append(row)
        if used is not None and used > 100:
            over.append({"code": row["code"], "label": row["label"], "pct": used})
    allowance.sort(key=lambda r: (r["utilisation"] is None, -(r["utilisation"] or 0)))
    over.sort(key=lambda r: r["pct"], reverse=True)

    km_per_day = d.totals["km"] / d.totals["days"] if d.totals["days"] else 0.0
    by_model = category(cur, scope="fleet", filters=f, dimension="car_model", code="car.car_model", value=KM, having=f"{KM} > 0")
    cars_active = len({c["code"] for c in cars})
    def cars_at(window: dict[str, str]) -> float:
        return scalars(cur, "fleet", window, {"v": "COUNT(DISTINCT ct.car_code)"})["v"]

    def km_per_day_at(window: dict[str, str]) -> float:
        found = scalars(cur, "fleet", window, {"km": KM, "days": "COUNT(DISTINCT ct.driving_date)"})
        return found["km"] / found["days"] if found["days"] else 0.0

    extra_kpis = [
        d.period_kpi("cars_active", "Cars on the road", "", fmt=qty, value=cars_active, at=cars_at, tone="teal",
                     hint="With a log in the period"),
        d.period_kpi("km_per_day", "Km per driving day", "", fmt=lambda v: f"{v:,.0f}", value=km_per_day, at=km_per_day_at,
                     tone="blue", hint="Fleet total ÷ days with a log"),
    ]
    return {
        "kpis": extra_kpis,
        "series": {"trend": points},
        "categories": {
            "by_model": by_model,
            "by_driver": category(
                cur, scope="fleet", filters=f, dimension="driver", code="drv.employee_code", label="drv.employee_name", value=KM,
                having=f"{KM} > 0", limit=10,
            ),
            "cost_by_case": category(
                cur, scope="fleet", filters=f, dimension="case", code="c.case_code", label="c.case_name", value=FLEET_COST,
                having=f"{FLEET_COST} > 0", limit=10,
            ),
        },
        "tables": {
            "cars": table(
                [
                    text_col("label", "Car"), text_col("model", "Model"), text_col("case", "Case"), text_col("driver", "Driver"),
                    count_col("km", "Km"), count_col("days", "Days driven"), count_col("km_day", "Km / day"),
                    money_col("cost", "Cost"), money_col("per_km", "₹ / km"),
                ],
                cars,
            ),
            "allowance": table(
                [
                    text_col("label", "Case"), count_col("km", "Km"), count_col("avg_km", "Km / month"),
                    count_col("allowed", "Allowed / month"), pct_col("utilisation", "Allowance used"), money_col("cost", "Cost"),
                ],
                allowance,
                filter_key="case",
            ),
        },
        "extra": {"fleet": {"over_allowance": over}},
    }


# ------------------------------------------------------------------------------------------------------------------
# controls
# ------------------------------------------------------------------------------------------------------------------


CLIENT_ONLY_KEYS = ("client", "state", "client_type", "priority")


def _contact_block(d: Dash) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Relationships worth a check: active clients with nobody to call, and the follow-ups that have come due. Both are as at today."""
    cur = d.cur
    now = without_period(d.filters)
    fields = SCOPES["contact"]["fields"]

    # Clients are not contacts, so the contact scope cannot list them; the segment filters a client has are applied by hand.
    parts = [
        "cl.is_current AND NOT cl.is_expired", "cl.client_status = 'Active'",
        "NOT EXISTS (SELECT 1 FROM orion_dw.dim_contact k WHERE k.client_code = cl.client_code AND k.is_current AND NOT k.is_expired"
        " AND k.contact_status = 'Active')",
    ]
    params: list[Any] = []
    for key in CLIENT_ONLY_KEYS:
        if key in now:
            parts.append(f"{fields[key]} = %s")
            params.append(now[key])
    bare = [
        {"code": r[0], "label": r[1], "state": r[2] or "—", "type": r[3] or "—", "priority": r[4] or "—"}
        for r in rows(
            cur,
            "SELECT cl.client_code, cl.client_name, cl.client_location_state, cl.client_type, cl.firm_priority"
            f" FROM orion_dw.dim_client cl WHERE {' AND '.join(parts)} ORDER BY cl.client_name LIMIT 200",
            params,
        )
    ]

    bare_count = int(rows(cur, f"SELECT COUNT(*) FROM orion_dw.dim_client cl WHERE {' AND '.join(parts)}", params)[0][0])

    where, due_params = clause("contact", now, extra=["ct.contact_status = 'Active'", "ct.next_follow_up_date <= CURRENT_DATE"])
    due = [
        {
            "code": r[0], "label": r[1], "client": r[2] or "—", "role": r[3] or "—", "owner": r[4] or "—",
            "last": day_label(r[5].isoformat()) if r[5] else "Never", "due": day_label(r[6].isoformat()), "late": int(r[7] or 0),
        }
        for r in rows(
            cur,
            "SELECT ct.contact_code, ct.contact_name, cl.client_name, ct.contact_role, owner.employee_name, ct.last_contacted_date,"
            " ct.next_follow_up_date, (CURRENT_DATE - ct.next_follow_up_date)"
            f" FROM {SCOPES['contact']['from']}"
            " LEFT JOIN orion_dw.dim_employee owner ON owner.employee_code = ct.relationship_owner_code AND owner.is_current AND NOT owner.is_expired"
            f"{where} ORDER BY ct.next_follow_up_date LIMIT 100",
            due_params,
        )
    ]
    overdue = scalars(
        cur, "contact", now, {"n": "COUNT(*)"}, extra=["ct.contact_status = 'Active'", "ct.next_follow_up_date <= CURRENT_DATE"]
    )["n"]
    kpis = [
        d.snapshot_kpi("clients_no_contact", "Clients with no active contact", qty(bare_count), tone="amber", higher_is_better=False,
                       hint="Active clients, nobody to call"),
        d.snapshot_kpi("contact_follow_ups", "Follow-ups due", qty(overdue), tone="rose", higher_is_better=False,
                       hint="Active contacts past their follow-up date"),
    ]
    bare_table = table(
        [text_col("label", "Client"), text_col("state", "State"), text_col("type", "Type"), text_col("priority", "Priority")],
        bare, truncated=bare_count > len(bare),
    )
    due_table = table(
        [text_col("label", "Contact"), text_col("client", "Client"), text_col("role", "Role"), text_col("owner", "Looked after by"),
         text_col("last", "Last contacted"), text_col("due", "Follow-up was due"), count_col("late", "Days late")],
        due,
    )
    return kpis, bare_table, due_table, {"clients_no_contact": bare_count, "follow_ups_due": int(overdue)}


def controls(d: Dash) -> dict[str, Any]:
    cur, f = d.cur, d.filters
    flt = d.context_filters
    bills = month_series(
        cur, scope="bill", filters={k: v for k, v in flt.items() if k != "status"},
        metrics={
            "cancelled": "COUNT(*) FILTER (WHERE b.status = 'Cancelled')",
            "edited": "COUNT(*) FILTER (WHERE b.status = 'Issued' AND b.version_no > 1)",
            "gst_unpaid": "COALESCE(SUM(b.cgst_amount + b.sgst_amount - COALESCE(b.credited_cgst, 0) - COALESCE(b.credited_sgst, 0) - COALESCE(b.gst_paid_amount, 0)) FILTER (WHERE b.status = 'Issued' AND NOT b.gst_paid), 0)",
        },
        include_cancelled=True,
    )
    pending = month_series(cur, scope="payroll", filters=flt, metrics={"salary_pending": "COALESCE(SUM(et.salary_amount) FILTER (WHERE et.salary_paid = 'No'), 0)"})
    trend = merge_months(bills, pending)

    def bill_rows(extra: list[str], include_cancelled: bool, limit: int = 60) -> list[dict[str, Any]]:
        where, params = clause("bill", {k: v for k, v in f.items() if k != "status"}, include_cancelled=include_cancelled, extra=extra)
        return [
            {
                "code": r[0], "bill_code": r[0], "number": r[1], "date": day_label(r[2].isoformat()), "client": r[3] or "—", "case": r[4] or "—",
                "amount": num(r[5]), "version": int(r[6]), "reason": r[7] or "", "gst": num(r[8]),
            }
            for r in rows(
                cur,
                "SELECT b.bill_code, b.bill_number, b.bill_date, cl.client_name, c.case_name, b.grand_total, b.version_no,"
                f" b.status, (b.cgst_amount + b.sgst_amount - COALESCE(b.credited_cgst, 0) - COALESCE(b.credited_sgst, 0) - COALESCE(b.gst_paid_amount, 0)) FROM {SCOPES['bill']['from']}{where}"
                f" ORDER BY b.bill_date DESC, b.bill_number DESC LIMIT {limit}",
                params,
            )
        ]

    cancelled = bill_rows(["b.status = 'Cancelled'"], True)
    edited = bill_rows(["b.status = 'Issued'", "b.version_no > 1"], False)
    gst_rows = bill_rows(["b.status = 'Issued'", "NOT b.gst_paid"], False, 200)
    statutory_open = "(b.epf_amount - COALESCE(b.epf_paid_amount, 0) > 0.004 OR b.esic_amount - COALESCE(b.esic_paid_amount, 0) > 0.004)"
    where_s, params_s = clause("bill", {k: v for k, v in f.items() if k != "status"}, extra=["b.status = 'Issued'", statutory_open])
    statutory_rows = [
        {
            "code": r[0], "bill_code": r[0], "number": r[1], "date": day_label(r[2].isoformat()), "client": r[3] or "—",
            "epf": num(r[4]), "esic": num(r[5]), "amount": num(r[6]),
        }
        for r in rows(
            cur,
            "SELECT b.bill_code, b.bill_number, b.bill_date, cl.client_name,"
            " GREATEST(b.epf_amount - COALESCE(b.epf_paid_amount, 0), 0), GREATEST(b.esic_amount - COALESCE(b.esic_paid_amount, 0), 0), b.grand_total"
            f" FROM {SCOPES['bill']['from']}{where_s} ORDER BY b.bill_date DESC, b.bill_number DESC LIMIT 200",
            params_s,
        )
    ]
    where_a, params_a = clause("bill", {k: v for k, v in f.items() if k != "status"}, extra=["b.status = 'Issued'", statutory_open])
    statutory_age = [
        {"code": str(r[0]), "label": str(r[0]), "value": round(num(r[1]), 2)}
        for r in rows(
            cur,
            f"SELECT CASE WHEN {BILL_AGE} <= 30 THEN '0-30' WHEN {BILL_AGE} <= 60 THEN '31-60' WHEN {BILL_AGE} <= 90 THEN '61-90' ELSE '90+' END,"
            " COALESCE(SUM(GREATEST(b.epf_amount - COALESCE(b.epf_paid_amount, 0), 0) + GREATEST(b.esic_amount - COALESCE(b.esic_paid_amount, 0), 0)), 0)"
            f" FROM {SCOPES['bill']['from']}{where_a} GROUP BY 1 ORDER BY 1",
            params_a,
        )
    ]
    where_g, params_g = clause("bill", f, extra=["NOT b.gst_paid"])
    gst_age = [
        {"code": str(r[0]), "label": str(r[0]), "value": round(num(r[1]), 2)}
        for r in rows(
            cur,
            f"SELECT CASE WHEN {BILL_AGE} <= 30 THEN '0-30' WHEN {BILL_AGE} <= 60 THEN '31-60' WHEN {BILL_AGE} <= 90 THEN '61-90' ELSE '90+' END,"
            f" COALESCE(SUM(b.cgst_amount + b.sgst_amount - COALESCE(b.credited_cgst, 0) - COALESCE(b.credited_sgst, 0) - COALESCE(b.gst_paid_amount, 0)), 0) FROM {SCOPES['bill']['from']}{where_g} GROUP BY 1 ORDER BY 1",
            params_g,
        )
    ]
    unbilled = unbilled_cases(cur, without_period(f))
    meta = case_meta(cur)
    unbilled_rows = [
        {"code": c, "label": meta.get(c, {}).get("case", c), "client": meta.get(c, {}).get("client", "—"),
         "expected": meta.get(c, {}).get("expected", 0.0)}
        for c in unbilled.get("codes", [])
    ]
    t = d.totals
    contact_kpis, no_contact_table, follow_up_table, contact_extra = _contact_block(d)
    return {
        "kpis": contact_kpis,
        "series": {"trend": trend},
        "categories": {"gst_age": gst_age, "statutory_age": statutory_age},
        "tables": {
            "no_contact": no_contact_table,
            "follow_ups": follow_up_table,
            "cancelled": table(
                [bill_col("number", "Bill"), text_col("date", "Date"), text_col("client", "Client"), text_col("case", "Case"), money_col("amount", "Amount")],
                cancelled,
            ),
            "edited": table(
                [bill_col("number", "Bill"), text_col("date", "Date"), text_col("client", "Client"), count_col("version", "Version"), money_col("amount", "Amount")],
                edited,
            ),
            "gst": table(
                [bill_col("number", "Bill"), text_col("date", "Date"), text_col("client", "Client"), money_col("gst", "GST"), money_col("amount", "Bill total")],
                gst_rows,
                truncated=len(gst_rows) >= 200,
            ),
            "statutory": table(
                [bill_col("number", "Bill"), text_col("date", "Date"), text_col("client", "Client"), money_col("epf", "EPFO to pay"), money_col("esic", "ESIC to pay"),
                 money_col("amount", "Bill total")],
                statutory_rows,
                truncated=len(statutory_rows) >= 200,
            ),
            "unbilled": table(
                [text_col("label", "Case"), text_col("client", "Client"), money_col("expected", "Expected / month")],
                unbilled_rows, filter_key="case",
            ),
        },
        "extra": {
            "controls": {
                "cancelled": t["cancelled"], "cancelled_value": t["cancelled_value"], "edited": t["edited"], "gst_unpaid": t["gst_unpaid"],
                "epf_unpaid": t["epf_unpaid"], "esic_unpaid": t["esic_unpaid"],
            },
            "unbilled": unbilled,
            "contacts": contact_extra,
        },
    }
