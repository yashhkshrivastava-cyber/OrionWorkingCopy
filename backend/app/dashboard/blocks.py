"""Small builders the views share: ranked categories, tables with totals, stacked monthly series, financial years."""

from __future__ import annotations

from typing import Any, Sequence

from app.dashboard.engine import (
    BILLED,
    COLLECTED,
    EXPENSE,
    REVENUE,
    SALARY,
    pct,
)
from app.dashboard.filters import SCOPES, clause, common, month_label, num, rows
from app.dashboard.measures import column, grid


def ranked(items: Sequence[dict[str, Any]], key: str, limit: int | None = None, *, label: str = "label") -> list[dict[str, Any]]:
    """Rows of a pnl-style list as chart categories, largest first, zero and negative values left out."""
    out = [
        {"code": str(i["code"]), "label": str(i[label]), "value": round(float(i[key]), 2)}
        for i in sorted(items, key=lambda x: float(x[key]), reverse=True)
        if float(i[key]) > 0
    ]
    return out[:limit] if limit else out


def table(
    columns: list[dict[str, Any]],
    records: list[dict[str, Any]],
    *,
    filter_key: str | None = None,
    totals: dict[str, float] | None = None,
    truncated: bool = False,
) -> dict[str, Any]:
    block = grid(columns, records, filter_key=filter_key)
    block["totals"] = totals
    block["truncated"] = truncated
    return block


