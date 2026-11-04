"""Read tools over the Tally dashboards: what was billed, to whom, the income mix, debtors and the books.

Every number comes from the same functions the Tally dashboard page uses (``app.tally_dashboard``) over the Tally warehouse,
so an answer and the page it came from agree. These are separate from the Orion tools on purpose: Orion's figures come from the
company's own operational records and bills, Tally's from the accounting books, and the two are allowed to differ. The tools say
which they are reading, and the model is told to say so too.

Nothing here writes. Access is the Tally dashboard permission, checked for each call.
"""

from __future__ import annotations

import functools
from typing import Any, Callable
from urllib.parse import urlencode

from app import tally_dashboard as td
from app.ai import periods
from app.ai.tools.analytics import PERIOD_PROPS, _round, _window, change, fmt
from app.ai.tools.core import READ, ToolContext, ToolError, ToolResult, tool
from app.auth import can_access_tally_dashboard
from app.dashboard.filters import inr

SOURCE = "Tally books"

# key -> (label, unit, higher is better). None means neither direction is better.
TALLY_METRICS: dict[str, tuple[str, str, bool | None]] = {
    "billed": ("Billed (with GST)", "inr", True),
    "revenue": ("Revenue (without GST)", "inr", True),
    "gst": ("GST billed", "inr", None),
    "invoices": ("Documents billed", "count", None),
    "clients": ("Clients billed", "count", None),
    "sales_billed": ("Sales invoiced", "inr", True),
    "sales_count": ("Sales invoices", "count", None),
    "avg_invoice": ("Average sales invoice", "inr", None),
    "credit_notes": ("Credit notes", "inr", False),
    "credit_note_count": ("Credit notes issued", "count", False),
    "credit_note_rate": ("Credit notes as a share of sales", "pct", False),
    "debit_notes": ("Debit notes", "inr", None),
    "manpower": ("Manpower income", "inr", True),
    "vehicle_rent": ("Vehicle rent income", "inr", None),
    "service_charges": ("SG service income", "inr", None),
    "epf_billed": ("EPF billed", "inr", None),
    "esic_billed": ("ESIC billed", "inr", None),
    "other_income": ("Other income", "inr", None),
}
HEADLINE = ("billed", "revenue", "gst", "invoices", "clients", "credit_notes")
# The months the dashboard can chart for a figure.
MONTHLY = {"billed": "billed", "revenue": "revenue", "gst": "gst", "invoices": "invoices"}
FILTER_KEYS = ("client", "company", "voucher_type", "income_line", "cost_centre")

FILTERS = {
    "type": "object",
    "description": (
        "Narrow the figures. client, company, voucher_type (the document type, such as Sales or Credit Note), income_line (manpower, "
        "vehicle, service, epf, esic, other_income, or a ledger name) and cost_centre take the exact name or part of it."
    ),
    "properties": {key: {"type": "string", "maxLength": 80} for key in FILTER_KEYS},
    "additionalProperties": False,
}

_DOC = " Source: the Tally books, not Orion's own records, so it can differ from the Orion dashboards."



