"""Read tools over the Orion dashboards: figures, comparisons, trends, rankings and what moved.

Every number returned comes from the dashboard engine (``app.dashboard``) over the warehouse, so it is the same number the
dashboard page shows for the same selection. The model gets exact values plus a few computed facts (change, share,
direction); it does not do arithmetic on them itself (it has ``calculate`` for that) and it cannot alter the blocks
(tables, charts, metric cards) these tools register for the screen.
"""

from __future__ import annotations

import math
from datetime import timedelta
from typing import Any

from urllib.parse import urlencode

from app.ai import periods
from app.ai.tools.core import READ, ToolContext, ToolError, ToolResult, tool
from app.auth import can_access_orion_dashboard
from app.dashboard import RESTRICTED_VIEWS, VIEWS, build_view
from app.dashboard.engine import Dash, owed_by
from app.dashboard.filters import DIMENSION_KEYS, clean_filters, inr

# --------------------------------------------------------------------------------------------------------- metrics

# key -> (label, unit, higher is better). None means neither direction is better (it is just a size).
PERIOD_METRICS: dict[str, tuple[str, str, bool | None]] = {
    "revenue": ("Revenue", "inr", True),
    "billed": ("Billed (with GST)", "inr", True),
    "gst": ("GST on bills", "inr", None),
    "bills": ("Bills raised", "count", None),
    "avg_bill": ("Average bill", "inr", None),
    "clients": ("Clients billed", "count", None),
    "cases_billed": ("Cases billed", "count", None),
    "collected": ("Cash collected", "inr", True),
    "collection_rate": ("Collection rate", "pct", True),
    "payroll": ("Payroll", "inr", False),
    "expenses": ("Operating expenses", "inr", False),
    "cost": ("Total cost", "inr", False),
    "margin": ("Operating margin", "inr", True),
    "margin_pct": ("Margin", "pct", True),
    "payroll_pct": ("Payroll share of revenue", "pct", False),
    "expense_pct": ("Expense share of revenue", "pct", False),
    "salary_pending": ("Salary pending", "inr", False),
    "days_to_collect": ("Days to collect", "days", False),
    "cancelled": ("Cancelled bills", "count", False),
    "edited": ("Bills edited after issue", "count", False),
    "gst_unpaid": ("GST not marked paid", "inr", False),
    "heads": ("Staff on payroll", "count", None),
    "rev_per_head": ("Revenue per employee", "inr", True),
    "km": ("Kilometres driven", "count", None),
    "fleet_cost": ("Fleet cost", "inr", False),
    "opps": ("Opportunities opened", "count", None),
    "won": ("Opportunities won", "count", True),
    "win_rate": ("Win rate", "pct", True),
}
# As of today, not for a period: what is owed and how old it is.
SNAPSHOT_METRICS: dict[str, tuple[str, str, bool | None]] = {
    "outstanding": ("Outstanding receivables", "inr", False),
    "overdue_90": ("Overdue more than 90 days", "inr", False),
    "overdue_pct": ("Share of receivables over 90 days", "pct", False),
    "dso": ("Days sales outstanding", "days", False),
    "open_bills": ("Unpaid bills", "count", False),
}
ALL_METRICS = {**PERIOD_METRICS, **SNAPSHOT_METRICS}
_SNAPSHOT_KEY = {"outstanding": "outstanding", "overdue_90": "over90", "overdue_pct": "overdue_pct", "dso": "dso", "open_bills": "open_bills"}
# What can be taken apart by client, case or business domain.
BREAKDOWN_METRICS = ("revenue", "billed", "collected", "margin", "payroll", "expenses")
DIMENSION_NAMES = {"client": "client", "case": "case", "domain": "business_domain"}


def fmt(value: float | None, unit: str) -> str:
    if value is None:
        return "—"
    if unit == "inr":
        return inr(value)
    if unit == "pct":
        return f"{value:.1f}%"
    if unit == "days":
        return f"{value:.0f} days"
    return f"{value:,.0f}"


def _round(value: Any) -> float | None:
    if value is None:
        return None
    return round(float(value), 2) if isinstance(value, (int, float)) and math.isfinite(value) else None


def change(a: float | None, b: float | None, unit: str, better: bool | None) -> dict[str, Any]:
    """``b`` against ``a``: how far and in which direction, and whether that is good news."""
    if a is None or b is None:
        return {"change": None, "change_pct": None, "direction": "unknown", "good": None}
    delta = b - a
    pct = (delta / abs(a) * 100) if a else None
    direction = "up" if delta > 0 else "down" if delta < 0 else "flat"
    if unit == "pct":
        # A percentage's change is in points; a percent-of-a-percent would mislead.
        pct = None
    good = None if (better is None or direction == "flat") else ((direction == "up") == better)
    out: dict[str, Any] = {"change": _round(delta), "change_display": fmt(abs(delta), unit) if unit != "pct" else f"{abs(delta):.1f} points",
                           "change_pct": _round(pct), "direction": direction, "good": good}
    return out


# ------------------------------------------------------------------------------------------------------- arguments

