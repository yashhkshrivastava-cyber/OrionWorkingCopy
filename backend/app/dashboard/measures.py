"""Reusable aggregate shapes: categories, monthly series, and grids.

Views describe what they want in terms of a scope, a dimension, and a value
expression. These helpers apply the filter engine, exclude the dimension being
plotted, and return the three payload shapes the frontend understands.
"""

from __future__ import annotations

from typing import Any, Sequence

from app.dashboard.filters import clause, month_label, num, rows, SCOPES

MONEY = "COALESCE(SUM({column}), 0)"


def category(
    cur,
    *,
    scope: str,
    filters: dict[str, str],
    dimension: str,
    code: str,
    value: str,
    label: str | None = None,
    joins: str = "",
    having: str | None = None,
    limit: int | None = None,
    order: str = "value DESC",
    include_cancelled: bool = False,
    order_by_list: Sequence[str] | None = None,
    month_labels: bool = False,
    extra: Sequence[str] = (),
) -> list[dict[str, Any]]:
    """One row per category value, shaped for a bar, donut, or funnel."""
    where, params = clause(
        scope, filters, exclude=(dimension,), include_cancelled=include_cancelled, extra=extra
    )
    sql = (
        f"SELECT {code} AS code, {label or code} AS label, {value} AS value"
        f" FROM {SCOPES[scope]['from']}{joins}{where}"
        f" GROUP BY 1, 2"
    )
    if having:
        sql += f" HAVING {having}"
    sql += f" ORDER BY {order}"
    if limit:
        sql += f" LIMIT {limit}"

    def display(row: tuple) -> str:
        if month_labels:
            return month_label(str(row[0]))
        return str(row[1]) if row[1] not in (None, "") else str(row[0])

    items = [
        {"code": str(row[0]), "label": display(row), "value": round(num(row[2]), 2)}
        for row in rows(cur, sql, params)
        if row[0] is not None
    ]

    if order_by_list:
        rank = {value: index for index, value in enumerate(order_by_list)}
        items.sort(key=lambda item: rank.get(item["code"], len(rank)))
    return items


class Series(dict):
    """Monthly totals that remember which metrics were asked for.

    Carrying the names matters when a fact has no rows for the current
    selection: the months are absent but the metrics still have to appear as
    zero, otherwise anything deriving a ratio from them breaks.
    """

    def __init__(self, metrics: Sequence[str], data: dict[str, dict[str, float]]):
        super().__init__(data)
        self.metrics = tuple(metrics)


def month_series(
    cur,
    *,
    scope: str,
    filters: dict[str, str],
    metrics: dict[str, str],
    include_cancelled: bool = False,
    extra: Sequence[str] = (),
) -> Series:
    """Monthly totals keyed by YYYY-MM. The month selection is never applied."""
    month_field = SCOPES[scope]["fields"]["month"]
    where, params = clause(
        scope, filters, exclude=("month",), include_cancelled=include_cancelled, extra=extra
    )
    selected = ", ".join(f"{expr}" for expr in metrics.values())
    sql = (
        f"SELECT {month_field} AS m, {selected}"
        f" FROM {SCOPES[scope]['from']}{where}"
        f" GROUP BY 1 ORDER BY 1"
    )
    names = list(metrics)
    return Series(
        names,
        {
            str(row[0]): {name: num(row[index + 1]) for index, name in enumerate(names)}
            for row in rows(cur, sql, params)
            if row[0]
        },
    )


def merge_months(*sources: dict[str, dict[str, float]], derive=None) -> list[dict[str, Any]]:
    """Align several monthly series onto one axis, oldest first, zero filling."""
    months = sorted({month for source in sources for month in source})
    metric_names = [
        getattr(source, "metrics", None)
        or sorted({name for values in source.values() for name in values})
        for source in sources
    ]
    points: list[dict[str, Any]] = []
    for month in months:
        point: dict[str, Any] = {"code": month, "label": month_label(month)}
        for source, names in zip(sources, metric_names):
            values = source.get(month, {})
            for name in names:
                point[name] = round(num(values.get(name)), 2)
        if derive:
            point.update(derive(point))
        points.append(point)
    return points


def grid(
    columns: Sequence[dict[str, Any]],
    records: Sequence[dict[str, Any]],
    *,
    filter_key: str | None = None,
) -> dict[str, Any]:
    """A table block. ``filter_key`` makes each row clickable as a filter."""
    return {"filter_key": filter_key, "columns": list(columns), "rows": list(records)}


def column(key: str, label: str, fmt: str = "text", align: str | None = None) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "format": fmt,
        "align": align or ("right" if fmt in ("money", "number", "percent") else "left"),
    }


def scalars(
    cur,
    scope: str,
    filters: dict[str, str],
    expressions: dict[str, str],
    *,
    include_cancelled: bool = False,
    extra: Sequence[str] = (),
) -> dict[str, float]:
    """One row of aggregates for the current selection."""
    where, params = clause(scope, filters, include_cancelled=include_cancelled, extra=extra)
    selected = ", ".join(expressions.values())
    row = rows(cur, f"SELECT {selected} FROM {SCOPES[scope]['from']}{where}", params)[0]
    return {name: num(row[index]) for index, name in enumerate(expressions)}