def stacked_months(
    cur,
    *,
    scope: str,
    filters: dict[str, str],
    code: str,
    label: str,
    value: str,
    top: int = 6,
    exclude: Sequence[str] = ("month",),
    extra: Sequence[str] = (),
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Months by a dimension, for a stacked chart: the largest ``top`` values plus "Other".

    Returns (points, keys). A point carries ``c0``, ``c1``… for the values; ``keys`` says what each one is.
    """
    month_field = SCOPES[scope]["fields"]["month"]
    where, params = clause(scope, filters, exclude=exclude, extra=extra)
    sql = (
        f"SELECT {month_field}, {code}, {label}, {value} FROM {SCOPES[scope]['from']}{where} GROUP BY 1, 2, 3 ORDER BY 1"
    )
    data = rows(cur, sql, params)
    totals: dict[str, float] = {}
    names: dict[str, str] = {}
    for month, key, name, amount in data:
        if month is None or key is None:
            continue
        totals[str(key)] = totals.get(str(key), 0.0) + num(amount)
        names[str(key)] = str(name or key)
    order = [k for k, _v in sorted(totals.items(), key=lambda kv: kv[1], reverse=True)]
    lead = order[:top]
    slots = {key: f"c{i}" for i, key in enumerate(lead)}
    other = f"c{len(lead)}" if len(order) > top else None
    by_month: dict[str, dict[str, float]] = {}
    for month, key, _name, amount in data:
        if month is None or key is None:
            continue
        slot = slots.get(str(key), other)
        if slot:
            point = by_month.setdefault(str(month), {})
            point[slot] = point.get(slot, 0.0) + num(amount)
    columns = [*slots.values(), *([other] if other else [])]
    points = []
    for month in sorted(by_month):
        point: dict[str, Any] = {"code": month, "label": month_label(month)}
        for slot in columns:
            point[slot] = round(by_month[month].get(slot, 0.0), 2)
        points.append(point)
    keys = [{"code": slots[k], "label": names[k], "value": round(totals[k], 2)} for k in lead]
    if other:
        keys.append({"code": other, "label": "Other", "value": round(sum(totals[k] for k in order[top:]), 2)})
    return points, keys


def financial_years(cur, filters: dict[str, str]) -> list[dict[str, Any]]:
    """One row per financial year: revenue, growth, cost, margin, cash and scale. The year and month filters are ignored."""
    shared = common(filters, "bill", "collection", "expense", "payroll")

    def by_fy(scope: str, metrics: dict[str, str]) -> dict[str, dict[str, float]]:
        fy = SCOPES[scope]["fields"]["fy"]
        where, params = clause(scope, shared, exclude=("fy", "month"))
        select = ", ".join(metrics.values())
        out: dict[str, dict[str, float]] = {}
        for row in rows(cur, f"SELECT {fy}, {select} FROM {SCOPES[scope]['from']}{where} GROUP BY 1", params):
            if row[0] is None:
                continue
            out[str(row[0])] = {name: num(row[1 + i]) for i, name in enumerate(metrics)}
        return out

    bills = by_fy("bill", {"revenue": REVENUE, "billed": BILLED, "bills": "COUNT(*)", "clients": "COUNT(DISTINCT cl.client_code)",
                           "cases": "COUNT(DISTINCT c.case_code)"})
    cash = by_fy("collection", {"collected": COLLECTED})
    spend = by_fy("expense", {"expenses": EXPENSE})
    pay = by_fy("payroll", {"payroll": SALARY, "pay_rows": "COUNT(*)", "months": "COUNT(DISTINCT et.month_year)"})
    years = sorted(set(bills) | set(pay) | set(spend))
    # Revenue by month, to compare a part-year with the same months of the year before.
    month_where, month_params = clause("bill", shared, exclude=("fy", "month"))
    by_month = {
        str(r[0]): num(r[1])
        for r in rows(
            cur,
            f"SELECT {SCOPES['bill']['fields']['month']}, {REVENUE} FROM {SCOPES['bill']['from']}{month_where} GROUP BY 1",
            month_params,
        )
        if r[0]
    }

    def same_months(fy: str, count: int) -> float:
        start = int(fy)
        return sum(by_month.get(f"{start + (1 if i >= 9 else 0)}-{(3 + i) % 12 + 1:02d}", 0.0) for i in range(count))

    out = []
    for fy in years:
        r = bills.get(fy, {})
        revenue = r.get("revenue", 0.0)
        payroll = pay.get(fy, {}).get("payroll", 0.0)
        expenses = spend.get(fy, {}).get("expenses", 0.0)
        margin = revenue - payroll - expenses
        months = pay.get(fy, {}).get("months", 0.0)
        billed_months = len([m for m in by_month if m in {f"{int(fy) + (1 if i >= 9 else 0)}-{(3 + i) % 12 + 1:02d}" for i in range(12)}])
        part = billed_months < 12
        before = str(int(fy) - 1)
        growth = None
        before_months = len([m for m in by_month if m in {f"{int(before) + (1 if i >= 9 else 0)}-{(3 + i) % 12 + 1:02d}" for i in range(12)}])
        # A year is only compared with one that ran in full (or the same months of it).
        if before in bills and bills[before].get("revenue") and (before_months == 12 or part):
            base = same_months(before, billed_months) if part else bills[before]["revenue"]
            growth = round(pct(revenue - base, base), 1) if base else None
        out.append(
            {
                "code": fy,
                "fy": f"FY {fy}-{str(int(fy) + 1)[2:]}" + (f" ({billed_months} mo)" if part else ""),
                "revenue": round(revenue, 2),
                "growth": growth,
                "cost": round(payroll + expenses, 2),
                "margin": round(margin, 2),
                "margin_pct": round(pct(margin, revenue), 1),
                "collected": round(cash.get(fy, {}).get("collected", 0.0), 2),
                "bills": int(r.get("bills", 0)),
                "clients": int(r.get("clients", 0)),
                "cases": int(r.get("cases", 0)),
                "heads": round(pay.get(fy, {}).get("pay_rows", 0.0) / months, 0) if months else 0,
                "months": int(months),
            }
        )
    return out


def money_col(key: str, label: str) -> dict[str, Any]:
    return column(key, label, "money")


def count_col(key: str, label: str) -> dict[str, Any]:
    return column(key, label, "number")


def pct_col(key: str, label: str) -> dict[str, Any]:
    return column(key, label, "percent")


def text_col(key: str, label: str) -> dict[str, Any]:
    return column(key, label, "text")


def bill_col(key: str, label: str) -> dict[str, Any]:
    """A bill number: shown as text, but the page makes it a link to the bill with a card on hover."""
    return column(key, label, "bill")


def case_meta(cur) -> dict[str, dict[str, Any]]:
    """Case names, clients and contract values as they stand now, for tables built from fact totals."""
    found = rows(
        cur,
        "SELECT c.case_code, c.case_name, cl.client_name, bd.business_domain_name, cap.capability_name,"
        " c.case_status, c.monthly_expected_revenue, c.case_start_date, c.case_end_date"
        " FROM orion_dw.dim_case c"
        " LEFT JOIN orion_dw.dim_client cl ON cl.client_code = c.client_code AND cl.is_current AND NOT cl.is_expired"
        " LEFT JOIN orion_dw.dim_business_domain bd ON bd.business_domain_code = c.business_domain_code"
        " AND bd.is_current AND NOT bd.is_expired"
        " LEFT JOIN orion_dw.dim_capability cap ON cap.capability_code = c.capability_code AND cap.is_current AND NOT cap.is_expired"
        " WHERE c.is_current AND NOT c.is_expired",
    )
    return {
        str(r[0]): {
            "case": r[1], "client": r[2] or "—", "domain": r[3] or "—", "capability": r[4] or "—",
            "status": r[5] or "—", "expected": num(r[6]), "start": r[7], "end": r[8],
        }
        for r in found
    }
