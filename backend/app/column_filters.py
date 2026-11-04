"""Filters on the columns of a table, as the headers of the data tables offer them (a condition on a column, or a pick of its values).

The browser sends the filters as JSON in one query parameter (``f``); this module reads them, checks every part and turns them into a
``WHERE`` condition with parameters. Nothing from the request is ever put into the SQL text: a column must be one of the table's own
(its name goes into the SQL only through the caller's own expression for it), an operator must be one of ``OPS`` for the column's
kind, and every value reaches the database as a parameter, converted to the column's kind first.

The same rules are written for the browser in ``frontend/src/tables/columnFilter.ts`` (a test compares the operator lists), which also
applies them to the dashboards' tables that are already in the page.

A filter is ``{"column", "op", "value", "value2", "values", "empty"}``; one per column, all of them together (AND), and together with the
search box. ``values`` is a pick (``in``); ``empty`` adds the rows with nothing in the column to a pick.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from app.query import escape_like

MAX_FILTERS = 20
MAX_VALUES = 200
MAX_TEXT = 200
MAX_JSON = 20_000

# What can be asked of a column, by the kind of thing it holds. The first of each is the one the screen starts with.
OPS: dict[str, tuple[str, ...]] = {
    "text": ("contains", "not_contains", "equals", "not_equals", "starts", "ends", "in", "empty", "not_empty"),
    "number": ("eq", "ne", "gt", "gte", "lt", "lte", "between", "in", "empty", "not_empty"),
    "date": ("eq", "ne", "gt", "gte", "lt", "lte", "between", "empty", "not_empty"),
    "bool": ("in", "empty", "not_empty"),
}
NEEDS_VALUE = {"contains", "not_contains", "equals", "not_equals", "starts", "ends", "eq", "ne", "gt", "gte", "lt", "lte", "between"}

# Database type codes (psycopg2's cursor.description) of the numbers, dates and booleans; everything else is text.
_NUMBER = {20, 21, 23, 700, 701, 790, 1700}
_DATE = {1082, 1114, 1184}
_BOOL = {16}


class FilterError(ValueError):
    """The filters cannot be used. The message is safe to show to the user."""


def kind_of_type_code(code: int | None) -> str:
    if code in _NUMBER:
        return "number"
    if code in _DATE:
        return "date"
    if code in _BOOL:
        return "bool"
    return "text"


def kind_of_format(format_name: str) -> str:
    """The kind of a dashboard column from how it is shown."""
    return "number" if format_name in ("money", "number", "percent") else "text"


def parse(raw: str | None) -> list[dict[str, Any]]:
    """The filters of a request, shaped and size-checked. Which columns exist, and which operators suit them, is ``build``'s to check."""
    text = (raw or "").strip()
    if not text:
        return []
    if len(text) > MAX_JSON:
        raise FilterError("There are too many filters.")
    try:
        found = json.loads(text)
    except ValueError as exc:
        raise FilterError("The filters could not be read.") from exc
    if not isinstance(found, list) or len(found) > MAX_FILTERS:
        raise FilterError(f"Use at most {MAX_FILTERS} filters.")
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in found:
        if not isinstance(item, dict) or not isinstance(item.get("column"), str) or not isinstance(item.get("op"), str):
            raise FilterError("A filter is not written the way Orion writes them.")
        if item["column"] in seen:
            raise FilterError("A column can have one filter.")
        seen.add(item["column"])
        values = item.get("values")
        if values is not None and (not isinstance(values, list) or len(values) > MAX_VALUES or not all(isinstance(v, str) and len(v) <= MAX_TEXT for v in values)):
            raise FilterError(f"Pick at most {MAX_VALUES} values.")
        parts = {}
        for key in ("value", "value2"):
            value = item.get(key)
            if value is not None and (not isinstance(value, (str, int, float)) or len(str(value)) > MAX_TEXT):
                raise FilterError("A filter value is too long.")
            parts[key] = None if value is None else str(value)
        out.append({"column": item["column"], "op": item["op"], "value": parts["value"], "value2": parts["value2"],
                    "values": values, "empty": bool(item.get("empty"))})
    return out


def _number(value: str | None, label: str) -> Decimal:
    try:
        number = Decimal((value or "").replace(",", "").strip())
        if not number.is_finite():
            raise InvalidOperation
        return number
    except (InvalidOperation, ValueError):
        raise FilterError(f"{label} is not a number.") from None


def _day(value: str | None, label: str) -> date:
    try:
        return date.fromisoformat((value or "").strip()[:10])
    except ValueError:
        raise FilterError(f"{label} is not a date.") from None


def build(filters: list[dict[str, Any]], specs: Mapping[str, tuple[str, str]], skip: str | None = None) -> tuple[str, list[Any]]:
    """``(condition, params)`` for the filters, joined with AND ("" when there are none).

    ``specs`` maps a column's name to ``(sql expression for it, kind)``; the expression is the caller's own, never the request's.
    ``skip`` leaves one column's filter out (the list of values to pick from ignores the filter of the column it is listing).
    """
    clauses: list[str] = []
    params: list[Any] = []
    for flt in filters:
        column, op = flt["column"], flt["op"]
        if column not in specs:
            raise FilterError(f"There is no column called {column}.")
        if column == skip:
            continue
        expr, kind = specs[column]
        if op not in OPS[kind]:
            raise FilterError(f"{column} cannot be filtered that way.")
        text = f"COALESCE(({expr})::text, '')"
        blank = f"(({expr}) IS NULL OR {text} = '')"
        label = column.replace("_", " ")
        if op == "empty":
            clauses.append(blank)
        elif op == "not_empty":
            clauses.append(f"NOT {blank}")
        elif op == "in":
            values = flt["values"] or []
            if not values and not flt["empty"]:
                raise FilterError(f"Pick at least one value of {label}.")
            parts = []
            if values:
                parts.append(f"{text} = ANY(%s)")
                params.append(list(values))
            if flt["empty"]:
                parts.append(blank)
            clauses.append("(" + " OR ".join(parts) + ")")
        elif kind == "text":
            value = flt["value"] or ""
            if not value.strip():
                raise FilterError(f"Type something to filter {label} by.")
            if op in ("contains", "not_contains"):
                clauses.append(f"{'NOT ' if op == 'not_contains' else ''}{text} ILIKE %s ESCAPE '\\'")
                params.append(f"%{escape_like(value)}%")
            elif op in ("starts", "ends"):
                clauses.append(f"{text} ILIKE %s ESCAPE '\\'")
                params.append(f"{escape_like(value)}%" if op == "starts" else f"%{escape_like(value)}")
            else:
                clauses.append(f"lower({text}) {'=' if op == 'equals' else '<>'} lower(%s)")
                params.append(value)
        else:
            convert = _number if kind == "number" else _day
            target = f"({expr})" if kind == "number" else f"({expr})::date"
            low = convert(flt["value"], f"The value for {label}")
            if op == "between":
                high = convert(flt["value2"], f"The second value for {label}")
                if high < low:
                    low, high = high, low
                clauses.append(f"{target} BETWEEN %s AND %s")
                params += [low, high]
            elif op == "ne":
                clauses.append(f"{target} IS DISTINCT FROM %s")
                params.append(low)
            else:
                symbol = {"eq": "=", "gt": ">", "gte": ">=", "lt": "<", "lte": "<="}[op]
                clauses.append(f"{target} {symbol} %s")
                params.append(low)
    return " AND ".join(clauses), params