PERIOD_PROPS = {
    "period": {"type": "string", "enum": list(periods.PRESETS), "description": "A named period. Use this for 'last month', 'this quarter', 'this financial year' and so on. The server works out the dates."},
    "from": {"type": "string", "pattern": r"\d{4}-\d{2}-\d{2}", "description": "Start date (YYYY-MM-DD). Use with 'to' for an exact range; it overrides 'period'."},
    "to": {"type": "string", "pattern": r"\d{4}-\d{2}-\d{2}", "description": "End date (YYYY-MM-DD), inclusive."},
}
DIM_FILTERS = {
    "type": "object",
    "description": "Narrow the figures to a client, case, business domain and so on. For client, case, business_domain and capability give the code (CL-0003) or the exact name; anything else is a value such as a state or client type.",
    "properties": {key: {"type": "string", "maxLength": 80} for key in DIMENSION_KEYS},
    "additionalProperties": False,
}
PERIOD_SPEC = {
    "type": "object",
    "properties": {**PERIOD_PROPS},
    "additionalProperties": False,
    "description": "A period: either a named period or from/to dates.",
}


def _window(args: dict[str, Any], ctx: ToolContext, default: str | None = "all_time") -> periods.Window:
    try:
        return periods.resolve(args.get("period") or (default if not (args.get("from") or args.get("to")) else None), args.get("from"), args.get("to"), ctx.today)
    except ValueError as exc:
        raise ToolError(str(exc)) from exc


def _spec_window(spec: dict[str, Any] | None, ctx: ToolContext, default: str | None = None) -> periods.Window:
    spec = spec or {}
    return _window(spec, ctx, default or "all_time")


def _resolve_dimensions(cur, dims: dict[str, str] | None) -> tuple[dict[str, str], list[str]]:
    """Accepts a client or case by name as well as by code. A name that matches nothing, or several, is an error to say aloud."""
    out: dict[str, str] = {}
    notes: list[str] = []
    tables = {
        "client": ("orion_ods.client", "client_code", "client_name"),
        "case": ("orion_ods.case", "case_code", "case_name"),
        "business_domain": ("orion_ods.business_domain", "business_domain_code", "business_domain_name"),
        "capability": ("orion_ods.capability", "capability_code", "capability_name"),
    }
    for key, value in (dims or {}).items():
        text = str(value).strip()
        if key in tables and text:
            table, code_col, name_col = tables[key]
            cur.execute(f"SELECT {code_col}, {name_col} FROM {table} WHERE {code_col} = %s OR lower({name_col}) = lower(%s)", (text, text))
            found = cur.fetchall()
            if not found:
                cur.execute(f"SELECT {code_col}, {name_col} FROM {table} WHERE {name_col} ILIKE %s ORDER BY {name_col} LIMIT 6", ("%" + text.replace("%", "") + "%",))
                close = cur.fetchall()
                if len(close) == 1:
                    found = close
                elif close:
                    raise ToolError(f"'{text}' matches several {key}s: " + "; ".join(f"{n} ({c})" for c, n in close) + ". Ask which one is meant.")
                else:
                    raise ToolError(f"There is no {key} called '{text}'. Check the name with search_records.")
            if len(found) > 1:
                raise ToolError(f"'{text}' matches several {key}s: " + "; ".join(f"{n} ({c})" for c, n in found) + ". Ask which one is meant.")
            out[key] = found[0][0]
            if found[0][0] != text:
                notes.append(f"{key} '{text}' is {found[0][1]} ({found[0][0]})")
        elif text:
            out[key] = text
    return out, notes


def _selection(cur, args: dict[str, Any], window: periods.Window) -> tuple[dict[str, str], dict[str, str], list[str]]:
    dims, notes = _resolve_dimensions(cur, args.get("filters"))
    return {**dims, **window.filters}, dims, notes


def _link(view: str, filters: dict[str, str]) -> str:
    base = "/dashboard/orion" if view == "overview" else f"/dashboard/orion/{view}"
    clean = {k: v for k, v in filters.items() if v}
    return base + (("?" + urlencode(clean)) if clean else "")


#: The tabs these tools may read. A tab that shows the bank is read through the bank tools, which check the person's bank access.
OPEN_VIEWS = [view for view in VIEWS if view not in RESTRICTED_VIEWS]


def _needs_dashboard(user: dict[str, Any]) -> bool:
    return can_access_orion_dashboard(user)


def _metric_value(d: Dash, key: str) -> float | None:
    if key in SNAPSHOT_METRICS:
        value = d.snapshot.get(_SNAPSHOT_KEY[key])
    else:
        value = d.totals.get(key)
    return float(value) if isinstance(value, (int, float)) else None


def _empty_note(d: Dash, window: periods.Window) -> list[str]:
    notes = []
    t = d.totals
    if not (t.get("bills") or t.get("payroll") or t.get("expenses")):
        notes.append(f"There is no billing, payroll or expense data for {window.label} with this selection.")
    if d.bounds.get("max"):
        notes.append(f"The warehouse has data through {d.bounds['max']}.")
    return notes


def _source(ctx: ToolContext, label: str, window: periods.Window, d: Dash, filters: dict[str, str], view: str = "overview") -> None:
    bills = int(d.totals.get("bills") or 0)
    ctx.source(label, f"{window.label}" + (f" · {bills:,} bills analysed" if bills else ""), _link(view, filters))


# ----------------------------------------------------------------------------------------------- the whole picture

