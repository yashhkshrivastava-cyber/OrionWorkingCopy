"""Pure helpers for the Tally dashboard: filter validation, comparison windows, insights.

Nothing here touches the database. ``tally_dashboard`` runs the queries and hands the
results in, so every rule below can be tested on plain numbers.

Every insight is computed from the figures the dashboard already shows. The only
judgement calls are the named thresholds below; each is quoted in the insight text
that depends on it.
"""

from __future__ import annotations

from calendar import monthrange
from datetime import date
from typing import Any

from app.dashboard.filters import day_label, inr, month_label
from app.dashboard.windows import (  # noqa: F401  (re-exported: the Tally code and tests use these names)
    comparison_windows,
    fy_label,
    parse_day,
    resolve_fy,
    selected_window,
    top_movers,
    validate_filters,
)

# Share of revenue from one client above which concentration is flagged.
CONCENTRATION_FLAG_PCT = 30.0
# A month this many times above (or below 1/n of) the average of the others is called out.
SWING_RATIO = 2.0
# Months needed in view before a swing is meaningful.
MIN_MONTHS_FOR_SWING = 6
MAX_INSIGHTS = 8



# --------------------------------------------------------------------------- movers


# --------------------------------------------------------------------------- insights


def _signed_pct(current: float, previous: float) -> float | None:
    if not previous:
        return None
    return (current - previous) / abs(previous) * 100


