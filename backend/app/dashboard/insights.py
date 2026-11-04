"""Findings for the Orion dashboards, worked out from the figures the dashboards already show.

Nothing here touches the database: ``engine`` runs the queries and hands the results in, so every rule below can be
tested on plain numbers. The only judgement calls are the named thresholds below, and each is quoted in the
insight text that depends on it. An insight is skipped, not guessed, when the input it needs is missing.

Each insight has an ``area`` (the dashboard tab that shows it), a ``tone``, a title and a detail, and optionally an
``action``: a filter it points at, or a ``tab`` that explains it.
"""

from __future__ import annotations

from typing import Any

from app.dashboard.filters import inr

# Share of revenue from one client above which concentration is flagged.
CONCENTRATION_FLAG_PCT = 25.0
# Cash collected as a share of billed, below which collection is called slow.
COLLECTION_FLAG_PCT = 90.0
# Share of what is owed that is over 90 days old, above which it is flagged.
OVERDUE_FLAG_PCT = 25.0
# Days of billing tied up in unpaid bills, above which it is flagged.
DSO_FLAG_DAYS = 60.0
# A margin this many points below the previous period is called out.
MARGIN_DROP_POINTS = 1.0
# Annual attrition above this share of headcount is flagged.
ATTRITION_FLAG_PCT = 25.0
# An open opportunity this many days old is called stale.
STALE_DAYS = 90
# A month this many times the average of the others is called out.
SWING_RATIO = 1.8
MIN_MONTHS_FOR_SWING = 6
# A case billing this far under its expected monthly revenue is under-billing.
UNDERBILL_FLAG_PCT = 10.0
MAX_INSIGHTS = 24


def _pct(part: float, whole: float) -> float:
    return part / whole * 100 if whole else 0.0


def _signed_pct(current: float, previous: float) -> float | None:
    if not previous:
        return None
    return (current - previous) / abs(previous) * 100