HEADLINE = ("revenue", "billed", "collected", "collection_rate", "payroll", "expenses", "margin", "margin_pct", "bills", "clients")


@tool(
    name="get_business_summary",
    label="Reading the dashboard figures",
    kind=READ,
    needs=_needs_dashboard,
    description=(
        "The headline picture of the business for a period: revenue, billed, cash collected, collection rate, payroll, expenses, margin, "
        "bills and clients, each compared with the period before (and the same period last year when available), plus what is owed, "
        "the monthly trend, the top clients and the dashboard's own findings. Use this for 'how are we doing', 'summarise the dashboard', "
        "'what changed', and as the first step of most analysis. Pass the person's filters to match what they see."
    ),
    schema={"properties": {**PERIOD_PROPS, "filters": DIM_FILTERS}},
)
def get_business_summary(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    window = _window(args, ctx, "last_12_months")
    cur = ctx.cursor()
    selection, dims, notes = _selection(cur, args, window)
    d = Dash(cur, selection)
    previous = d.previous
    insights = build_view("overview", selection).get("insights", [])
    head = []
    for key in HEADLINE:
        label, unit, better = PERIOD_METRICS[key]
        now_v = _metric_value(d, key)
        prev_v = float(previous[0].get(key)) if previous and isinstance(previous[0].get(key), (int, float)) else None
        item = {"metric": key, "label": label, "value": _round(now_v), "display": fmt(now_v, unit), "unit": unit}
        if prev_v is not None:
            item.update({"previous_value": _round(prev_v), "previous_display": fmt(prev_v, unit), **change(prev_v, now_v, unit, better)})
        head.append(item)
    snap = d.snapshot
    owed = {
        "outstanding": {"value": _round(snap.get("outstanding")), "display": inr(snap.get("outstanding") or 0)},
        "overdue_over_90_days": {"value": _round(snap.get("over90")), "display": inr(snap.get("over90") or 0)},
        "days_sales_outstanding": _round(snap.get("dso")),
        "unpaid_bills": int(snap.get("open_bills") or 0),
        "as_of": ctx.today.isoformat(),
    }
    monthly = [
        {"month": m["code"], "revenue": _round(m["revenue"]), "collected": _round(m["collected"]), "margin": _round(m["margin"]), "bills": int(m["bills"])}
        for m in d.monthly[-24:]
    ]
    top = [{"code": r["code"], "client": r["label"], "revenue": _round(r["revenue"]), "share_pct": _round(r["share"])} for r in d.client_revenue[:5]]

    cards = ctx.block(
        "metrics",
        title=f"{window.label.capitalize()}",
        items=[{"label": h["label"], "value": h["display"], "delta": (f"{h['change_pct']:+.1f}%" if h.get("change_pct") is not None else (h.get("change_display") if h.get("change_display") else None)),
                "tone": ("positive" if h.get("good") else "negative" if h.get("good") is False else "neutral")} for h in head[:6]],
        link=_link("overview", selection),
    )
    chart = ctx.block(
        "chart", title="Revenue and cash collected by month", type="bar", unit="inr",
        x=[m["month"] for m in monthly], series=[{"name": "Revenue", "values": [m["revenue"] for m in monthly]}, {"name": "Collected", "values": [m["collected"] for m in monthly]}],
        link=_link("revenue", selection),
    ) if monthly else None
    table = ctx.block(
        "table", title="Top clients by revenue", columns=[{"key": "client", "label": "Client"}, {"key": "revenue", "label": "Revenue", "format": "inr", "align": "right"}, {"key": "share_pct", "label": "Share", "format": "pct", "align": "right"}],
        rows=top, link=_link("revenue", selection),
    ) if top else None

    _source(ctx, "Executive overview", window, d, selection)
    data: dict[str, Any] = {
        "period": window.label, "from": selection.get("from"), "to": selection.get("to"), "filters_applied": {**dims}, "filter_notes": notes,
        "compared_with": d.previous[1] if d.previous else None, "headline": head, "receivables_now": owed, "monthly": monthly, "top_clients": top,
        "dashboard_findings": [{"tone": i.get("tone"), "title": i.get("title"), "detail": i.get("detail")} for i in insights[:6]],
        "notes": _empty_note(d, window),
        "blocks": [b for b in (
            {"id": cards, "shows": "headline figure cards"},
            {"id": chart, "shows": "monthly revenue and collections chart"} if chart else None,
            {"id": table, "shows": "top clients table"} if table else None) if b],
    }
    if d.window and d.window[1] and d.window[1] >= ctx.today.replace(day=1):
        data["notes"].append("The latest month may be incomplete: bills are counted by the month of service and may not all be raised yet.")
    return ToolResult(data, f"Retrieved the business summary for {window.label}")


# ---------------------------------------------------------------------------------------------------- one measure


@tool(
    name="get_metric",
    label="Looking up a figure",
    kind=READ,
    needs=_needs_dashboard,
    description=(
        "One figure for a period, compared with the period before, with its monthly trend. Metrics: "
        + ", ".join(ALL_METRICS)
        + ". The last five (outstanding, overdue_90, overdue_pct, dso, open_bills) are as of today, not for a period."
    ),
    schema={"properties": {"metric": {"type": "string", "enum": list(ALL_METRICS)}, **PERIOD_PROPS, "filters": DIM_FILTERS}, "required": ["metric"]},
)
def get_metric(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    key = args["metric"]
    label, unit, better = ALL_METRICS[key]
    window = _window(args, ctx, "last_month")
    cur = ctx.cursor()
    selection, dims, notes = _selection(cur, args, window)
    d = Dash(cur, selection)
    value = _metric_value(d, key)
    data: dict[str, Any] = {"metric": key, "label": label, "period": window.label if key in PERIOD_METRICS else "as of today", "value": _round(value), "display": fmt(value, unit), "unit": unit,
                            "filters_applied": dims, "filter_notes": notes, "notes": _empty_note(d, window)}
    if key in PERIOD_METRICS and d.previous:
        prev_v = d.previous[0].get(key)
        prev_v = float(prev_v) if isinstance(prev_v, (int, float)) else None
        data.update({"compared_with": d.previous[1], "previous_value": _round(prev_v), "previous_display": fmt(prev_v, unit), **change(prev_v, value, unit, better)})
    if key in PERIOD_METRICS:
        series = [{"month": m["code"], "value": _round(m.get(key))} for m in d.monthly if key in m][-24:]
        if series:
            data["monthly"] = series
    ctx.block("metrics", title=label, items=[{"label": label, "value": fmt(value, unit), "delta": (f"{data['change_pct']:+.1f}%" if data.get("change_pct") is not None else None),
                                               "tone": "positive" if data.get("good") else "negative" if data.get("good") is False else "neutral"}], link=_link("overview", selection))
    _source(ctx, f"{label}", window, d, selection)
    return ToolResult(data, f"Retrieved {label.lower()} for {window.label}")


# ------------------------------------------------------------------------------------------------ two periods


@tool(
    name="compare_periods",
    label="Comparing the two periods",
    kind=READ,
    needs=_needs_dashboard,
    description=(
        "Compares figures between two periods that you name (for example this month with last month, or this quarter with the same "
        "quarter last year). Returns each figure for both periods with the change and whether it is good news. If period_b is left out "
        "it is the period just before period_a."
    ),
    schema={"properties": {
        "metrics": {"type": "array", "items": {"type": "string", "enum": list(PERIOD_METRICS)}, "maxItems": 12, "description": "Figures to compare. Defaults to the headline figures."},
        "period_a": PERIOD_SPEC,
        "period_b": PERIOD_SPEC,
        "filters": DIM_FILTERS,
    }, "required": ["period_a"]},
)
def compare_periods(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    a = _spec_window(args.get("period_a"), ctx, "this_month")
    if args.get("period_b"):
        b = _spec_window(args["period_b"], ctx)
    else:
        try:
            b = periods.previous(a)
        except ValueError as exc:
            raise ToolError(str(exc)) from exc
    keys = args.get("metrics") or list(HEADLINE)
    cur = ctx.cursor()
    dims, notes = _resolve_dimensions(cur, args.get("filters"))
    da = Dash(cur, {**dims, **a.filters})
    db = Dash(cur, {**dims, **b.filters})
    rows = []
    for key in keys:
        label, unit, better = PERIOD_METRICS[key]
        va, vb = _metric_value(da, key), _metric_value(db, key)
        rows.append({"metric": key, "label": label, "unit": unit, a.label: fmt(va, unit), b.label: fmt(vb, unit), "value_a": _round(va), "value_b": _round(vb),
                     **{k: v for k, v in change(vb, va, unit, better).items()}})
    items = [{"label": r["label"], "value": r[a.label], "delta": (f"{r['change_pct']:+.1f}%" if r.get("change_pct") is not None else r.get("change_display")),
              "tone": "positive" if r.get("good") else "negative" if r.get("good") is False else "neutral"} for r in rows[:8]]
    cards = ctx.block("metrics", title=f"{a.label} compared with {b.label}", items=items, link=_link("overview", {**dims, **a.filters}))
    table = ctx.block(
        "table", title="Side by side",
        columns=[{"key": "label", "label": "Figure"}, {"key": "a", "label": a.label, "align": "right"}, {"key": "b", "label": b.label, "align": "right"}, {"key": "chg", "label": "Change", "align": "right"}],
        rows=[{"label": r["label"], "a": r[a.label], "b": r[b.label], "chg": (f"{r['change_pct']:+.1f}%" if r.get("change_pct") is not None else r.get("change_display") or "—")} for r in rows],
        link=_link("overview", {**dims, **a.filters}),
    )
    _source(ctx, f"Executive overview · {a.label}", a, da, {**dims, **a.filters})
    _source(ctx, f"Executive overview · {b.label}", b, db, {**dims, **b.filters})
    data = {"period_a": {"label": a.label, "from": a.filters.get("from"), "to": a.filters.get("to")}, "period_b": {"label": b.label, "from": b.filters.get("from"), "to": b.filters.get("to")},
            "filters_applied": dims, "filter_notes": notes, "comparison": rows, "notes": _empty_note(da, a) + _empty_note(db, b),
            "blocks": [{"id": cards, "shows": "comparison cards"}, {"id": table, "shows": "side-by-side table"}],
            "reading": "change is period_a against period_b. 'good' says whether the move is favourable (for example lower cost is good)."}
    return ToolResult(data, f"Compared {a.label} with {b.label}")


# -------------------------------------------------------------------------------------------------- what moved


def _breakdown(d: Dash, dimension: str) -> list[dict[str, Any]]:
    return {"client": d.client_revenue, "case": d.cases_pnl, "domain": d.domains_pnl}[dimension]


@tool(
    name="explain_change",
    label="Finding what moved",
    kind=READ,
    needs=_needs_dashboard,
    description=(
        "Explains a change in revenue, billed, collected, margin, payroll or expenses between two periods by finding which clients, cases "
        "or business domains account for it. Use this for 'why did revenue fall', 'which customers are responsible for the decline', "
        "'what drove the growth'. It returns the biggest contributors with how much of the total change each explains."
    ),
    schema={"properties": {
        "metric": {"type": "string", "enum": list(BREAKDOWN_METRICS)},
        "period_a": {**PERIOD_SPEC, "description": "The later period (for example last month). Defaults to last month."},
        "period_b": {**PERIOD_SPEC, "description": "The baseline to compare against. Defaults to the period before period_a."},
        "by": {"type": "string", "enum": list(DIMENSION_NAMES), "description": "What to break the change down by. Default client."},
        "filters": DIM_FILTERS,
    }, "required": ["metric"]},
)
def explain_change(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    key = args["metric"]
    by = args.get("by", "client")
    a = _spec_window(args.get("period_a"), ctx, "last_month")
    try:
        b = _spec_window(args["period_b"], ctx) if args.get("period_b") else periods.previous(a)
    except ValueError as exc:
        raise ToolError(str(exc)) from exc
    label, unit, better = PERIOD_METRICS[key]
    cur = ctx.cursor()
    dims, notes = _resolve_dimensions(cur, args.get("filters"))
    # The breakdown is by one dimension, so a filter on that same dimension would hide the answer.
    dims = {k: v for k, v in dims.items() if k != DIMENSION_NAMES[by]}
    da = Dash(cur, {**dims, **a.filters})
    db = Dash(cur, {**dims, **b.filters})
    now_rows = {r["code"]: r for r in _breakdown(da, by)}
    before_rows = {r["code"]: r for r in _breakdown(db, by)}
    total_a, total_b = _metric_value(da, key) or 0.0, _metric_value(db, key) or 0.0
    total_delta = total_a - total_b
    movers = []
    for code in set(now_rows) | set(before_rows):
        va = float((now_rows.get(code) or {}).get(key, 0) or 0)
        vb = float((before_rows.get(code) or {}).get(key, 0) or 0)
        name = (now_rows.get(code) or before_rows.get(code) or {}).get("label", code)
        delta = va - vb
        if abs(delta) < 0.5:
            continue
        movers.append({
            "code": code, "name": name, "now": _round(va), "before": _round(vb), "change": _round(delta),
            "change_pct": _round(delta / abs(vb) * 100) if vb else None,
            "share_of_total_change_pct": _round(delta / total_delta * 100) if total_delta else None,
            "status": "new" if vb == 0 and va else "stopped" if va == 0 and vb else "changed",
        })
    movers.sort(key=lambda m: m["change"])
    losers = [m for m in movers if m["change"] < 0][:6]
    gainers = [m for m in reversed(movers) if m["change"] > 0][:6]
    lead = (losers if total_delta < 0 else gainers)[:3]
    explained = sum(m["change"] for m in lead)
    rows = [{"name": m["name"], "before": fmt(m["before"], unit), "now": fmt(m["now"], unit), "change": ("-" if m["change"] < 0 else "+") + fmt(abs(m["change"]), unit)} for m in (losers[:5] + gainers[:5])]
    table = ctx.block("table", title=f"What moved {label.lower()}: {a.label} against {b.label}",
                      columns=[{"key": "name", "label": by.capitalize()}, {"key": "before", "label": b.label, "align": "right"}, {"key": "now", "label": a.label, "align": "right"}, {"key": "change", "label": "Change", "align": "right"}],
                      rows=rows, link=_link("revenue", {**dims, **a.filters}))
    chart = ctx.block("chart", title="Change by " + by, type="bar", unit=unit, x=[m["name"] for m in (losers[:5] + gainers[:5])],
                      series=[{"name": "Change", "values": [m["change"] for m in (losers[:5] + gainers[:5])]}], link=_link("revenue", {**dims, **a.filters}))
    _source(ctx, f"Executive overview · {a.label}", a, da, {**dims, **a.filters})
    _source(ctx, f"Executive overview · {b.label}", b, db, {**dims, **b.filters})
    data = {
        "metric": label, "unit": unit, "period_a": a.label, "period_b": b.label, "by": by, "filter_notes": notes,
        "total_now": _round(total_a), "total_before": _round(total_b), "total_change": _round(total_delta),
        "total_change_display": ("-" if total_delta < 0 else "+") + fmt(abs(total_delta), unit),
        "total_change_pct": _round(total_delta / abs(total_b) * 100) if total_b else None,
        "biggest_decreases": losers, "biggest_increases": gainers,
        "top_contributors_explain_pct_of_change": _round(explained / total_delta * 100) if total_delta else None,
        "notes": _empty_note(da, a),
        "blocks": [{"id": table, "shows": "contributors table"}, {"id": chart, "shows": "contributors chart"}],
        "reading": "Positive change means more in period_a. A mover with status 'stopped' billed before and nothing now; 'new' is the opposite.",
    }
    return ToolResult(data, f"Compared {by}s between {a.label} and {b.label}")


# --------------------------------------------------------------------------------------------------- top lists


@tool(
    name="get_top_items",
    label="Ranking",
    kind=READ,
    needs=_needs_dashboard,
    description=(
        "The top (or bottom) clients, cases or business domains by revenue, billed, cash collected, margin, payroll or what they owe. "
        "Use for 'show me the top 10 customers', 'who owes us the most', 'which domain earns most'."
    ),
    schema={"properties": {
        "by": {"type": "string", "enum": list(DIMENSION_NAMES)},
        "metric": {"type": "string", "enum": [*BREAKDOWN_METRICS, "outstanding"]},
        **PERIOD_PROPS,
        "limit": {"type": "integer", "minimum": 1, "maximum": 25},
        "order": {"type": "string", "enum": ["highest", "lowest"]},
        "filters": DIM_FILTERS,
    }, "required": ["by", "metric"]},
)
def get_top_items(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    by, key = args["by"], args["metric"]
    limit = args.get("limit", 10)
    window = _window(args, ctx, "last_12_months" if key != "outstanding" else "all_time")
    cur = ctx.cursor()
    selection, dims, notes = _selection(cur, args, window)
    dims = {k: v for k, v in dims.items() if k != DIMENSION_NAMES[by]}
    selection = {k: v for k, v in selection.items() if k != DIMENSION_NAMES[by]}
    d = Dash(cur, selection)
    if key == "outstanding":
        owed = owed_by(cur, selection, DIMENSION_NAMES[by])
        items = [{"code": r["code"], "name": r["label"], "value": _round(r["owed"]), "over_90_days": _round(r["over90"]), "unpaid_bills": r["open_bills"], "oldest_days": r["oldest"]} for r in owed]
        unit = "inr"
        label = "Outstanding"
    else:
        label, unit, _better = PERIOD_METRICS[key]
        items = [{"code": r["code"], "name": r["label"], "value": _round(r.get(key, 0)), "share_pct": _round(r.get("share"))} for r in _breakdown(d, by)]
    items = [i for i in items if i["value"] is not None]
    items.sort(key=lambda i: i["value"], reverse=args.get("order", "highest") == "highest")
    items = items[:limit]
    total = _metric_value(d, key) if key != "outstanding" else d.snapshot.get("outstanding")
    columns = [{"key": "name", "label": by.capitalize()}, {"key": "value", "label": label, "format": unit, "align": "right"}]
    rows = [{"name": i["name"], "value": i["value"]} for i in items]
    table = ctx.block("table", title=f"{'Top' if args.get('order', 'highest') == 'highest' else 'Lowest'} {len(items)} {by}s by {label.lower()}", columns=columns, rows=rows, link=_link("revenue" if key != "outstanding" else "collections", selection))
    _source(ctx, "Executive overview" if key != "outstanding" else "Collections dashboard", window, d, selection, "overview" if key != "outstanding" else "collections")
    data = {"by": by, "metric": label, "unit": unit, "period": window.label if key != "outstanding" else "as of today", "filters_applied": dims, "filter_notes": notes,
            "total_all_items": _round(total), "items": items, "blocks": [{"id": table, "shows": "the ranking table"}], "notes": _empty_note(d, window)}
    return ToolResult(data, f"Ranked {by}s by {label.lower()}")


# ----------------------------------------------------------------------------------------------------- over time


@tool(
    name="get_trend",
    label="Reading the trend",
    kind=READ,
    needs=_needs_dashboard,
    description="A figure month by month over a period, with the highest and lowest months and the overall direction. Use for 'show me revenue over the last 12 months' and 'is it growing'.",
    schema={"properties": {"metric": {"type": "string", "enum": list(PERIOD_METRICS)}, **PERIOD_PROPS, "filters": DIM_FILTERS}, "required": ["metric"]},
)
def get_trend(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    key = args["metric"]
    label, unit, better = PERIOD_METRICS[key]
    window = _window(args, ctx, "last_12_months")
    cur = ctx.cursor()
    selection, dims, notes = _selection(cur, args, window)
    d = Dash(cur, selection)
    source = d.cash_monthly if key == "collected" else d.monthly
    points = [{"month": m["code"], "label": m["label"], "value": _round(m.get(key if key != "collected" else "collected"))} for m in source if (key in m or key == "collected")]
    points = [p for p in points if p["value"] is not None][-36:]
    if not points:
        raise ToolError(f"There is no {label.lower()} data for {window.label} with this selection.")
    values = [p["value"] for p in points]
    high, low = max(points, key=lambda p: p["value"]), min(points, key=lambda p: p["value"])
    first, last = values[0], values[-1]
    rises = [(points[i]["month"], values[i] - values[i - 1]) for i in range(1, len(values))]
    data = {
        "metric": label, "unit": unit, "period": window.label, "filters_applied": dims, "filter_notes": notes, "points": points,
        "first": {"month": points[0]["month"], "value": first, "display": fmt(first, unit)}, "latest": {"month": points[-1]["month"], "value": last, "display": fmt(last, unit)},
        "highest": {"month": high["month"], "display": fmt(high["value"], unit), "value": high["value"]}, "lowest": {"month": low["month"], "display": fmt(low["value"], unit), "value": low["value"]},
        "average": _round(sum(values) / len(values)), "average_display": fmt(sum(values) / len(values), unit),
        **{"change_first_to_latest": change(first, last, unit, better)},
        "biggest_month_on_month_rise": max(rises, key=lambda r: r[1], default=None), "biggest_month_on_month_fall": min(rises, key=lambda r: r[1], default=None),
        "notes": ["The latest month may be incomplete."] if d.window and d.window[1] and d.window[1] >= ctx.today.replace(day=1) else [],
    }
    chart = ctx.block("chart", title=f"{label} by month", type="line" if unit == "pct" else "bar", unit=unit, x=[p["label"] for p in points], series=[{"name": label, "values": values}],
                      link=_link("revenue", selection))
    data["blocks"] = [{"id": chart, "shows": "the monthly chart"}]
    _source(ctx, "Revenue dashboard" if key not in ("collected",) else "Collections dashboard", window, d, selection, "revenue" if key != "collected" else "collections")
    return ToolResult(data, f"Retrieved the {label.lower()} trend for {window.label}")


# ----------------------------------------------------------------------------------------- what looks unusual


@tool(
    name="find_anomalies",
    label="Looking for anything unusual",
    kind=READ,
    needs=_needs_dashboard,
    description=(
        "Looks for unusual months in revenue, collections, payroll, expenses and bills (a month that jumps or drops far from the usual), "
        "and lists the dashboard's own warnings. Use for 'what's unusual', 'any problems', 'what should I focus on'."
    ),
    schema={"properties": {**PERIOD_PROPS, "filters": DIM_FILTERS}},
)
def find_anomalies(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    window = _window(args, ctx, "last_12_months")
    cur = ctx.cursor()
    selection, dims, notes = _selection(cur, args, window)
    d = Dash(cur, selection)
    findings = build_view("overview", selection).get("insights", [])
    unusual = []
    for key in ("revenue", "collected", "payroll", "expenses", "bills"):
        label, unit, better = PERIOD_METRICS[key]
        rows = d.cash_monthly if key == "collected" else d.monthly
        series = [(m["code"], float(m.get(key) or 0)) for m in rows if key in m]
        # The newest month may be unfinished, so the usual is judged on the months before it.
        if len(series) < 5:
            continue
        for index in range(3, len(series)):
            history = [v for _c, v in series[max(0, index - 6) : index]]
            mean = sum(history) / len(history)
            sd = math.sqrt(sum((v - mean) ** 2 for v in history) / len(history))
            month, value = series[index]
            if mean <= 0:
                continue
            deviation = (value - mean) / mean * 100
            z = (value - mean) / sd if sd else (math.inf if value != mean else 0)
            if abs(deviation) >= 20 and abs(z) >= 1.8:
                unusual.append({"metric": label, "month": month, "value": _round(value), "display": fmt(value, unit), "usual_display": fmt(mean, unit),
                                "usual": _round(mean), "deviation_pct": _round(deviation), "direction": "above usual" if deviation > 0 else "below usual",
                                "worrying": (deviation > 0) != bool(better) if better is not None else None})
    unusual.sort(key=lambda u: abs(u["deviation_pct"]), reverse=True)
    unusual = unusual[:10]
    _source(ctx, "Executive overview", window, d, selection)
    data = {"period": window.label, "filters_applied": dims, "filter_notes": notes, "unusual_months": unusual,
            "dashboard_findings": [{"tone": i.get("tone"), "title": i.get("title"), "detail": i.get("detail"), "tab": i.get("tab")} for i in findings[:10]],
            "method": "A month is flagged when it is at least 20% away from the average of the six months before it and clearly outside their usual spread.",
            "notes": _empty_note(d, window)}
    return ToolResult(data, f"Checked {window.label} for unusual months")


@tool(
    name="find_inactive_clients",
    label="Finding clients that have gone quiet",
    kind=READ,
    needs=_needs_dashboard,
    description="Clients that were billed earlier but have no billing in the last N months. Use for 'which customers haven't purchased recently'.",
    schema={"properties": {"months": {"type": "integer", "minimum": 1, "maximum": 24, "description": "How many recent months with no billing counts as quiet. Default 3."}}},
)
def find_inactive_clients(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    months = args.get("months", 3)
    recent = periods.Window(periods._add_months(ctx.today.replace(day=1), -(months - 1)), periods._month_end(ctx.today.year, ctx.today.month), f"the last {months} months")
    cur = ctx.cursor()
    everything = Dash(cur, {"to": (recent.start - timedelta(days=1)).isoformat()})
    lately = Dash(cur, recent.filters)
    past = {r["code"]: r for r in everything.client_revenue}
    current = {r["code"] for r in lately.client_revenue if r["revenue"] > 0}
    lapsed = []
    for code, row in past.items():
        if code in current or row["revenue"] <= 0:
            continue
        cur.execute("SELECT MAX(b.service_month) FROM orion_dw.fact_bill b JOIN orion_dw.dim_client c ON c.client_sk = b.client_sk WHERE c.client_code = %s AND b.is_current AND NOT b.is_expired", (code,))
        last_month = cur.fetchone()[0]
        lapsed.append({"code": code, "name": row["label"], "billed_before": _round(row["revenue"]), "last_billed_month": last_month.isoformat()[:7] if last_month else None})
    lapsed.sort(key=lambda r: r["billed_before"] or 0, reverse=True)
    table = ctx.block("table", title=f"Clients with no billing in the {recent.label}", columns=[{"key": "name", "label": "Client"}, {"key": "last", "label": "Last billed", "align": "right"}, {"key": "before", "label": "Billed before", "format": "inr", "align": "right"}],
                      rows=[{"name": r["name"], "last": r["last_billed_month"], "before": r["billed_before"]} for r in lapsed[:15]], link="/dashboard/orion/revenue")
    ctx.source("Revenue dashboard", f"Billing through {ctx.today:%b %Y}", "/dashboard/orion/revenue")
    data = {"months": months, "clients": lapsed[:25], "count": len(lapsed), "blocks": [{"id": table, "shows": "table of quiet clients"}],
            "notes": ([] if lapsed else [f"Every client billed before is also billed in the {recent.label}."])}
    return ToolResult(data, f"Checked which clients were quiet for {months} months")


# ------------------------------------------------------------------------------------------- a dashboard tab


def condensed_view(view: str, filters: dict[str, str]) -> dict[str, Any]:
    """A dashboard tab shortened to what a model needs: its figures, top rows of each chart and its findings."""
    payload = build_view(view, filters)
    if payload["meta"].get("empty"):
        return {"empty": True, "message": payload["meta"].get("message") or "No data for this selection."}
    kpis = [{"label": k["label"], "value": k["value"], "change": k.get("delta") or None, "compared_with": k.get("compare") or None, "tone": k.get("delta_type")} for k in payload["kpis"][:14]]
    categories = {name: [{"label": c.get("label"), "value": c.get("value")} for c in rows[:8]] for name, rows in payload["categories"].items()}
    series = {name: [{k: v for k, v in point.items() if k in ("label", "revenue", "billed", "collected", "margin", "payroll", "expenses", "bills", "heads", "km", "cost")} for point in points[-18:]]
              for name, points in payload["series"].items()}
    tables = {name: {"columns": [c["label"] for c in block["columns"]], "rows": [[row.get(c["key"]) for c in block["columns"]] for row in block["rows"][:8]]} for name, block in payload["tables"].items()}
    return {
        "view": view, "range": payload["meta"].get("range"), "data_through": payload["meta"].get("data_through"), "filters": payload["filters"],
        "active_filters": [c.get("label") if isinstance(c, dict) else str(c) for c in payload["active_filters"]],
        "compared_with": payload["meta"].get("comparison"), "kpis": kpis, "categories": categories, "series": series, "tables": tables,
        "findings": [{"tone": i.get("tone"), "title": i.get("title"), "detail": i.get("detail")} for i in payload["insights"][:8]],
    }


@tool(
    name="get_dashboard_tab",
    label="Reading that dashboard",
    kind=READ,
    needs=_needs_dashboard,
    description=(
        "Everything on one dashboard tab (figures, the charts' top rows, its tables and findings) for a selection. Tabs: "
        + ", ".join(OPEN_VIEWS)
        + ". Use it to explain a chart or summarise a tab the person is looking at."
    ),
    schema={"properties": {"view": {"type": "string", "enum": OPEN_VIEWS}, **PERIOD_PROPS, "filters": DIM_FILTERS}, "required": ["view"]},
)
def get_dashboard_tab(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    view = args["view"]
    if view not in OPEN_VIEWS:
        raise ToolError("That dashboard is not one this tool reads.")
    window = _window(args, ctx, "all_time")
    cur = ctx.cursor()
    selection, dims, notes = _selection(cur, args, window)
    data = condensed_view(view, selection)
    data["filter_notes"] = notes
    ctx.source(f"{view.capitalize()} dashboard", f"{window.label}", _link(view, selection))
    return ToolResult(data, f"Read the {view} dashboard")


@tool(
    name="get_current_view",
    label="Looking at what you're looking at",
    kind=READ,
    needs=_needs_dashboard,
    description=(
        "What the person is looking at right now, using the page and filters the application reported. Use it for 'summarise this', "
        "'explain this chart', 'what am I looking at'. Only dashboard pages can be read this way."
    ),
)
def get_current_view(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    page = ctx.page
    if page.get("area") != "dashboard" or not page.get("view") or page["view"] not in OPEN_VIEWS:
        return ToolResult({"page": page or None, "note": "The person is not on an Orion dashboard tab, so there is no chart or figure set to read. Ask what they want to look at, or use get_business_summary."},
                          "Checked the current page")
    filters = clean_filters(dict(page.get("filters") or {}))
    data = condensed_view(page["view"], filters)
    data["page"] = {"path": page.get("path"), "title": page.get("title")}
    ctx.source(f"{page['view'].capitalize()} dashboard", data.get("range") or "as on screen", _link(page["view"], filters))
    return ToolResult(data, f"Read the {page['view']} dashboard as it is on screen")
