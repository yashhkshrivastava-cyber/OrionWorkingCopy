"""The Forecast tab of the Tally dashboards: the same forecast as Orion's, over what the Tally books say was billed.

It reads the monthly figures the Tally dashboard already works out (``tally_dashboard._monthly`` and ``_document_trend``), over every month the Tally
warehouse holds and narrowed only by client, company, document type, income line and cost centre; the statistics are in ``app.forecast``.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Optional

from app import forecast as fc
from app import tally_dashboard as td
from app.database import db_cursor
from app.tally_insights import validate_filters

#: Choices that describe the period, not the business: a forecast learns from every month.
PERIOD_KEYS = ("fy", "month", "from", "to")

METRICS: tuple[tuple[str, str, str, str], ...] = (
    ("billed", "Billed", "Everything billed, including GST, net of credit notes (what Tally calls the invoice value).", "inr"),
    ("revenue", "Revenue", "What was billed before GST.", "inr"),
    ("gst", "GST billed", "The GST on what was billed.", "inr"),
    ("invoices", "Documents", "How many sales documents went out.", "count"),
    ("credit_notes", "Credit notes", "What was given back through credit notes.", "inr"),
)


def build_tally_forecast(raw_filters: dict[str, Any], today: Optional[date] = None) -> dict[str, Any]:
    today = today or date.today()
    with db_cursor() as cur:
        if not td._warehouse_ready(cur):
            return {"source": "tally", "ready": False, "message": "The Tally warehouse has not been loaded yet.", "metrics": []}
        cleaned, _problems = validate_filters(td._clean_filters(raw_filters))
        segment = {k: v for k, v in cleaned.items() if k not in PERIOD_KEYS}
        monthly = td._monthly(cur, segment)
        documents = td._document_trend(cur, segment)
        options = td._filter_options(cur)
        chips = [c for c in td._chips(segment) if c.get("key") not in PERIOD_KEYS]

    def pairs(points: list[dict[str, Any]], key: str) -> list[tuple[str, float]]:
        return [(p["code"], float(p.get(key) or 0)) for p in points]

    out = []
    for key, label, means, unit in METRICS:
        source = documents if key == "credit_notes" else monthly
        result = fc.public(fc.forecast_series(pairs(source, key), as_of=today, label=label, unit=unit))
        result.update({"key": key, "label": label, "means": means})
        out.append(result)
    return {
        "source": "tally",
        "ready": True,
        "as_of": today.isoformat(),
        "filters": segment,
        "active_filters": chips,
        "options": {k: options.get(k, []) for k in ("clients", "companies", "voucher_types", "income_lines", "cost_centres")},
        "metrics": out,
        "default_metric": "billed",
    }