def _fallback_short(name: str, limit: int = 28) -> str:
    text = " ".join((name or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def build_insights(
    *,
    totals: dict[str, float],
    previous: dict[str, float] | None,
    previous_label: str,
    yoy: dict[str, float] | None,
    monthly: list[dict[str, Any]],
    clients: list[dict[str, Any]],
    gainers: list[tuple[str, float]],
    losers: list[tuple[str, float]],
    mover_basis: str,
    mover_months: tuple[str, str] | None,
    notes: list[dict[str, Any]],
    income_groups: list[dict[str, Any]],
    data_end: date | None,
    window: tuple[date, date] | None = None,
    month_selected: bool = False,
    like_for_like: bool = False,
    yoy_phrase: str = "the same period last year",
    shorten=None,
) -> list[dict[str, Any]]:
    """Each insight: id, area (which tab shows it), tone, title, detail, optional action.

    ``window`` is the span the filters select (None for all time); the partial-month
    warning only appears when that span reaches the half-billed month.
    """
    short = shorten or _fallback_short
    if not totals.get("invoices"):
        return []
    out: list[dict[str, Any]] = []

    # 1. Partial latest month. Warns before any month-on-month number is trusted.
    if monthly and data_end:
        last = monthly[-1]["code"]
        month_start = data_end.replace(day=1)
        in_scope = window is None or window[1] >= month_start
        month_open = data_end.day < monthrange(data_end.year, data_end.month)[1]
        if last == data_end.strftime("%Y-%m") and month_open and in_scope:
            out.append(
                {
                    "id": "partial_month",
                    "area": "trend",
                    "tone": "warning",
                    "title": f"{month_label(last)} is only partly billed",
                    "detail": (
                        f"The latest billed document is dated {day_label(data_end.isoformat())}. "
                        + (
                            "Comparisons here use the same days of the earlier period."
                            if like_for_like
                            else "Month-on-month comparisons with this month understate it."
                        )
                    ),
                }
            )

    # 2. What moved: window vs previous window, or the last two months when no window is set.
    if previous is not None and previous.get("billed") is not None and previous.get("invoices"):
        pct = _signed_pct(totals["billed"], previous["billed"])
        if pct is not None:
            out.append(
                _change_insight(
                    "period_change",
                    f"Billed {'up' if pct >= 0 else 'down'} {abs(pct):.1f}% {previous_label}",
                    f"{inr(totals['billed'])} now against {inr(previous['billed'])}.",
                    pct,
                    gainers,
                    losers,
                    short,
                )
            )
    elif mover_months and len(monthly) >= 2:
        last, prior = monthly[-1], monthly[-2]
        pct = _signed_pct(float(last["billed"]), float(prior["billed"]))
        if pct is not None:
            out.append(
                _change_insight(
                    "period_change",
                    f"{last['label']} billed {'up' if pct >= 0 else 'down'} {abs(pct):.1f}% on {prior['label']}",
                    f"{inr(float(last['billed']))} against {inr(float(prior['billed']))}.",
                    pct,
                    gainers,
                    losers,
                    short,
                )
            )

    # 3. Year on year, when the same period last year is in the data.
    if yoy is not None and yoy.get("invoices"):
        pct = _signed_pct(totals["billed"], yoy["billed"])
        if pct is not None:
            out.append(
                {
                    "id": "yoy",
                    "area": "trend",
                    "tone": "positive" if pct >= 0 else "negative",
                    "title": f"{abs(pct):.1f}% {'higher' if pct >= 0 else 'lower'} than {yoy_phrase}",
                    "detail": f"{inr(totals['billed'])} now against {inr(yoy['billed'])}.",
                }
            )

    # 3b. Documents with no amount. They are counted as documents, so say so.
    zero = int(totals.get("zero_docs") or 0)
    if zero:
        docs = int(totals["invoices"])
        net = totals["billed"]
        sized = docs - zero
        detail = (
            "These carry no amount (often cancelled or blank invoices in Tally) but are counted as documents, "
            "so the Documents figure and the average invoice include them."
        )
        if sized > 0:
            detail += f" Without them the average invoice is {inr(net / sized)}."
        out.append(
            {
                "id": "zero_value",
                "area": "trend",
                "tone": "warning",
                "title": f"{zero} of {docs} documents ({zero / docs * 100:.0f}%) have no value",
                "detail": detail,
            }
        )

    # 4. Concentration.
    if clients and totals.get("revenue"):
        revenue = totals["revenue"]
        top = clients[0]
        share = float(top["revenue"]) / revenue * 100 if revenue else 0.0
        top3 = sum(float(c["revenue"]) for c in clients[:3]) / revenue * 100 if revenue else 0.0
        flagged = share >= CONCENTRATION_FLAG_PCT
        out.append(
            {
                "id": "concentration",
                "area": "clients",
                "tone": "warning" if flagged else "neutral",
                "title": f"{short(top['code'])} is {share:.0f}% of revenue",
                "detail": (
                    f"The top 3 clients are {top3:.0f}% of revenue."
                    + (f" That is above the {CONCENTRATION_FLAG_PCT:.0f}% single-client watch level." if flagged else "")
                ),
                "action": {"key": "client", "value": top["code"]},
            }
        )

    # 5. A month far from the others.
    swing = None if month_selected else _swing(monthly)
    if swing:
        out.append(swing)

    # 6. Credit notes.
    if totals.get("cn_count"):
        credit = abs(totals["cn_billed"])
        sales = totals.get("sales_billed") or 0.0
        rate = credit / sales * 100 if sales else 0.0
        credit_rows = [row for row in notes if row.get("type") == "Credit note"]
        detail = f"{rate:.1f}% of sales invoiced."
        if credit_rows:
            biggest = max(credit_rows, key=lambda row: abs(float(row["billed"])))
            detail += f" Largest: {inr(abs(float(biggest['billed'])))} to {biggest['client']} on {day_label(biggest['date'])}."
        out.append(
            {
                "id": "credit_notes",
                "area": "notes",
                "tone": "warning",
                "title": f"{int(totals['cn_count'])} credit note{'s' if totals['cn_count'] != 1 else ''} worth {inr(credit)}",
                "detail": detail,
                "tab": "credit-notes",
            }
        )

    # 7. What the revenue is made of.
    groups = [g for g in income_groups if float(g["value"]) > 0]
    if len(groups) >= 2:
        total = sum(float(g["value"]) for g in groups)
        lead = max(groups, key=lambda g: float(g["value"]))
        out.append(
            {
                "id": "income_mix",
                "area": "income",
                "tone": "neutral",
                "title": f"{lead['label']} is {float(lead['value']) / total * 100:.0f}% of income",
                "detail": ", ".join(
                    f"{g['label']} {float(g['value']) / total * 100:.0f}%"
                    for g in sorted(groups, key=lambda g: float(g["value"]), reverse=True)
                ),
                "action": {"key": "income_line", "value": lead["code"]},
            }
        )

    return out[:MAX_INSIGHTS]


def _change_insight(insight_id, title, detail, pct, gainers, losers, short) -> dict[str, Any]:
    parts = []
    if gainers:
        parts.append("Biggest gain: " + ", ".join(f"{short(n)} {inr(v)}" for n, v in gainers[:2]))
    if losers:
        parts.append("Biggest fall: " + ", ".join(f"{short(n)} {inr(v)}" for n, v in losers[:2]))
    insight = {
        "id": insight_id,
        "area": "trend",
        "tone": "positive" if pct >= 0 else "negative",
        "title": title,
        "detail": " ".join([detail, *[p + "." for p in parts]]),
    }
    lead = (losers[:1] if pct < 0 else gainers[:1]) or gainers[:1] or losers[:1]
    if lead:
        insight["action"] = {"key": "client", "value": lead[0][0]}
    return insight


def _swing(monthly: list[dict[str, Any]]) -> dict[str, Any] | None:
    if len(monthly) < MIN_MONTHS_FOR_SWING:
        return None
    best: tuple[float, dict[str, Any], float] | None = None
    for point in monthly:
        others = [float(p["billed"]) for p in monthly if p is not point]
        average = sum(others) / len(others)
        value = float(point["billed"])
        if average <= 0 or value <= 0:
            continue
        ratio = value / average
        extremity = max(ratio, 1 / ratio)
        if extremity >= SWING_RATIO and (best is None or extremity > best[0]):
            best = (extremity, point, average)
    if not best:
        return None
    _extremity, point, average = best
    value = float(point["billed"])
    ratio = value / average
    return {
        "id": "swing",
        "area": "trend",
        "tone": "neutral",
        "title": (
            f"{point['label']} was {ratio:.1f}× the usual month"
            if ratio >= 1
            else f"{point['label']} was {1 / ratio:.1f}× below the usual month"
        ),
        "detail": (
            f"{inr(value)} billed against an average of {inr(average)} across the other "
            f"{len(monthly) - 1} months in view."
        ),
        "action": {"key": "month", "value": point["code"]},
    }