def _short(name: str, limit: int = 30) -> str:
    text = " ".join((name or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _item(insight_id: str, area: str, tone: str, title: str, detail: str, **extra: Any) -> dict[str, Any]:
    return {"id": insight_id, "area": area, "tone": tone, "title": title, "detail": detail, **extra}


def build_insights(f: dict[str, Any]) -> list[dict[str, Any]]:
    """``f`` is the bundle of figures ``engine`` collected. Missing keys simply skip that insight."""
    out: list[dict[str, Any]] = []
    totals: dict[str, float] = f.get("totals") or {}
    if not totals or not (totals.get("bills") or totals.get("payroll") or totals.get("expenses")):
        return out
    previous = f.get("previous")
    prev_label = f.get("previous_label") or "the earlier period"
    yoy = f.get("yoy")
    yoy_phrase = f.get("yoy_phrase") or "the same period last year"
    monthly: list[dict[str, Any]] = f.get("monthly") or []

    # ---- the period against the one before --------------------------------------------------------------------
    if previous and previous.get("revenue"):
        pct = _signed_pct(totals["revenue"], previous["revenue"])
        if pct is not None:
            detail = f"{inr(totals['revenue'])} now against {inr(previous['revenue'])}."
            gain, loss = f.get("gainers") or [], f.get("losers") or []
            if gain:
                detail += " Biggest gain: " + ", ".join(f"{_short(n)} {inr(v)}" for n, v, *_ in gain[:2]) + "."
            if loss:
                detail += " Biggest fall: " + ", ".join(f"{_short(n)} {inr(v)}" for n, v, *_ in loss[:2]) + "."
            lead = (loss[:1] if pct < 0 else gain[:1]) or gain[:1] or loss[:1]
            extra = {"action": {"key": "client", "value": lead[0][2]}} if lead and len(lead[0]) > 2 else {}
            out.append(
                _item(
                    "revenue_change",
                    "overview",
                    "positive" if pct >= 0 else "negative",
                    f"Revenue {'up' if pct >= 0 else 'down'} {abs(pct):.1f}% {prev_label}",
                    detail,
                    **extra,
                )
            )
    if yoy and yoy.get("revenue"):
        pct = _signed_pct(totals["revenue"], yoy["revenue"])
        if pct is not None:
            out.append(
                _item(
                    "revenue_yoy",
                    "revenue",
                    "positive" if pct >= 0 else "negative",
                    f"Revenue is {abs(pct):.1f}% {'higher' if pct >= 0 else 'lower'} than {yoy_phrase}",
                    f"{inr(totals['revenue'])} now against {inr(yoy['revenue'])}.",
                )
            )

    # ---- margin -----------------------------------------------------------------------------------------------
    if totals.get("revenue"):
        margin_pct = totals.get("margin_pct", 0.0)
        if previous and previous.get("revenue"):
            drift = margin_pct - previous.get("margin_pct", 0.0)
            if abs(drift) >= MARGIN_DROP_POINTS:
                out.append(
                    _item(
                        "margin_shift",
                        "profitability",
                        "positive" if drift > 0 else "negative",
                        f"Margin {'widened' if drift > 0 else 'narrowed'} by {abs(drift):.1f} points {prev_label}",
                        f"{margin_pct:.1f}% of revenue now ({inr(totals['margin'])}), against "
                        f"{previous.get('margin_pct', 0.0):.1f}%. Payroll is {totals.get('payroll_pct', 0.0):.0f}% of "
                        f"revenue and running costs {totals.get('expense_pct', 0.0):.0f}%.",
                    )
                )
        if totals["margin"] < 0:
            out.append(
                _item(
                    "margin_negative",
                    "overview",
                    "negative",
                    f"Delivery cost exceeds revenue by {inr(-totals['margin'])}",
                    "Payroll and running costs together are above what was billed in this selection.",
                    tab="profitability",
                )
            )

    losers = f.get("loss_cases") or []
    if losers:
        drag = sum(float(c["margin"]) for c in losers)
        worst = min(losers, key=lambda c: float(c["margin"]))
        out.append(
            _item(
                "loss_cases",
                "profitability",
                "warning",
                f"{len(losers)} case{'s' if len(losers) != 1 else ''} cost more than they bill",
                f"Together they lose {inr(-drag)}. Largest: {_short(worst['label'])} at {inr(float(worst['margin']))}.",
                action={"key": "case", "value": worst["code"]},
            )
        )

    domains = [d for d in (f.get("domains") or []) if float(d.get("revenue") or 0) > 0]
    if len(domains) >= 2:
        best = max(domains, key=lambda d: float(d["margin_pct"]))
        worst = min(domains, key=lambda d: float(d["margin_pct"]))
        if float(best["margin_pct"]) - float(worst["margin_pct"]) >= 5:
            out.append(
                _item(
                    "domain_spread",
                    "profitability",
                    "neutral",
                    f"{_short(best['label'])} earns {float(best['margin_pct']):.0f}% margin, {_short(worst['label'])} "
                    f"{float(worst['margin_pct']):.0f}%",
                    "Margin by business domain on the current selection. Click a domain on the page to focus it.",
                    action={"key": "business_domain", "value": worst["code"]},
                )
            )

    # ---- concentration ----------------------------------------------------------------------------------------
    clients = f.get("clients") or []
    revenue = totals.get("revenue", 0.0)
    if clients and revenue:
        top = clients[0]
        share = float(top["value"]) / revenue * 100
        top3 = sum(float(c["value"]) for c in clients[:3]) / revenue * 100
        flagged = share >= CONCENTRATION_FLAG_PCT
        out.append(
            _item(
                "concentration",
                "revenue",
                "warning" if flagged else "neutral",
                f"{_short(top['label'])} is {share:.0f}% of revenue",
                f"The top 3 clients are {top3:.0f}% of revenue."
                + (f" That is above the {CONCENTRATION_FLAG_PCT:.0f}% single-client watch level." if flagged else ""),
                action={"key": "client", "value": top["code"]},
            )
        )

    new_share = f.get("new_client_share")
    if new_share and revenue:
        out.append(
            _item(
                "new_clients",
                "revenue",
                "positive" if new_share >= 10 else "neutral",
                f"{new_share:.0f}% of revenue comes from clients billed for the first time in the last 12 months",
                "Clients are counted from their first bill in the warehouse.",
            )
        )

    under = f.get("underbilled")
    if under and under.get("count"):
        worst = under["worst"]
        out.append(
            _item(
                "underbilled",
                "revenue",
                "warning",
                f"{under['count']} case{'s' if under['count'] != 1 else ''} billed below what the contract expects",
                f"A monthly gap of {inr(under['gap'])} against expected revenue (more than {UNDERBILL_FLAG_PCT:.0f}% "
                f"short). Largest: {_short(worst['label'])}, {inr(worst['gap'])} a month.",
                action={"key": "case", "value": worst["code"]},
            )
        )

    # ---- collections ------------------------------------------------------------------------------------------
    snap = f.get("snapshot") or {}
    outstanding = snap.get("outstanding", 0.0)
    if outstanding > 0:
        over90 = snap.get("over90", 0.0)
        share = _pct(over90, outstanding)
        flagged = share >= OVERDUE_FLAG_PCT
        detail = f"{inr(outstanding)} is outstanding on {int(snap.get('open_bills', 0))} bills; {share:.0f}% of it is more than 90 days old."
        worst_client = snap.get("worst_client")
        if worst_client:
            detail += f" Largest balance: {_short(worst_client['label'])}, {inr(worst_client['value'])}."
        out.append(
            _item(
                "overdue",
                "collections",
                "negative" if flagged else "neutral",
                f"{inr(over90)} is more than 90 days overdue" if over90 else f"{inr(outstanding)} outstanding, none over 90 days",
                detail
                + (f" That is above the {OVERDUE_FLAG_PCT:.0f}% watch level." if flagged else ""),
                action={"key": "bucket", "value": "90+"} if over90 else None,
            )
        )
        dso = snap.get("dso")
        if dso:
            out.append(
                _item(
                    "dso",
                    "collections",
                    "warning" if dso >= DSO_FLAG_DAYS else "neutral",
                    f"{dso:.0f} days of billing are tied up in unpaid bills",
                    "Outstanding divided by the last 90 days of billing."
                    + (f" Above the {DSO_FLAG_DAYS:.0f}-day watch level." if dso >= DSO_FLAG_DAYS else ""),
                )
            )
    rate = totals.get("collection_rate")
    if rate is not None and totals.get("billed"):
        out.append(
            _item(
                "collection_rate",
                "collections",
                "warning" if rate < COLLECTION_FLAG_PCT else "positive",
                f"Collected {rate:.0f}% of what was billed in this period",
                f"{inr(totals.get('settled', totals.get('collected', 0.0)))} settled ({inr(totals.get('collected', 0.0))} in the bank"
                + (f" and {inr(totals['tds_held'])} held back by clients" if totals.get("tds_held") else "")
                + f") against {inr(totals['billed'])} billed."
                + (" Bills are building up faster than they are paid." if rate < COLLECTION_FLAG_PCT else ""),
            )
        )
    slow = f.get("slow_payer")
    if slow:
        out.append(
            _item(
                "slow_payer",
                "collections",
                "warning",
                f"{_short(slow['label'])} takes {slow['days']:.0f} days to pay",
                f"The slowest of the clients with paid bills; the average across clients is {slow['average']:.0f} days.",
                action={"key": "client", "value": slow["code"]},
            )
        )

    # ---- people -----------------------------------------------------------------------------------------------
    ppl = f.get("people") or {}
    if ppl.get("attrition") is not None and ppl.get("leavers") is not None:
        attr = ppl["attrition"]
        out.append(
            _item(
                "attrition",
                "people",
                "warning" if attr >= ATTRITION_FLAG_PCT else "neutral",
                f"{int(ppl['leavers'])} people left; attrition runs at {attr:.0f}% a year",
                f"{int(ppl.get('joiners', 0))} joined in the same period. Headcount is {int(ppl.get('headcount', 0))} now."
                + (f" Above the {ATTRITION_FLAG_PCT:.0f}% watch level." if attr >= ATTRITION_FLAG_PCT else ""),
            )
        )
    if totals.get("salary_pending"):
        out.append(
            _item(
                "salary_pending",
                "people",
                "warning",
                f"{inr(totals['salary_pending'])} of salary is not yet marked paid",
                "Payroll lines in this selection with the salary-paid flag off.",
                action={"key": "salary_paid", "value": "No"},
            )
        )
    if previous and previous.get("payroll_pct") and totals.get("payroll_pct"):
        shift = totals["payroll_pct"] - previous["payroll_pct"]
        if abs(shift) >= 2:
            out.append(
                _item(
                    "payroll_share",
                    "people",
                    "negative" if shift > 0 else "positive",
                    f"Payroll is {totals['payroll_pct']:.0f}% of revenue, {'up' if shift > 0 else 'down'} "
                    f"{abs(shift):.1f} points {prev_label}",
                    "Salary cost relative to what is billed.",
                )
            )

    # ---- pipeline ---------------------------------------------------------------------------------------------
    pipe = f.get("pipeline") or {}
    if pipe.get("decided"):
        out.append(
            _item(
                "win_rate",
                "pipeline",
                "positive" if pipe["win_rate"] >= 30 else "neutral",
                f"Won {pipe['win_rate']:.0f}% of the tenders that were decided",
                f"{int(pipe.get('won', 0))} won out of {int(pipe['decided'])} decided; {int(pipe.get('open', 0))} still open.",
            )
        )
    if pipe.get("stale"):
        out.append(
            _item(
                "stale_pipeline",
                "pipeline",
                "warning",
                f"{int(pipe['stale'])} open opportunit{'ies are' if pipe['stale'] != 1 else 'y is'} more than {STALE_DAYS} days old",
                "No stage change or close date recorded since. Close them out or move them on.",
            )
        )
    if pipe.get("top_loss"):
        out.append(
            _item(
                "loss_reason",
                "pipeline",
                "neutral",
                f"Most common reason for losing: {pipe['top_loss']['label']}",
                f"{int(pipe['top_loss']['value'])} lost or disqualified opportunities gave this reason.",
            )
        )

    # ---- fleet ------------------------------------------------------------------------------------------------
    fleet = f.get("fleet") or {}
    if fleet.get("over_allowance"):
        worst = fleet["over_allowance"][0]
        out.append(
            _item(
                "km_allowance",
                "fleet",
                "warning",
                f"{len(fleet['over_allowance'])} case{'s' if len(fleet['over_allowance']) != 1 else ''} drove past their km allowance",
                f"Worst: {_short(worst['label'])}, {worst['pct']:.0f}% of the monthly allowance.",
                action={"key": "case", "value": worst["code"]},
            )
        )

    # ---- controls ---------------------------------------------------------------------------------------------
    ctl = f.get("controls") or {}
    if ctl.get("cancelled"):
        out.append(
            _item(
                "cancelled",
                "controls",
                "warning",
                f"{int(ctl['cancelled'])} bill{'s were' if ctl['cancelled'] != 1 else ' was'} cancelled, worth {inr(ctl['cancelled_value'])}",
                "Cancelled bills keep their numbers. Each one is a bill that was raised and withdrawn.",
                action={"key": "status", "value": "Cancelled"},
            )
        )
    if ctl.get("edited"):
        out.append(
            _item(
                "edited",
                "controls",
                "neutral",
                f"{int(ctl['edited'])} issued bill{'s were' if ctl['edited'] != 1 else ' was'} edited after issue",
                f"That is {_pct(ctl['edited'], max(totals.get('bills', 0), 1)):.1f}% of the bills raised. Every earlier version is kept on the bill.",
            )
        )
    if ctl.get("gst_unpaid"):
        out.append(
            _item(
                "gst_unpaid",
                "controls",
                "warning",
                f"{inr(ctl['gst_unpaid'])} of GST has not been marked as paid",
                "GST on issued bills whose GST-paid flag is off. Check these before the next return.",
            )
        )
    if ctl.get("epf_unpaid") or ctl.get("esic_unpaid"):
        parts = [f"{inr(ctl[key])} of {label}" for key, label in (("epf_unpaid", "EPFO"), ("esic_unpaid", "ESIC")) if ctl.get(key)]
        out.append(
            _item(
                "statutory_unpaid",
                "controls",
                "warning",
                f"{' and '.join(parts)} charged on bills has not been marked as paid",
                "What the bills charged clients for EPFO and ESIC, not yet shown as paid to the authority. Check these before the due dates.",
            )
        )
    unbilled = f.get("unbilled") or {}
    if unbilled.get("count"):
        names = ", ".join(_short(n, 24) for n in unbilled.get("names", [])[:3])
        out.append(
            _item(
                "unbilled",
                "controls",
                "warning",
                f"{unbilled['count']} active case{'s have' if unbilled['count'] != 1 else ' has'} no bill yet for {unbilled['month']}",
                (f"{names}. " if names else "") + "They were billed the month before.",
                tab="revenue",
            )
        )

    # ---- the shape of the months ------------------------------------------------------------------------------
    partial = f.get("partial_month")
    if partial:
        out.append(
            _item(
                "partial_month",
                "overview",
                "warning",
                f"{partial} is still in progress",
                "Cash collected for the month so far is shown, but its bills and payroll are not complete, so "
                "month-on-month comparisons with it understate it.",
            )
        )
    swing = None if f.get("month_selected") else _swing(monthly)
    if swing:
        out.append(swing)

    seen: set[str] = set()
    unique = []
    for item in out:
        if item["id"] in seen:
            continue
        seen.add(item["id"])
        if item.get("action") is None:
            item.pop("action", None)
        unique.append(item)
    return unique[:MAX_INSIGHTS]


def _swing(monthly: list[dict[str, Any]]) -> dict[str, Any] | None:
    if len(monthly) < MIN_MONTHS_FOR_SWING:
        return None
    best: tuple[float, dict[str, Any], float] | None = None
    for point in monthly:
        others = [float(p["revenue"]) for p in monthly if p is not point]
        average = sum(others) / len(others)
        value = float(point["revenue"])
        if average <= 0 or value <= 0:
            continue
        ratio = value / average
        extremity = max(ratio, 1 / ratio)
        if extremity >= SWING_RATIO and (best is None or extremity > best[0]):
            best = (extremity, point, average)
    if not best:
        return None
    _extremity, point, average = best
    value = float(point["revenue"])
    ratio = value / average
    return _item(
        "swing",
        "revenue",
        "neutral",
        f"{point['label']} was {ratio:.1f}× the usual month" if ratio >= 1 else f"{point['label']} was {1 / ratio:.1f}× below the usual month",
        f"{inr(value)} of revenue against an average of {inr(average)} across the other {len(monthly) - 1} months in view.",
        action={"key": "month", "value": point["code"]},
    )
