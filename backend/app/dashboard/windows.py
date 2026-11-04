"""Period windows shared by the Orion and Tally dashboards.

Pure: nothing here touches the database. A selection (month, financial year, or from/to) becomes a date
window, and from that window the previous period and the same period last year, but only where the data
covers them.
"""

from __future__ import annotations

import re
from calendar import monthrange
from datetime import date, datetime, timedelta
from typing import Any

from app.dashboard.filters import month_label

_MONTH = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
_YEAR = re.compile(r"^\d{4}$")


def parse_day(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def fy_label(start_year: int) -> str:
    return f"FY {start_year}-{str(start_year + 1)[2:]}"


def fy_start_year(day: date) -> int:
    """The year a financial year (April to March) starts in, for a day inside it."""
    return day.year if day.month >= 4 else day.year - 1


#: What a screen sends for "the financial year we are in" and for "every year". Neither is a year, so each is
#: replaced before the filters are checked: the first by the year itself, the second by no financial-year filter.
THIS_FY = "current"
ALL_YEARS = "all"


def resolve_fy(raw: dict[str, Any], hi: date | None, today: date | None = None) -> dict[str, Any]:
    """Replace ``fy=current`` by the current financial year and drop ``fy=all``.

    The current year is the one the later of today and the newest data falls in, but never past today, so a dashboard
    opened in April, before the new year has any bills, still shows the year that has data in it.
    """
    out = dict(raw)
    value = str(out.get("fy") or "").strip().lower()
    if value == ALL_YEARS:
        out.pop("fy")
    elif value == THIS_FY:
        today = today or date.today()
        out["fy"] = str(fy_start_year(min(today, hi) if hi else today))
    return out


# --------------------------------------------------------------------------- filters


def validate_filters(filters: dict[str, str]) -> tuple[dict[str, str], list[dict[str, str]]]:
    """Drop values the queries cannot use and say what was dropped.

    A reversed date range is swapped rather than dropped, because the intent is clear.
    """
    clean = dict(filters)
    problems: list[dict[str, str]] = []

    month = clean.get("month")
    if month and not _MONTH.match(month):
        clean.pop("month")
        problems.append({"key": "month", "value": month, "reason": "Expected a month like 2026-07."})

    fy = clean.get("fy")
    if fy and not _YEAR.match(str(fy).strip()[:4]):
        clean.pop("fy")
        problems.append({"key": "fy", "value": fy, "reason": "Expected a financial year like 2025."})

    for key in ("from", "to"):
        raw = clean.get(key)
        if raw and parse_day(raw) is None:
            clean.pop(key)
            problems.append({"key": key, "value": raw, "reason": "Expected a date like 2026-04-01."})

    start, end = parse_day(clean.get("from")), parse_day(clean.get("to"))
    if start and end and start > end:
        clean["from"], clean["to"] = end.isoformat(), start.isoformat()
        problems.append(
            {"key": "from", "value": f"{start} > {end}", "reason": "The dates were reversed, so they were swapped."}
        )
    return clean, problems


# --------------------------------------------------------------------------- windows


def _shift_year(day: date, years: int) -> date:
    try:
        return day.replace(year=day.year + years)
    except ValueError:  # 29 Feb
        return day.replace(year=day.year + years, day=28)


def _window_filters(filters: dict[str, str], start: date, end: date) -> dict[str, str]:
    out = {k: v for k, v in filters.items() if k not in ("month", "fy", "from", "to")}
    out["from"], out["to"] = start.isoformat(), end.isoformat()
    return out


def selected_window(
    filters: dict[str, str], lo: date | None, hi: date | None
) -> tuple[date, date, str] | None:
    """The date span the filters select, and its kind: month, fy, or range.

    No window (all time) means there is nothing meaningful to compare against.
    """
    if not lo or not hi:
        return None
    month = filters.get("month")
    if month:
        year, mon = int(month[:4]), int(month[5:7])
        return date(year, mon, 1), date(year, mon, monthrange(year, mon)[1]), "month"

    start, end = lo, hi
    constrained = False
    fy = filters.get("fy")
    if fy:
        year = int(str(fy)[:4])
        start, end = max(start, date(year, 4, 1)), min(end, date(year + 1, 3, 31))
        constrained = True
    first, last = parse_day(filters.get("from")), parse_day(filters.get("to"))
    if first:
        start, constrained = max(start, first), True
    if last:
        end, constrained = min(end, last), True
    if not constrained or start > end:
        return None
    return start, end, "fy" if fy and not first and not last else "range"


def comparison_windows(
    filters: dict[str, str], lo: date | None, hi: date | None
) -> dict[str, dict[str, Any] | None]:
    """Previous-period and same-period-last-year windows, only where the data covers them.

    A financial year also gets ``full``: the whole of the year before, for a year still in progress. ``previous`` is then
    the same stretch of the year before (the same months up to the same point), so a year in progress can be set against
    the year before at the same time, or against all of it."""
    window = selected_window(filters, lo, hi)
    result: dict[str, dict[str, Any] | None] = {"previous": None, "yoy": None, "full": None}
    if not window or not lo:
        return result
    start, end, kind = window

    def covered(a: date) -> bool:
        return a >= lo

    partial_end = None
    if kind == "month":
        # A month billed only part-way compares with the same days of the earlier month and year.
        if hi and hi < end:
            partial_end, end = end, hi
        month_end = start - timedelta(days=1)
        prev_start = month_end.replace(day=1)
        prev_end = min(month_end, prev_start + timedelta(days=(end - start).days))
        if covered(prev_start):
            name = month_label(prev_start.strftime("%Y-%m"))
            result["previous"] = {
                "filters": _window_filters(filters, prev_start, prev_end),
                "label": f"vs {prev_start.day}–{prev_end.day} {name}" if partial_end else f"vs {name}",
                "like_for_like": bool(partial_end),
            }
    elif kind == "fy":
        year = int(str(filters["fy"])[:4])
        prior_start, prior_end = _shift_year(start, -1), _shift_year(end, -1)
        name = fy_label(year - 1)
        if covered(prior_start):
            result["previous"] = {
                "filters": _window_filters(filters, prior_start, prior_end),
                "label": f"vs {name}, same period",
            }
            whole_end = date(year, 3, 31)
            if whole_end > prior_end:
                result["full"] = {
                    "filters": _window_filters(filters, prior_start, whole_end),
                    "label": f"vs full {name}",
                }
        return result  # previous period and last year are the same thing here
    else:
        span = (end - start).days + 1
        prev_end = start - timedelta(days=1)
        prev_start = prev_end - timedelta(days=span - 1)
        if covered(prev_start):
            result["previous"] = {
                "filters": _window_filters(filters, prev_start, prev_end),
                "label": f"vs prior {span} days",
            }

    yoy_start, yoy_end = _shift_year(start, -1), _shift_year(end, -1)
    if covered(yoy_start):
        result["yoy"] = {
            "filters": _window_filters(filters, yoy_start, yoy_end),
            "label": "vs same days last year" if partial_end else "vs same period last year",
            "like_for_like": bool(partial_end),
        }
    return result


# --------------------------------------------------------------------------- movers


def top_movers(current: dict[str, float], previous: dict[str, float], limit: int = 3):
    """Clients whose revenue changed most between two windows, largest gain and loss first."""
    changes = [(name, current.get(name, 0.0) - previous.get(name, 0.0)) for name in set(current) | set(previous)]
    gainers = sorted((c for c in changes if c[1] > 0.5), key=lambda c: c[1], reverse=True)[:limit]
    losers = sorted((c for c in changes if c[1] < -0.5), key=lambda c: c[1])[:limit]
    return gainers, losers