def _with_blocks(function: Callable[[ToolContext, dict[str, Any]], ToolResult]) -> Callable[[ToolContext, dict[str, Any]], ToolResult]:
    """Lists what this call put on the screen (tables, cards, charts) in its result, so the answer can place it."""

    @functools.wraps(function)
    def run(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        before = set(ctx.blocks)
        result = function(ctx, args)
        made = [block for key, block in ctx.blocks.items() if key not in before]
        if isinstance(result.data, dict) and made and "blocks" not in result.data:
            result.data["blocks"] = [{"id": block["id"], "shows": block.get("title", "")} for block in made]
        return result

    return run


def _needs_tally(user: dict[str, Any]) -> bool:
    return can_access_tally_dashboard(user)


# --------------------------------------------------------------------------------------------------------- selection

_LOOKUPS = {
    "client": "SELECT DISTINCT party_ledger_name FROM tally_dw.fact_voucher WHERE is_current = TRUE AND COALESCE(is_sales_document, FALSE) = TRUE AND party_ledger_name ILIKE %s ORDER BY 1 LIMIT 8",
    "company": "SELECT DISTINCT company_name FROM tally_dw.fact_voucher WHERE is_current = TRUE AND COALESCE(is_sales_document, FALSE) = TRUE AND company_name ILIKE %s ORDER BY 1 LIMIT 8",
    "voucher_type": "SELECT DISTINCT voucher_type_name FROM tally_dw.fact_voucher WHERE is_current = TRUE AND COALESCE(is_sales_document, FALSE) = TRUE AND voucher_type_name ILIKE %s ORDER BY 1 LIMIT 8",
    "cost_centre": "SELECT DISTINCT cost_centre_name FROM tally_dw.fact_cost_centre_allocation WHERE is_current = TRUE AND cost_centre_name ILIKE %s ORDER BY 1 LIMIT 8",
}
_LEDGER_LOOKUP = "SELECT DISTINCT ledger_name FROM tally_dw.fact_ledger_line WHERE is_current = TRUE AND line_role = 'income' AND ledger_name ILIKE %s ORDER BY 1 LIMIT 8"
_LABELS = {"client": "client", "company": "company", "voucher_type": "document type", "cost_centre": "cost centre", "income_line": "income line"}


def _one_of(key: str, text: str, found: list[str]) -> str:
    """The single name a person meant, or an error that says what the choices are."""
    exact = [name for name in found if name.lower() == text.lower()]
    if len(exact) == 1:
        return exact[0]
    if len(found) == 1:
        return found[0]
    word = _LABELS[key]
    if not found:
        raise ToolError(f"There is no {word} called '{text}' in the Tally books. Check the name.")
    raise ToolError(f"'{text}' matches several {word}s: " + "; ".join(found) + ". Ask which one is meant.")


def _resolve(cur, filters: dict[str, str] | None) -> tuple[dict[str, str], list[str]]:
    """Accepts names, or part of a name, and turns them into what the books call them."""
    out: dict[str, str] = {}
    notes: list[str] = []
    for key, value in (filters or {}).items():
        text = str(value).strip()
        if key not in FILTER_KEYS or not text:
            continue
        like = "%" + text.replace("\\", "").replace("%", "").replace("_", "") + "%"
        if key == "income_line":
            lowered = text.lower().replace(" ", "_")
            known = {code: label for code, label in td.INCOME_LINES}
            match = next((code for code, label in known.items() if lowered in (code, label.lower().replace(" ", "_"))), None)
            if match:
                out[key] = match
                continue
            cur.execute(_LEDGER_LOOKUP, (like,))
            name = _one_of(key, text, [row[0] for row in cur.fetchall()])
        else:
            cur.execute(_LOOKUPS[key], (like,))
            name = _one_of(key, text, [row[0] for row in cur.fetchall()])
        out[key] = name
        if name != text:
            notes.append(f"{_LABELS[key]} '{text}' is {name}")
    return out, notes


def _ready(cur) -> None:
    if not td._warehouse_ready(cur):
        raise ToolError("The Tally warehouse has not been loaded yet, so there are no billed figures to read.")


def _selection(ctx: ToolContext, args: dict[str, Any], default: str) -> tuple[Any, periods.Window, dict[str, str], dict[str, str], list[str]]:
    window = _window(args, ctx, default)
    cur = ctx.cursor()
    _ready(cur)
    dims, notes = _resolve(cur, args.get("filters"))
    return cur, window, dims, {**dims, **window.filters}, notes


def _link(path: str, filters: dict[str, str]) -> str:
    base = "/dashboard/tally" + (f"/{path}" if path else "")
    clean = {k: v for k, v in filters.items() if v}
    return base + (("?" + urlencode(clean)) if clean else "")


# ------------------------------------------------------------------------------------------------------------ figures


def _totals(cur, filters: dict[str, str]) -> dict[str, float]:
    """The dashboard's totals, with the income lines taken from the ledger lines as the page does."""
    totals = td._aggregates(cur, filters)
    income = td._income_from_lines(cur, filters)
    for key, value in income["totals"].items():
        totals[key] = value
    return totals


def _figures(t: dict[str, float]) -> dict[str, float | None]:
    sales, sales_n = t.get("sales_billed", 0.0), t.get("sales_count", 0.0)
    return {
        "billed": t.get("billed"), "revenue": t.get("revenue"), "gst": t.get("gst"), "invoices": t.get("invoices"), "clients": t.get("clients"),
        "sales_billed": sales, "sales_count": sales_n, "avg_invoice": (sales / sales_n) if sales_n else None,
        "credit_notes": abs(t.get("cn_billed", 0.0)), "credit_note_count": t.get("cn_count"),
        "credit_note_rate": (abs(t.get("cn_billed", 0.0)) / sales * 100) if sales else None,
        "debit_notes": t.get("dn_billed"),
        "manpower": t.get("manpower"), "vehicle_rent": t.get("vehicle"), "service_charges": t.get("service"),
        "epf_billed": t.get("epf"), "esic_billed": t.get("esic"), "other_income": t.get("other_income"),
    }


def _previous(cur, dims: dict[str, str], window: periods.Window) -> tuple[dict[str, float | None], str] | None:
    """The figures for the stretch just before the window, when there is one and anything was billed in it."""
    if not (window.start and window.end):
        return None
    try:
        before = periods.previous(window)
    except ValueError:
        return None
    totals = _totals(cur, {**dims, **before.filters})
    return (_figures(totals), before.label) if totals.get("invoices") else None


def _item(key: str, now: float | None, before: float | None = None) -> dict[str, Any]:
    label, unit, better = TALLY_METRICS[key]
    out: dict[str, Any] = {"metric": key, "label": label, "value": _round(now), "display": fmt(now, unit), "unit": unit}
    if before is not None:
        out.update({"previous_value": _round(before), "previous_display": fmt(before, unit), **change(before, now, unit, better)})
    return out


def _tone(item: dict[str, Any]) -> str:
    return "positive" if item.get("good") else "negative" if item.get("good") is False else "neutral"


def _delta(item: dict[str, Any]) -> str | None:
    if item.get("change_pct") is not None:
        return f"{item['change_pct']:+.1f}%"
    return item.get("change_display")


def _notes(totals: dict[str, float], bounds: dict[str, str], window: periods.Window) -> list[str]:
    notes = []
    if not totals.get("invoices"):
        notes.append(f"Nothing was billed in the Tally books for {window.label} with this selection.")
    if bounds.get("max"):
        notes.append(f"The Tally books have billed documents through {bounds['max']}.")
    return notes


def _source(ctx: ToolContext, label: str, window: periods.Window, totals: dict[str, float], path: str, filters: dict[str, str]) -> None:
    docs = int(totals.get("invoices") or 0)
    ctx.source(f"{SOURCE}: {label}", f"{window.label}" + (f" · {docs:,} documents" if docs else ""), _link(path, filters))


# ---------------------------------------------------------------------------------------------------- the picture


@tool(
    name="get_tally_summary",
    label="Reading the Tally books",
    kind=READ,
    needs=_needs_tally,
    description=(
        "The billing picture from the Tally books for a period: billed, revenue, GST, documents, clients and credit notes, each against the "
        "period before, plus the monthly trend, the top clients, where the income comes from, what Sundry Debtors show now, and the "
        "dashboard's own findings. Use for 'how is billing in Tally', 'summarise the Tally dashboard', 'what do the books say'." + _DOC
    ),
    schema={"properties": {**PERIOD_PROPS, "filters": FILTERS}},
)
@_with_blocks
def get_tally_summary(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    cur, window, dims, selection, notes = _selection(ctx, args, "last_12_months")
    bounds = td._data_span(cur)
    totals = _totals(cur, selection)
    now = _figures(totals)
    prior = _previous(cur, dims, window)
    head = [_item(key, now[key], prior[0][key] if prior else None) for key in HEADLINE]
    monthly = [
        {"month": m["code"], "billed": _round(m["billed"]), "revenue": _round(m["revenue"]), "gst": _round(m["gst"]), "documents": int(m["invoices"])}
        for m in td._monthly(cur, selection)[-24:]
    ]
    revenue_total = totals.get("revenue") or 0.0
    top = [
        {"client": r["code"], "revenue": _round(r["revenue"]), "billed": _round(r["billed"]), "share_pct": _round(r["revenue"] / revenue_total * 100) if revenue_total else None}
        for r in td._top_clients(cur, selection, 5)
    ]
    income = [{"line": g["label"], "amount": _round(g["value"]), "display": inr(g["value"])} for g in td._income_from_lines(cur, selection)["groups"]]
    debtors = td._debtor_snapshot(cur, dims)
    findings: list[dict[str, Any]] = []
    try:
        findings = [{"tone": i.get("tone"), "title": i.get("title"), "detail": i.get("detail")} for i in td.build_tally_dashboard(selection).get("insights", [])[:6]]
    except Exception:  # noqa: BLE001 - the figures above are enough; the findings are a bonus
        findings = []

    cards = ctx.block(
        "metrics", title=f"Tally: {window.label}",
        items=[{"label": h["label"], "value": h["display"], "delta": _delta(h), "tone": _tone(h)} for h in head],
        link=_link("", selection),
    )
    chart = ctx.block(
        "chart", title="Billed by month (Tally)", type="bar", unit="inr", x=[m["month"] for m in monthly],
        series=[{"name": "Revenue", "values": [m["revenue"] for m in monthly]}, {"name": "GST", "values": [m["gst"] for m in monthly]}],
        link=_link("billing", selection),
    ) if monthly else None
    table = ctx.block(
        "table", title="Top clients by revenue (Tally)",
        columns=[{"key": "client", "label": "Client"}, {"key": "revenue", "label": "Revenue", "format": "inr", "align": "right"}, {"key": "share_pct", "label": "Share", "format": "pct", "align": "right"}],
        rows=top, link=_link("clients", selection),
    ) if top else None
    _source(ctx, "Billing overview", window, totals, "", selection)
    data: dict[str, Any] = {
        "source": SOURCE, "period": window.label, "from": selection.get("from"), "to": selection.get("to"), "filters_applied": dims, "filter_notes": notes,
        "compared_with": prior[1] if prior else None, "headline": head, "monthly": monthly, "top_clients": top, "income_by_line": income,
        "sundry_debtors_now": {"closing_balance": _round(debtors["balance"]), "display": inr(debtors["balance"]), "ledgers": int(debtors["count"]),
                               "note": "Tally shows debit balances as negative. This is the closing balance at the last warehouse load, not aged receivables."},
        "dashboard_findings": findings, "notes": _notes(totals, bounds, window),
        "blocks": [b for b in (
            {"id": cards, "shows": "headline Tally figure cards"},
            {"id": chart, "shows": "monthly billing chart"} if chart else None,
            {"id": table, "shows": "top clients table"} if table else None) if b],
    }
    return ToolResult(data, f"Retrieved the Tally billing summary for {window.label}")


# ------------------------------------------------------------------------------------------------------ one figure


@tool(
    name="get_tally_metric",
    label="Looking up a Tally figure",
    kind=READ,
    needs=_needs_tally,
    description=(
        "One figure from the Tally books for a period, against the period before, with its monthly trend where there is one. Metrics: "
        + ", ".join(TALLY_METRICS) + ". Use for 'how much did we bill Acme last year in Tally', 'credit notes this quarter', 'manpower income'." + _DOC
    ),
    schema={"properties": {"metric": {"type": "string", "enum": list(TALLY_METRICS)}, **PERIOD_PROPS, "filters": FILTERS}, "required": ["metric"]},
)
@_with_blocks
def get_tally_metric(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    key = args["metric"]
    cur, window, dims, selection, notes = _selection(ctx, args, "last_month")
    bounds = td._data_span(cur)
    totals = _totals(cur, selection)
    now = _figures(totals)[key]
    prior = _previous(cur, dims, window)
    data: dict[str, Any] = {"source": SOURCE, **_item(key, now, prior[0][key] if prior else None), "period": window.label, "filters_applied": dims,
                            "filter_notes": notes, "notes": _notes(totals, bounds, window)}
    if prior:
        data["compared_with"] = prior[1]
    if key in MONTHLY:
        series = [{"month": m["code"], "value": _round(m[MONTHLY[key]])} for m in td._monthly(cur, selection)[-24:]]
        if series:
            data["monthly"] = series
    ctx.block("metrics", title=data["label"], items=[{"label": data["label"], "value": data["display"], "delta": _delta(data), "tone": _tone(data)}], link=_link("", selection))
    _source(ctx, data["label"], window, totals, "", selection)
    return ToolResult(data, f"Retrieved {data['label'].lower()} from the Tally books for {window.label}")


# ---------------------------------------------------------------------------------------------------- two periods


@tool(
    name="compare_tally_periods",
    label="Comparing two periods in the Tally books",
    kind=READ,
    needs=_needs_tally,
    description=(
        "The Tally billing figures for two periods side by side, with the change in each. period_b defaults to the stretch just before "
        "period_a. Use for 'compare billing this quarter with last quarter in Tally'." + _DOC
    ),
    schema={
        "properties": {
            "period_a": {"type": "object", "properties": {**PERIOD_PROPS}, "additionalProperties": False, "description": "The period to look at."},
            "period_b": {"type": "object", "properties": {**PERIOD_PROPS}, "additionalProperties": False, "description": "The period to compare it with. Omit for the period before."},
            "metrics": {"type": "array", "items": {"type": "string", "enum": list(TALLY_METRICS)}, "maxItems": 12, "description": "Which figures. Omit for the headline ones."},
            "filters": FILTERS,
        },
        "required": ["period_a"],
    },
)
@_with_blocks
def compare_tally_periods(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    cur = ctx.cursor()
    _ready(cur)
    dims, notes = _resolve(cur, args.get("filters"))
    a = _window(args["period_a"], ctx, "last_month")
    if args.get("period_b"):
        b = _window(args["period_b"], ctx, "last_month")
    else:
        try:
            b = periods.previous(a)
        except ValueError as exc:
            raise ToolError(str(exc)) from exc
    keys = list(args.get("metrics") or HEADLINE)
    now = _figures(_totals(cur, {**dims, **a.filters}))
    then = _figures(_totals(cur, {**dims, **b.filters}))
    rows = []
    for key in keys:
        label, unit, better = TALLY_METRICS[key]
        rows.append({"metric": key, "label": label, "a": _round(now[key]), "a_display": fmt(now[key], unit), "b": _round(then[key]), "b_display": fmt(then[key], unit),
                     **change(then[key], now[key], unit, better)})
    ctx.block(
        "table", title=f"{a.label.capitalize()} against {b.label} (Tally)",
        columns=[{"key": "label", "label": "Figure"}, {"key": "a_display", "label": a.label.capitalize(), "align": "right"}, {"key": "b_display", "label": b.label.capitalize(), "align": "right"}, {"key": "change_display", "label": "Change", "align": "right"}],
        rows=rows, link=_link("", dims),
    )
    ctx.source(f"{SOURCE}: comparison", f"{a.label} against {b.label}", _link("", {**dims, **a.filters}))
    return ToolResult({"source": SOURCE, "period_a": {"label": a.label}, "period_b": {"label": b.label}, "filters_applied": dims, "filter_notes": notes, "comparison": rows},
                      f"Compared {a.label} with {b.label} in the Tally books")


# ---------------------------------------------------------------------------------------------------------- clients


@tool(
    name="get_tally_top_clients",
    label="Ranking clients in the Tally books",
    kind=READ,
    needs=_needs_tally,
    description=(
        "The clients billed the most in the Tally books for a period, with each one's share and how concentrated billing is. "
        "Use for 'who are our biggest clients in Tally' and 'how dependent are we on one client'." + _DOC
    ),
    schema={"properties": {**PERIOD_PROPS, "metric": {"type": "string", "enum": ["revenue", "billed"]}, "limit": {"type": "integer", "minimum": 1, "maximum": 25}, "filters": FILTERS}},
)
@_with_blocks
def get_tally_top_clients(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    cur, window, dims, selection, notes = _selection(ctx, args, "last_12_months")
    metric = args.get("metric") or "revenue"
    limit = int(args.get("limit") or 10)
    totals = td._aggregates(cur, selection)
    whole = totals.get("revenue" if metric == "revenue" else "billed") or 0.0
    rows = sorted(td._top_clients(cur, selection, 100), key=lambda r: r[metric], reverse=True)
    ranked = [
        {"rank": i + 1, "client": r["code"], "revenue": _round(r["revenue"]), "billed": _round(r["billed"]), "share_pct": _round(r[metric] / whole * 100) if whole else None}
        for i, r in enumerate(rows[:limit])
    ]
    top3 = sum(r["share_pct"] or 0 for r in ranked[:3])
    if ranked:
        ctx.block(
            "table", title=f"Top clients by {'revenue' if metric == 'revenue' else 'amount billed'} (Tally)",
            columns=[{"key": "rank", "label": "#"}, {"key": "client", "label": "Client"}, {"key": "revenue", "label": "Revenue", "format": "inr", "align": "right"},
                     {"key": "billed", "label": "Billed", "format": "inr", "align": "right"}, {"key": "share_pct", "label": "Share", "format": "pct", "align": "right"}],
            rows=ranked, link=_link("clients", selection),
        )
    _source(ctx, "Clients", window, totals, "clients", selection)
    data = {
        "source": SOURCE, "period": window.label, "ranked_by": metric, "filters_applied": dims, "filter_notes": notes, "clients_billed": int(totals.get("clients") or 0),
        "total": _round(whole), "total_display": inr(whole), "top_three_share_pct": _round(top3) if len(ranked) >= 3 else None, "clients": ranked,
        "notes": [] if ranked else [f"Nothing was billed in the Tally books for {window.label} with this selection."],
    }
    return ToolResult(data, f"Ranked {len(ranked)} clients from the Tally books for {window.label}")


# --------------------------------------------------------------------------------------------------------- income


@tool(
    name="get_tally_income_mix",
    label="Reading the Tally income lines",
    kind=READ,
    needs=_needs_tally,
    description=(
        "Where the income comes from in the Tally books for a period: manpower, vehicle rent, SG service, EPF, ESIC and other income, with "
        "each line's share and the ledgers behind them. Use for 'how much is manpower versus vehicle rent'." + _DOC
    ),
    schema={"properties": {**PERIOD_PROPS, "filters": FILTERS}},
)
@_with_blocks
def get_tally_income_mix(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    cur, window, dims, selection, notes = _selection(ctx, args, "last_12_months")
    income = td._income_from_lines(cur, selection)
    whole = sum(g["value"] for g in income["groups"]) or 0.0
    groups = [
        {"line": g["label"], "amount": _round(g["value"]), "display": inr(g["value"]), "share_pct": _round(g["value"] / whole * 100) if whole else None}
        for g in income["groups"]
    ]
    ledgers = [{"ledger": r["code"], "group": r["group"], "amount": _round(r["revenue"]), "share_pct": r["share"]} for r in income["rows"][:10]]
    if groups:
        ctx.block(
            "table", title="Income by line (Tally)",
            columns=[{"key": "line", "label": "Income line"}, {"key": "amount", "label": "Amount", "format": "inr", "align": "right"}, {"key": "share_pct", "label": "Share", "format": "pct", "align": "right"}],
            rows=groups, link=_link("income", selection),
        )
    ctx.source(f"{SOURCE}: income mix", window.label, _link("income", selection))
    data = {
        "source": SOURCE, "period": window.label, "filters_applied": dims, "filter_notes": notes, "total": _round(whole), "total_display": inr(whole), "by_line": groups,
        "largest_ledgers": ledgers, "notes": [] if groups else [f"No income lines were found in the Tally books for {window.label} with this selection."],
    }
    return ToolResult(data, f"Retrieved the Tally income mix for {window.label}")


# -------------------------------------------------------------------------------------------------------- debtors


@tool(
    name="get_tally_debtors",
    label="Reading the Sundry Debtors",
    kind=READ,
    needs=_needs_tally,
    description=(
        "What the Tally books show for Sundry Debtors now: the total closing balance and the largest ledgers, with how much each was billed "
        "in the period. This is the books' balance at the last warehouse load, NOT aged receivables; for what clients owe on bills and how "
        "old it is, use get_receivables. Tally shows debit balances as negative." + _DOC
    ),
    schema={"properties": {**PERIOD_PROPS, "limit": {"type": "integer", "minimum": 1, "maximum": 25}, "filters": FILTERS}},
)
@_with_blocks
def get_tally_debtors(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    cur, window, dims, selection, notes = _selection(ctx, args, "last_12_months")
    limit = int(args.get("limit") or 10)
    snapshot = td._debtor_snapshot(cur, dims)
    rows = td._debtor_rows(cur, selection, max(limit, 25))[:limit]
    listed = [{"client": r["code"], "closing_balance": _round(r["closing"]), "closing_display": inr(r["closing"]), "billed_revenue_in_period": _round(r["revenue"]), "documents_in_period": int(r["invoices"])} for r in rows]
    if listed:
        ctx.block(
            "table", title="Sundry Debtors, largest balances (Tally)",
            columns=[{"key": "client", "label": "Debtor"}, {"key": "closing_balance", "label": "Closing", "format": "inr", "align": "right"}, {"key": "billed_revenue_in_period", "label": "Billed in period", "format": "inr", "align": "right"}],
            rows=listed, link=_link("clients", selection),
        )
    ctx.source(f"{SOURCE}: debtors", "closing balances at the last warehouse load", _link("clients", dims))
    data = {"source": SOURCE, "as_of": "the last warehouse load", "filters_applied": dims, "filter_notes": notes, "total_closing_balance": _round(snapshot["balance"]),
            "total_display": inr(snapshot["balance"]), "debtor_ledgers": int(snapshot["count"]), "largest": listed,
            "note": "Tally shows debit balances as negative. These are book balances, not aged receivables."}
    return ToolResult(data, "Retrieved the Sundry Debtors from the Tally books")


# ---------------------------------------------------------------------------------------------------- credit notes


@tool(
    name="get_tally_credit_notes",
    label="Reading the Tally credit and debit notes",
    kind=READ,
    needs=_needs_tally,
    description=(
        "Credit and debit notes in the Tally books for a period: how many, how much, credit notes as a share of sales, which clients had the "
        "most credited, and the latest notes. Use for 'how many credit notes this year' and 'who gets the most credit notes'." + _DOC
    ),
    schema={"properties": {**PERIOD_PROPS, "limit": {"type": "integer", "minimum": 1, "maximum": 25}, "filters": FILTERS}},
)
@_with_blocks
def get_tally_credit_notes(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    cur, window, dims, selection, notes = _selection(ctx, args, "last_12_months")
    limit = int(args.get("limit") or 10)
    totals = td._aggregates(cur, selection)
    now = _figures(totals)
    by_client = [{"client": r["code"], "credited": _round(r["value"])} for r in td._notes_by_client(cur, selection, limit)]
    latest = [{"date": r["date"], "voucher": r["voucher"], "type": r["type"], "client": r["code"], "amount": _round(r["billed"]), "narration": r["narration"]}
              for r in td._note_documents(cur, selection, limit)]
    if latest:
        ctx.block(
            "table", title="Latest credit and debit notes (Tally)",
            columns=[{"key": "date", "label": "Date"}, {"key": "type", "label": "Type"}, {"key": "client", "label": "Client"}, {"key": "amount", "label": "Amount", "format": "inr", "align": "right"}],
            rows=latest, link=_link("credit-notes", selection),
        )
    _source(ctx, "Credit and debit notes", window, totals, "credit-notes", selection)
    data = {"source": SOURCE, "period": window.label, "filters_applied": dims, "filter_notes": notes,
            "credit_notes": _item("credit_notes", now["credit_notes"]), "credit_note_count": int(now["credit_note_count"] or 0),
            "credit_note_rate": _item("credit_note_rate", now["credit_note_rate"]), "debit_notes": _item("debit_notes", now["debit_notes"]),
            "debit_note_count": int(totals.get("dn_count") or 0), "most_credited_clients": by_client, "latest_notes": latest,
            "notes": [] if (latest or by_client or now["credit_notes"]) else [f"No credit or debit notes in the Tally books for {window.label} with this selection."]}
    return ToolResult(data, f"Retrieved credit and debit notes from the Tally books for {window.label}")


# ------------------------------------------------------------------------------------------------------------ books


@tool(
    name="get_tally_books_position",
    label="Reading the Tally balances",
    kind=READ,
    needs=_needs_tally,
    description=(
        "The books' closing balances at the last warehouse load: GST payable, loans, sundry creditors, statutory liabilities, cash and bank, "
        "and capital / profit and loss. They are different kinds of balance, so they are never added into one total. Signs are as Tally "
        "stores them (debit balances negative). Use for 'what is our GST liability', 'how much cash do the books show', 'what loans do we have'." + _DOC
    ),
    schema={"properties": {"filters": {"type": "object", "properties": {"company": {"type": "string", "maxLength": 80}}, "additionalProperties": False, "description": "Optionally one company."}}},
)
@_with_blocks
def get_tally_books_position(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    cur = ctx.cursor()
    _ready(cur)
    dims, notes = _resolve(cur, {k: v for k, v in (args.get("filters") or {}).items() if k == "company"})
    position = td._books_position(cur, dims)
    named = [
        ("GST payable", position["gst_payable"]), ("Loans", position["loans"]), ("Sundry creditors", position["creditors"]),
        ("Statutory and other liabilities", position["statutory"]), ("Cash and bank", position["cash"]), ("Capital and profit and loss", position["profit_loss"]),
    ]
    balances = [{"balance": label, "closing": _round(value), "display": inr(value)} for label, value in named]
    # Whatever else the books hold a balance for (sundry debtors, assets), so a nil row above is not mistaken for an empty ledger.
    shown = {"GST payable", "Loans", "Sundry creditors", "Statutory / other liabilities", "Cash and bank", "Capital / P&L"}
    others = [{"balance": b["label"], "closing": _round(b["value"]), "display": inr(b["value"])} for b in position["balances"] if b["label"] not in shown]
    ctx.block(
        "table", title="Closing balances in the Tally books",
        columns=[{"key": "balance", "label": "Balance"}, {"key": "closing", "label": "Closing", "format": "inr", "align": "right"}],
        rows=balances, link=_link("books", dims),
    )
    ctx.source(f"{SOURCE}: balances", "closing balances at the last warehouse load", _link("books", dims))
    data = {"source": SOURCE, "as_of": "the last warehouse load", "filters_applied": dims, "filter_notes": notes, "balances": balances, "other_balances": others,
            "loan_ledgers": position["loan_ledgers"], "creditor_ledgers": position["creditor_ledgers"],
            "note": "Signs are as Tally stores them (debit balances negative). These balances are different kinds of figure and are not added together."}
    return ToolResult(data, "Retrieved the closing balances from the Tally books")
