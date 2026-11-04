"""A read tool over the Forecast tabs: where a figure is heading over the next month, quarter, half-year, year and three years.

It calls the same builders the two Forecast pages use (``dashboard.forecasting`` for Orion, ``tally_forecast`` for the Tally books), so an answer and the page it
came from agree. Nothing here writes. Access is the dashboard permission of the source asked about, checked for each call.
"""

from __future__ import annotations

from typing import Any

from app.ai.tools.core import READ, ToolContext, ToolError, ToolResult, tool
from app.auth import can_access_orion_dashboard, can_access_tally_dashboard
from app.dashboard.filters import inr

ORION_METRICS = ["revenue", "billed", "collected", "cost", "margin"]
TALLY_METRICS = ["billed", "revenue", "gst", "invoices", "credit_notes"]


def _needs(user: dict[str, Any]) -> bool:
    return can_access_orion_dashboard(user) or can_access_tally_dashboard(user)


def _r(value: Any) -> float:
    return round(float(value or 0), 2)


@tool(
    name="get_forecast",
    label="Looking ahead",
    kind=READ,
    needs=_needs,
    description=(
        "Where a business figure is heading if it keeps its present pace: the expected total, and a likely range, for the next month, 3 months, 6 months, 12 months "
        "and 3 years, how it compares with the same length of time just gone, and how confident the forecast is and why. source is 'orion' (revenue, billed, "
        "collected, cost, margin from the company's own records) or 'tally' (billed, revenue, gst, invoices, credit_notes from the Tally books). Use it for "
        "'what will revenue be next year', 'how will the next quarter look', 'where are we heading'. Always give the range and the confidence with the number: "
        "a short history makes the far end indicative only."
    ),
    schema={
        "properties": {
            "source": {"type": "string", "enum": ["orion", "tally"], "description": "Where the figures come from. Default: Orion if the person may see it."},
            "metric": {"type": "string", "enum": sorted(set(ORION_METRICS + TALLY_METRICS)), "description": "The figure. Default: revenue (Orion) or billed (Tally)."},
        }
    },
)
def get_forecast(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    source = args.get("source") or ("orion" if can_access_orion_dashboard(ctx.user) else "tally")
    if source == "orion":
        if not can_access_orion_dashboard(ctx.user):
            raise ToolError("You do not have access to the Orion dashboards.")
        from app.dashboard.forecasting import build_forecast

        payload = build_forecast({})
        link = "/dashboard/orion/forecast"
    else:
        if not can_access_tally_dashboard(ctx.user):
            raise ToolError("You do not have access to the Tally dashboards.")
        from app.tally_forecast import build_tally_forecast

        payload = build_tally_forecast({})
        link = "/dashboard/tally/forecast"
    if not payload.get("ready"):
        raise ToolError(payload.get("message") or "The warehouse has not been loaded yet.")
    wanted = args.get("metric") or payload["default_metric"]
    metric = next((m for m in payload["metrics"] if m["key"] == wanted), None)
    if metric is None:
        raise ToolError(f"The {source} forecast has no figure called {wanted}. Choose from: " + ", ".join(m["key"] for m in payload["metrics"]) + ".")
    if not metric["available"]:
        raise ToolError(f"{metric['label']} cannot be forecast yet: " + " ".join(metric.get("notes") or []))
    count = metric["unit"] == "count"
    shown = (lambda v: f"{round(v):,}") if count else (lambda v: inr(v))
    data = {
        "source": "Orion records" if source == "orion" else "Tally books",
        "figure": metric["label"],
        "what_it_is": metric["means"],
        "history_through": metric["data_through"],
        "confidence": metric["confidence"]["level"],
        "why": metric["confidence"]["reasons"],
        "notes": metric["notes"],
        "horizons": [
            {
                "period": h["label"], "to": h["through"], "expected": _r(h["expected"]), "expected_display": shown(h["expected"]),
                "likely_low": _r(h["p10"]), "likely_high": _r(h["p90"]), "range_means": "8 in 10 outcomes fall inside",
                "change_vs_same_length_just_gone_pct": None if h["change_pct"] is None else round(h["change_pct"], 1),
            }
            for h in metric["horizons"]
        ],
        "financial_years": [
            {"fy": y["fy"], "expected_for_the_year": _r(y["expected"]), "complete_year": y["complete"], "done_so_far": _r(y["actual"])} for y in metric["years"]
        ],
        "pace": {
            k: (None if v is None else round(v, 1))
            for k, v in (metric.get("drivers") or {}).items()
            if k in ("growth_yoy_pct", "pace_pct_per_year", "volatility_pct")
        },
        "method": "damped trend, run-rate, trend line and (with two years of history) seasonal models, blended by how well each did when tested on the past",
    }
    ctx.source("Forecast", f"{metric['label']} ({'Orion' if source == 'orion' else 'Tally'})", link)
    ctx.remember(data)
    return ToolResult(data, f"Read the {metric['label'].lower()} forecast ({metric['confidence']['level'].replace('_', ' ')} confidence)")
