"""Turning "last month" or "this quarter" into exact dates, on the server.

The model is never asked to work out a date range. It names a preset (``last_month``) or gives explicit dates, and this
module decides what that means: the Indian financial year starts on 1 April, quarters follow it, and "this month" is the
month so far. The same window is used for the dashboards, so an answer and the page it came from agree.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

PRESETS = (
    "this_month", "last_month", "this_quarter", "last_quarter", "this_fy", "last_fy", "this_year", "last_year",
    "last_7_days", "last_30_days", "last_90_days", "last_12_months", "all_time",
)


@dataclass(frozen=True)
class Window:
    start: Optional[date]
    end: Optional[date]
    label: str
    preset: str = ""

    @property
    def filters(self) -> dict[str, str]:
        out: dict[str, str] = {}
        if self.start:
            out["from"] = self.start.isoformat()
        if self.end:
            out["to"] = self.end.isoformat()
        return out

    @property
    def days(self) -> int:
        return ((self.end or date.today()) - self.start).days + 1 if self.start else 0


def _month_end(year: int, month: int) -> date:
    return date(year, month, calendar.monthrange(year, month)[1])


def _add_months(day: date, months: int) -> date:
    index = day.year * 12 + (day.month - 1) + months
    return date(index // 12, index % 12 + 1, 1)


def fy_start(day: date) -> date:
    return date(day.year if day.month >= 4 else day.year - 1, 4, 1)


def fy_name(start: date) -> str:
    return f"FY {start.year}-{str(start.year + 1)[2:]}"


def quarter_start(day: date) -> date:
    first = fy_start(day)
    months = (day.year - first.year) * 12 + day.month - first.month
    return _add_months(first, (months // 3) * 3)


def _month_name(day: date) -> str:
    return day.strftime("%B %Y")


def resolve(preset: str | None, start: str | None, end: str | None, today: date | None = None) -> Window:
    """A window from explicit ISO dates if given, otherwise from a preset. Raises ValueError for anything unusable."""
    today = today or date.today()
    if start or end:
        first = date.fromisoformat(start) if start else None
        last = date.fromisoformat(end) if end else None
        if first and last and first > last:
            first, last = last, first
        if (first and not 1990 <= first.year <= 2100) or (last and not 1990 <= last.year <= 2100):
            raise ValueError("Dates must be between 1990 and 2100.")
        if first and last and first.day == 1 and last == _month_end(first.year, first.month):
            label = _month_name(first)
        else:
            label = f"{first.strftime('%d %b %Y') if first else 'the start'} to {last.strftime('%d %b %Y') if last else 'today'}"
        return Window(first, last, label, "custom")

    name = (preset or "all_time").strip().lower()
    if name == "all_time":
        return Window(None, None, "all time", name)
    if name == "this_month":
        return Window(today.replace(day=1), _month_end(today.year, today.month), f"{_month_name(today)} (so far)" if today.day < _month_end(today.year, today.month).day else _month_name(today), name)
    if name == "last_month":
        first = _add_months(today.replace(day=1), -1)
        return Window(first, _month_end(first.year, first.month), _month_name(first), name)
    if name == "this_quarter":
        first = quarter_start(today)
        last = _month_end(_add_months(first, 2).year, _add_months(first, 2).month)
        return Window(first, last, _quarter_label(first), name)
    if name == "last_quarter":
        first = _add_months(quarter_start(today), -3)
        last = _month_end(_add_months(first, 2).year, _add_months(first, 2).month)
        return Window(first, last, _quarter_label(first), name)
    if name == "this_fy":
        first = fy_start(today)
        return Window(first, date(first.year + 1, 3, 31), fy_name(first), name)
    if name == "last_fy":
        first = date(fy_start(today).year - 1, 4, 1)
        return Window(first, date(first.year + 1, 3, 31), fy_name(first), name)
    if name == "this_year":
        return Window(date(today.year, 1, 1), date(today.year, 12, 31), str(today.year), name)
    if name == "last_year":
        return Window(date(today.year - 1, 1, 1), date(today.year - 1, 12, 31), str(today.year - 1), name)
    if name in ("last_7_days", "last_30_days", "last_90_days"):
        days = int(name.split("_")[1])
        return Window(today - timedelta(days=days - 1), today, f"the last {days} days", name)
    if name == "last_12_months":
        return Window(_add_months(today.replace(day=1), -11), _month_end(today.year, today.month), "the last 12 months", name)
    raise ValueError(f"Unknown period '{preset}'. Use one of: {', '.join(PRESETS)}, or give from and to dates.")


def _quarter_label(first: date) -> str:
    fy = fy_start(first)
    number = ((first.year - fy.year) * 12 + first.month - fy.month) // 3 + 1
    return f"Q{number} {fy_name(fy)}"


def previous(window: Window) -> Window:
    """The stretch of the same length just before ``window`` (or the previous month/quarter/year for a preset)."""
    if not window.start or not window.end:
        raise ValueError("There is no earlier period to compare with.")
    start, end = window.start, window.end
    if window.preset in ("this_month", "last_month"):
        first = _add_months(start.replace(day=1), -1)
        return Window(first, _month_end(first.year, first.month), _month_name(first), "last_month" if window.preset == "this_month" else "")
    if window.preset in ("this_quarter", "last_quarter"):
        first = _add_months(quarter_start(start), -3)
        return Window(first, _month_end(_add_months(first, 2).year, _add_months(first, 2).month), _quarter_label(first))
    if window.preset in ("this_fy", "last_fy"):
        first = date(start.year - 1, 4, 1)
        return Window(first, date(first.year + 1, 3, 31), fy_name(first))
    if window.preset in ("this_year", "last_year"):
        return Window(date(start.year - 1, 1, 1), date(start.year - 1, 12, 31), str(start.year - 1))
    span = (end - start).days + 1
    prev_end = start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=span - 1)
    return Window(prev_start, prev_end, f"the {span} days before", "")


def months_in(window: Window, today: date | None = None) -> int:
    today = today or date.today()
    if not window.start:
        return 0
    end = window.end or today
    return (end.year - window.start.year) * 12 + end.month - window.start.month + 1
