"""Orion dashboards, read from the warehouse.

``build_view`` is the only entry point: it cleans the incoming selection, works out the windows to compare with, runs
the requested tab against them, and wraps the result with the filter chips, the insights and the context every page
displays.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from app.auth import can_access_bank
from app.database import db_cursor
from app.dashboard.engine import Dash, client_revenue_map
from app.dashboard.explore import MEASURES
from app.dashboard.filters import (
    FILTER_KEYS,
    day_label,
    filter_chips,
    month_label,
    rows,
)
from app.dashboard.insights import build_insights
from app.dashboard.views import VIEWS
from app.dashboard.windows import top_movers

DEFAULT_VIEW = "overview"

# Findings from other tabs worth a place on the executive summary.
OVERVIEW_ALSO = {"concentration", "overdue", "collection_rate", "loss_cases", "margin_shift", "dso"}

#: Tabs that show something not every dashboard user may see: the tab and who may open it. The router checks it, and so does every Copilot tool
#: that reads a dashboard, because a tab is data as much as a page is.
RESTRICTED_VIEWS = {"cash": can_access_bank}


def view_allowed(view: str, user) -> bool:
    check = RESTRICTED_VIEWS.get(view)
    return check is None or bool(check(user))


def views_for(user) -> list[str]:
    return [view for view in VIEWS if view_allowed(view, user)]


__all__ = ["FILTER_KEYS", "VIEWS", "DEFAULT_VIEW", "RESTRICTED_VIEWS", "build_view", "view_allowed", "views_for"]


def _warehouse_ready(cur) -> bool:
    return bool(rows(cur, "SELECT EXISTS (SELECT 1 FROM orion_dw.fact_bill WHERE is_current AND NOT is_expired)")[0][0])


def _movers(d: Dash) -> tuple[list[tuple], list[tuple]]:
    """Clients whose revenue moved most against the earlier period (or against the month before)."""
    if d.filters.get("client") or not d.previous:
        return [], []
    names = {r["code"]: r["label"] for r in d.client_revenue}
    now = {r["code"]: r["revenue"] for r in d.client_revenue}
    before = client_revenue_map(d.cur, d.windows["previous"]["filters"])
    for code, (name, _v) in before.items():
        names.setdefault(code, name)
    gainers, losers = top_movers(now, {c: v for c, (_n, v) in before.items()})
    return (
        [(names.get(c, c), v, c) for c, v in gainers],
        [(names.get(c, c), v, c) for c, v in losers],
    )


def _facts(d: Dash, block: dict[str, Any]) -> dict[str, Any]:
    t = d.totals
    previous = d.previous[0] if d.previous else None
    gainers, losers = _movers(d)
    snapshot = dict(d.snapshot)
    owed = []
    if snapshot.get("outstanding"):
        from app.dashboard.engine import owed_by

        owed = owed_by(d.cur, d.filters, "client", limit=1)
    if owed:
        snapshot["worst_client"] = {"code": owed[0]["code"], "label": owed[0]["label"], "value": owed[0]["owed"]}
    loss = [c for c in d.cases_pnl if c["revenue"] > 0 and c["margin"] < 0]
    monthly = d.monthly
    cash = d.cash_monthly
    partial = None
    if monthly and cash and cash[-1]["code"] > monthly[-1]["code"]:
        window_end = d.window[1] if d.window else None
        last_day = date.fromisoformat(d.bounds["max"]) if d.bounds["max"] else None
        if last_day and (window_end is None or window_end.strftime("%Y-%m") >= cash[-1]["code"]):
            partial = month_label(cash[-1]["code"])
    facts: dict[str, Any] = {
        "totals": t,
        "previous": previous,
        "previous_label": d.previous[1] if d.previous else "",
        "yoy": d.yoy[0] if d.yoy else None,
        "yoy_phrase": "the " + d.yoy[1][3:] if d.yoy else "",
        "monthly": monthly,
        "gainers": gainers,
        "losers": losers,
        "clients": [{"code": r["code"], "label": r["label"], "value": r["revenue"]} for r in d.client_revenue[:10]],
        "snapshot": snapshot,
        "loss_cases": loss,
        "domains": d.domains_pnl,
        "unbilled": snapshot.get("unbilled"),
        "partial_month": partial,
        "month_selected": bool(d.filters.get("month")),
    }
    extra = block.get("extra") or {}
    facts.update(extra)
    return facts


def _empty(d: Dash, message: str) -> dict[str, Any]:
    return {
        "view": "",
        "filters": d.filters,
        "active_filters": [],
        "kpis": [],
        "series": {},
        "categories": {},
        "tables": {},
        "insights": [],
        "meta": {
            "months": 0, "range": "", "from": None, "to": None, "bounds": d.bounds, "empty": True, "message": message,
            "filter_options": {}, "invalid_filters": d.invalid, "comparison": {"previous": "", "yoy": "", "full": "", "kind": "all"},
        },
    }


def build_view(view: str, raw_filters: dict[str, Any], *, bank_access: bool = False) -> dict[str, Any]:
    """One tab's data. ``bank_access`` lets a block show what comes from the bank book (the profit and loss lines below operating profit); it is off unless the caller
    has checked the person's Bank access, so a Copilot tool or a script never shows it by accident."""
    if view not in VIEWS:
        raise KeyError(view)

    with db_cursor() as cur:
        d = Dash(cur, raw_filters)
        d.bank_access = bank_access
        if not _warehouse_ready(cur):
            payload = _empty(d, "The Orion warehouse has not been loaded yet. Run the Orion warehouse pipeline from the ETL page.")
            payload["view"] = view
            return payload
        block = VIEWS[view](d)
        kpis = [*d.kpis(), *block.get("kpis", [])]
        for item in kpis:
            item["explore"] = item["key"] in MEASURES
        chips = filter_chips(cur, d.filters)
        options = d.filter_options()
        insights = [
            i
            for i in build_insights(_facts(d, block))
            if i["area"] == view or (view == "overview" and i["id"] in OVERVIEW_ALSO)
        ]

    months = [p["code"] for p in d.monthly]
    start, end = d.filters.get("from"), d.filters.get("to")
    if start or end:
        range_label = f"{day_label(start) if start else '…'} – {day_label(end) if end else '…'}"
    elif months:
        range_label = f"{month_label(months[0])} – {month_label(months[-1])}"
    else:
        range_label = ""

    return {
        "view": view,
        "filters": d.filters,
        "active_filters": chips,
        "kpis": kpis,
        "series": block.get("series", {}),
        "categories": block.get("categories", {}),
        "tables": block.get("tables", {}),
        "insights": insights,
        "meta": {
            "months": len(months),
            "range": range_label,
            "from": start,
            "to": end,
            "bounds": d.bounds,
            "data_through": d.bounds["max"] if d.bounds["min"] else "",
            "comparison": {
                "previous": d.previous[1] if d.previous else "",
                "yoy": d.yoy[1] if d.yoy else "",
                "full": d.full[1] if d.full else "",
                # What the selection is, so a screen knows whether "same period" and "full year" both apply.
                "kind": d.window[2] if d.window else "all",
            },
            "invalid_filters": d.invalid,
            "empty": not (d.totals["bills"] or d.totals["payroll"] or d.totals["expenses"]),
            "filter_options": options,
        },
    }
