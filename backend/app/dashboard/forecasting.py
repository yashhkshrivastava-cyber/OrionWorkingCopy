"""The Forecast tab of the Orion dashboards: what the next month, quarter, half-year, year and three years are likely to look like.

The figures are the dashboard's own monthly figures (the same functions the other tabs use), taken over **all** the months the warehouse holds,
not the period chosen elsewhere (a forecast learns from the whole history), and narrowed only by who and what: one client, one business
domain, one case. The statistics are in ``app.forecast``, which knows nothing about Orion; this file only feeds it and labels the result.

Cost is payroll plus running costs, and margin is revenue less cost, worked out from the two forecasts so that it always agrees with them.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Optional

from app import forecast as fc
from app.dashboard.engine import Dash, cash_trend, trend, without_period
from app.dashboard.filters import filter_chips, rows

# key, label, what it is, the dashboard series it comes from
METRICS: tuple[tuple[str, str, str], ...] = (
    ("revenue", "Revenue", "What is earned from billing, before GST, in the month the service was for."),
    ("billed", "Billed", "Invoices raised, including GST."),
    ("collected", "Cash collected", "Money received from clients, including GST, in the month it came in."),
    ("cost", "Cost", "Payroll plus running costs."),
    ("margin", "Margin", "Revenue less cost: worked out from the two forecasts, so it always agrees with them."),
)


def _warehouse_ready(cur) -> bool:
    return bool(rows(cur, "SELECT EXISTS (SELECT 1 FROM orion_dw.fact_bill WHERE is_current AND NOT is_expired)")[0][0])


def build_forecast(raw_filters: dict[str, Any], today: Optional[date] = None) -> dict[str, Any]:
    from app.database import db_cursor

    today = today or date.today()
    with db_cursor() as cur:
        d = Dash(cur, raw_filters)
        if not _warehouse_ready(cur):
            return {"source": "orion", "ready": False, "message": "The Orion warehouse has not been loaded yet. Run the Orion warehouse pipeline from the ETL page.", "metrics": []}
        segment = without_period(d.filters)
        monthly = trend(cur, segment)
        cash = cash_trend(cur, segment)
        chips = filter_chips(cur, segment)
        options = d.filter_options()
        contracted = float(d.snapshot.get("run_rate") or 0)

    def pairs(points: list[dict[str, Any]], key: str) -> list[tuple[str, float]]:
        return [(p["code"], float(p.get(key) or 0)) for p in points]

    results = {
        "revenue": fc.forecast_series(pairs(monthly, "revenue"), as_of=today, label="Revenue"),
        "billed": fc.forecast_series(pairs(monthly, "billed"), as_of=today, label="Billed"),
        "collected": fc.forecast_series(pairs(cash, "collected"), as_of=today, label="Cash collected"),
        "cost": fc.forecast_series(pairs(monthly, "cost"), as_of=today, label="Cost"),
    }
    results["margin"] = fc.difference(results["revenue"], results["cost"], label="Margin")
    out_metrics = []
    for key, label, means in METRICS:
        result = fc.public(results[key])
        result.update({"key": key, "label": label, "means": means})
        if key == "revenue" and contracted > 0:
            result.setdefault("drivers", {})["contracted_per_month"] = round(contracted, 2)
        out_metrics.append(result)
    return {
        "source": "orion",
        "ready": True,
        "as_of": today.isoformat(),
        "filters": segment,
        "active_filters": chips,
        "options": {k: options[k] for k in ("clients", "domains", "cases") if k in options},
        "metrics": out_metrics,
        "default_metric": "revenue",
    }
