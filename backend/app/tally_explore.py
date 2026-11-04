"""Drill-down for a Tally key figure: by year, month and every dimension that applies, plus the rows behind it.

Built on the same ``tally_dw`` rows and the same filter clause (``tally_dashboard._sales_where``) as the Tally dashboard, so a
figure here equals its tile. The answer has the same shape as the Orion one (``dashboard.explore``) so one screen shows both.

Billing figures are sums over billed documents. The books figures (debtors, loans, cash...) are closing balances at the last
load, so they are drilled by ledger and group instead of by year.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from app import column_filters
from app.dashboard.filters import month_label
from app.tally_dashboard import (
    _by_cost_centre,
    _chips,
    _income_from_lines,
    _position_bucket,
    _sales_where,
    _short_label,
    _voucher_kind_sql,
)

TOP = 12
MONTHS = 36

KIND = _voucher_kind_sql("v")
FY_SQL = "(CASE WHEN EXTRACT(MONTH FROM v.voucher_date) >= 4 THEN EXTRACT(YEAR FROM v.voucher_date) ELSE EXTRACT(YEAR FROM v.voucher_date) - 1 END)::int::text"
MONTH_SQL = "to_char(date_trunc('month', v.voucher_date), 'YYYY-MM')"

DIM_LABEL = {"client": "Client", "voucher_type": "Document type", "company": "Company", "cost_centre": "Cost centre", "income_line": "Income line"}
DIM_SQL = {"client": "v.party_ledger_name", "voucher_type": "v.voucher_type_name", "company": "v.company_name"}


@dataclass(frozen=True)
class Measure:
    key: str
    label: str
    fmt: str
    expr: str = ""
    additive: bool = True
    # which special breakdowns make sense: they sum revenue, so only revenue-like figures use them
    special: bool = False
    dims: tuple[str, ...] = ("client", "voucher_type", "company")
    records: tuple[tuple[str, str], ...] = (("vouchers", "Billed documents"),)
    note: str = ""
    snapshot: str = ""  # a books figure: the ledger bucket it sums
    # Conditions on a billed document that make it count towards the figure: credit notes only, or documents with an EPF line.
    population: tuple[str, ...] = ()
    population_note: str = ""


def _sum(col: str) -> str:
    return f"COALESCE(SUM(v.{col}), 0)"


def _m(key: str, label: str, fmt: str, expr: str, **kw: Any) -> Measure:
    return Measure(key, label, fmt, expr, **kw)


MEASURES: dict[str, Measure] = {
    m.key: m
    for m in [
        _m("billed", "Billed incl. GST", "money", _sum("invoice_value_incl_gst")),
        _m("revenue", "Revenue ex GST", "money", _sum("revenue_ex_gst"), special=True),
        _m("gst", "GST", "money", _sum("gst")),
        _m("cgst", "CGST", "money", _sum("cgst")),
        _m("sgst", "SGST", "money", _sum("sgst")),
        _m("invoices", "Documents", "number", "COUNT(*)"),
        _m("clients", "Clients billed", "number", "COUNT(DISTINCT v.party_ledger_name)", additive=False, dims=("voucher_type", "company")),
        _m("companies", "Companies billed", "number", "COUNT(DISTINCT v.company_name)", additive=False, dims=("client", "voucher_type")),
        _m("avg_invoice", "Average document", "money", "COALESCE(SUM(v.invoice_value_incl_gst) / NULLIF(COUNT(*), 0), 0)", additive=False),
        _m("avg_revenue", "Average revenue per document", "money", "COALESCE(SUM(v.revenue_ex_gst) / NULLIF(COUNT(*), 0), 0)", additive=False),
        _m("gst_pct", "GST share of billed", "percent", "COALESCE(SUM(v.gst) / NULLIF(SUM(v.invoice_value_incl_gst), 0) * 100, 0)", additive=False),
        _m("sales", "Sales invoiced", "money", f"COALESCE(SUM(v.invoice_value_incl_gst) FILTER (WHERE {KIND} = 'Sales'), 0)"),
        _m("credit_notes", "Credit notes", "money", f"COALESCE(SUM(v.invoice_value_incl_gst) FILTER (WHERE {KIND} = 'Credit note'), 0)",
           note="Credit notes are negative: they reduce what was billed."),
        _m("debit_notes", "Debit notes", "money", f"COALESCE(SUM(v.invoice_value_incl_gst) FILTER (WHERE {KIND} = 'Debit note'), 0)"),
        _m(
            "cn_rate", "Credit note rate", "percent",
            f"COALESCE(ABS(SUM(v.invoice_value_incl_gst) FILTER (WHERE {KIND} = 'Credit note')) / "
            f"NULLIF(SUM(v.invoice_value_incl_gst) FILTER (WHERE {KIND} = 'Sales'), 0) * 100, 0)",
            additive=False,
        ),
        _m("manpower", "Manpower revenue", "money", _sum("manpower_supply")),
        _m("vehicle", "Vehicle rent revenue", "money", _sum("vehicle_rental")),
        _m("service", "Service charge revenue", "money", _sum("service_charges")),
        _m("epf", "EPF billed", "money", _sum("epf_billed")),
        _m("esic", "ESIC billed", "money", _sum("esic_billed")),
        _m("other_income", "Other income", "money", _sum("other_income")),
        # books figures: closing balances, drilled by ledger
        Measure("debtors", "Debtors", "money", additive=True, snapshot="Sundry debtors", dims=(), records=(("ledgers_debtors", "Debtor ledgers"),),
                note="Tally shows money owed to you as a negative balance."),
        Measure("gst_payable", "GST payable", "money", snapshot="GST payable", dims=(), records=(("ledgers_gst_payable", "Tax ledgers"),)),
        Measure("loans", "Loans", "money", snapshot="Loans", dims=(), records=(("ledgers_loans", "Loan ledgers"),)),
        Measure("creditors", "Creditors", "money", snapshot="Sundry creditors", dims=(), records=(("ledgers_creditors", "Creditor ledgers"),)),
        Measure("statutory", "Statutory and other liabilities", "money", snapshot="Statutory / other liabilities", dims=(),
                records=(("ledgers_statutory", "Liability ledgers"),)),
        Measure("cash", "Cash and bank", "money", snapshot="Cash and bank", dims=(), records=(("ledgers_cash", "Cash and bank ledgers"),)),
        Measure("profit_loss", "Profit and loss", "money", snapshot="Capital / P&L", dims=(), records=(("ledgers_profit_loss", "Capital and P&L ledgers"),)),
    ]
}

def _only(key: str, condition: str, note: str) -> None:
    MEASURES[key] = replace(MEASURES[key], population=(condition,), population_note=note)


_only("sales", f"{KIND} = 'Sales'", "Only sales invoices, before any credit or debit notes.")
_only("credit_notes", f"{KIND} = 'Credit note'", "Only credit notes. They are negative: they reduce what was billed.")
_only("debit_notes", f"{KIND} = 'Debit note'", "Only debit notes.")
_only("cn_rate", f"{KIND} = 'Credit note'", "The credit notes. The rate is their value as a share of sales invoiced.")
_only("manpower", "v.manpower_supply <> 0", "Documents with a manpower-supply income line. The Ex GST column is the whole document.")
_only("vehicle", "v.vehicle_rental <> 0", "Documents with a vehicle-rent income line. The Ex GST column is the whole document.")
_only("service", "v.service_charges <> 0", "Documents with a service-charge income line. The Ex GST column is the whole document.")
_only("epf", "v.epf_billed <> 0", "Documents with an EPF line. The Ex GST column is the whole document.")
_only("esic", "v.esic_billed <> 0", "Documents with an ESIC line. The Ex GST column is the whole document.")
_only("other_income", "v.other_income <> 0", "Documents with income that is not manpower, vehicle, service, EPF or ESIC.")


def record_context(key: str) -> tuple[str, ...]:
    return MEASURES[key].population


SNAPSHOT_DATASET = {
    "ledgers_debtors": "Sundry debtors",
    "ledgers_gst_payable": "GST payable",
    "ledgers_loans": "Loans",
    "ledgers_creditors": "Sundry creditors",
    "ledgers_statutory": "Statutory / other liabilities",
    "ledgers_cash": "Cash and bank",
    "ledgers_profit_loss": "Capital / P&L",
}


def _fy_label(code: str) -> str:
    return f"FY {code}-{str(int(code) + 1)[2:]}" if code.isdigit() else code


def _num(value: Any) -> float:
    return float(value or 0)


def _grouped(cur, expr: str, filters: dict[str, str], group: str, exclude: tuple[str, ...]) -> list[tuple[Any, float]]:
    scoped = {k: v for k, v in filters.items() if k not in exclude}
    where, params = _sales_where(scoped)
    cur.execute(f"SELECT {group}, {expr} FROM tally_dw.fact_voucher v {where} GROUP BY 1", params)
    return [(r[0], _num(r[1])) for r in cur.fetchall()]


def _ledger_rows(cur, bucket: str, filters: dict[str, str], extra: dict[str, str]) -> list[dict[str, Any]]:
    parts = ["c.is_current = TRUE"]
    params: list[Any] = []
    if filters.get("company"):
        parts.append("c.company_name = %s")
        params.append(filters["company"])
    cur.execute(
        f"SELECT COALESCE(c.parent_name, ''), c.name, COALESCE(c.closing_balance, 0), COALESCE(c.ledger_class, '') "
        f"FROM tally_dw.dim_ledger c WHERE {' AND '.join(parts)} ORDER BY c.parent_name, c.name",
        params,
    )
    out = []
    for parent, name, closing, klass in cur.fetchall():
        if _position_bucket(parent, name) != bucket:
            continue
        if extra.get("group") and (parent or "—") != extra["group"]:
            continue
        if extra.get("ledger") and name != extra["ledger"]:
            continue
        out.append({"group": parent or "—", "ledger": name, "closing": _num(closing), "class": klass})
    return out


def _explore_snapshot(cur, measure: Measure, filters: dict[str, str], extra: dict[str, str]) -> dict[str, Any]:
    ledgers = _ledger_rows(cur, measure.snapshot, filters, extra)
    every = _ledger_rows(cur, measure.snapshot, filters, {})
    total = round(sum(r["closing"] for r in ledgers), 2)

    def bars(key: str, field_: str, source: list[dict[str, Any]], limit: int | None = TOP) -> dict[str, Any] | None:
        sums: dict[str, float] = {}
        for r in source:
            sums[r[field_]] = sums.get(r[field_], 0.0) + r["closing"]
        items = [{"code": k, "label": _short_label(k, 40), "value": round(v, 2)} for k, v in sums.items() if abs(v) > 0.005]
        items.sort(key=lambda r: abs(r["value"]), reverse=True)
        if len(items) < 2 and not extra.get(key):
            return None
        return {"key": key, "label": DIM_LABEL.get(key, "Account group" if key == "group" else "Ledger"), "items": items[:limit], "more": max(0, len(items) - (limit or 0))}

    # a pick of one breakdown narrows the other, but not itself
    by_group = bars("group", "group", _ledger_rows(cur, measure.snapshot, filters, {k: v for k, v in extra.items() if k != "group"}))
    by_ledger = bars("ledger", "ledger", _ledger_rows(cur, measure.snapshot, filters, {k: v for k, v in extra.items() if k != "ledger"}))
    return {
        "measure": measure.key,
        "label": measure.label,
        "format": measure.fmt,
        "additive": True,
        "snapshot": True,
        "note": (measure.note + " " if measure.note else "") + f"Closing balances at the last warehouse load; {len(every)} ledgers.",
        "total": total,
        "years": [],
        "months": [],
        "breakdowns": [b for b in (by_group, by_ledger) if b],
        "records": [{"dataset": d, "label": label} for d, label in measure.records],
        "population_note": "",
        "chips": [
            *([{"key": "group", "label": "Account group", "value": extra["group"], "display": extra["group"]}] if extra.get("group") else []),
            *([{"key": "ledger", "label": "Ledger", "value": extra["ledger"], "display": _short_label(extra["ledger"], 40)}] if extra.get("ledger") else []),
        ],
    }


def explore(cur, key: str, filters: dict[str, str], extra: dict[str, str] | None = None) -> dict[str, Any]:
    measure = MEASURES[key]
    extra = extra or {}
    if measure.snapshot:
        return _explore_snapshot(cur, measure, filters, extra)

    where, params = _sales_where(filters)
    cur.execute(f"SELECT {measure.expr} FROM tally_dw.fact_voucher v {where}", params)
    total = round(_num(cur.fetchone()[0]), 2)

    years = sorted(
        ({"code": str(c), "label": _fy_label(str(c)), "value": round(v, 2)} for c, v in _grouped(cur, measure.expr, filters, FY_SQL, ("fy", "month")) if c is not None),
        key=lambda r: r["code"],
    )
    months = sorted(
        ({"code": c, "label": month_label(c), "value": round(v, 2)} for c, v in _grouped(cur, measure.expr, filters, MONTH_SQL, ("month",)) if c),
        key=lambda r: r["code"],
    )[-MONTHS:]

    breakdowns: list[dict[str, Any]] = []
    for dim in measure.dims:
        items = [
            {"code": str(c), "label": _short_label(str(c), 40) if dim == "client" else str(c), "value": round(v, 2)}
            for c, v in _grouped(cur, measure.expr, filters, DIM_SQL[dim], (dim,))
            if c is not None and (v or measure.fmt == "percent")
        ]
        items.sort(key=lambda r: abs(r["value"]), reverse=True)
        shown = items[:TOP]
        if measure.additive and total:
            for i in shown:
                i["share"] = round(i["value"] / total * 100, 1)
        if len(shown) > 1 or (shown and filters.get(dim)):
            breakdowns.append({"key": dim, "label": DIM_LABEL[dim], "items": shown, "more": max(0, len(items) - TOP)})

    if measure.special:
        lines = _income_from_lines(cur, filters)["groups"]
        if len(lines) > 1 or (lines and filters.get("income_line")):
            breakdowns.append({"key": "income_line", "label": DIM_LABEL["income_line"], "items": [{"code": g["code"], "label": g["label"], "value": g["value"]} for g in lines], "more": 0})
        centres = _by_cost_centre(cur, filters)
        if len(centres) > 1 or (centres and filters.get("cost_centre")):
            shown = [{"code": c["code"], "label": c["label"], "value": round(c["revenue"], 2)} for c in centres[:TOP]]
            breakdowns.append({"key": "cost_centre", "label": DIM_LABEL["cost_centre"], "items": shown, "more": max(0, len(centres) - TOP)})

    return {
        "measure": measure.key,
        "label": measure.label,
        "format": measure.fmt,
        "additive": measure.additive,
        "snapshot": False,
        "note": measure.note,
        "total": total,
        "years": years,
        "months": months,
        "breakdowns": breakdowns,
        "records": [{"dataset": d, "label": label} for d, label in measure.records],
        "population_note": measure.population_note,
        "chips": _chips(filters),
    }


# --------------------------------------------------------------------------- the rows behind a figure

VOUCHER_COLUMNS = [
    ("date", "Date", "text", "v.voucher_date"),
    ("number", "Document", "text", "v.voucher_number"),
    ("type", "Type", "text", "v.voucher_type_name"),
    ("client", "Client", "text", "v.party_ledger_name"),
    ("billed", "Billed", "money", "v.invoice_value_incl_gst"),
    ("revenue", "Ex GST", "money", "v.revenue_ex_gst"),
    ("gst", "GST", "money", "v.gst"),
    ("narration", "Narration", "text", "v.narration"),
]
MONEY_TOTALS = ("billed", "revenue", "gst")


def _clean(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()[:10]
    return value


def records(
    cur,
    dataset: str,
    filters: dict[str, str],
    extra: dict[str, str] | None = None,
    *,
    q: str = "",
    sort: str | None = None,
    direction: str | None = None,
    page: int = 1,
    size: int = 25,
    export: bool = False,
    conditions: tuple[str, ...] = (),
    column_filters_: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    extra = extra or {}
    size = 20000 if export else max(1, min(int(size), 100))
    offset = 0 if export else (max(1, int(page)) - 1) * size

    if dataset in SNAPSHOT_DATASET:
        data = _ledger_rows(cur, SNAPSHOT_DATASET[dataset], filters, extra)
        needle = q.strip().lower()
        if needle:
            data = [r for r in data if needle in r["ledger"].lower() or needle in r["group"].lower()]
        key = sort if sort in ("group", "ledger", "closing") else "closing"
        reverse = (direction or "desc").lower() != "asc"
        data.sort(key=lambda r: (abs(r[key]) if key == "closing" else str(r[key]).lower()), reverse=reverse)
        total_rows = len(data)
        sliced = data[offset : offset + size]
        return {
            "dataset": dataset,
            "label": next((label for m in MEASURES.values() for d, label in m.records if d == dataset), dataset),
            "columns": [
                {"key": "ledger", "label": "Ledger", "format": "text", "align": "left"},
                {"key": "group", "label": "Account group", "format": "text", "align": "left"},
                {"key": "closing", "label": "Closing balance", "format": "money", "align": "right"},
            ],
            "rows": [{"ledger": r["ledger"], "group": r["group"], "closing": r["closing"]} for r in sliced],
            "total": total_rows,
            "totals": {"closing": round(sum(r["closing"] for r in data), 2)},
            "page": 1 if export else max(1, int(page)),
            "size": size,
            "sort": {"key": key, "dir": "desc" if reverse else "asc"},
            "link": None,
            "period_applies": False,
            "truncated": False,
            "filterable": False,  # worked out in Python, not read from a table
        }

    if dataset != "vouchers":
        raise KeyError(dataset)
    where, params = _sales_where(filters)
    for condition in conditions:
        where += f" AND ({condition})"
    needle = q.strip()
    if needle:
        cols = ["v.voucher_number", "v.voucher_type_name", "v.party_ledger_name", "v.narration"]
        where += " AND (" + " OR ".join(f"{c}::text ILIKE %s" for c in cols) + ")"
        params = [*params, *([f"%{needle}%"] * len(cols))]
    by_key = {c[0]: c for c in VOUCHER_COLUMNS}
    if column_filters_:
        sql, more = column_filters.build(column_filters_, {c[0]: (c[3], column_filters.kind_of_format(c[2])) for c in VOUCHER_COLUMNS})
        if sql:
            where += f" AND {sql}"
            params = [*params, *more]
    key = sort if sort in by_key else "date"
    order = "ASC" if (direction or "desc").lower() == "asc" else "DESC"
    cur.execute(f"SELECT COUNT(*) FROM tally_dw.fact_voucher v {where}", params)
    total_rows = int(cur.fetchone()[0])
    cur.execute(
        "SELECT " + ", ".join(f"COALESCE(SUM({by_key[k][3]}), 0)" for k in MONEY_TOTALS) + f" FROM tally_dw.fact_voucher v {where}", params
    )
    sums = dict(zip(MONEY_TOTALS, (_num(x) for x in cur.fetchone())))
    cur.execute(
        "SELECT " + ", ".join(f"{c[3]} AS {c[0]}" for c in VOUCHER_COLUMNS)
        + f" FROM tally_dw.fact_voucher v {where} ORDER BY {by_key[key][3]} {order} NULLS LAST LIMIT {size} OFFSET {offset}",
        params,
    )
    rows_out = [{c[0]: _clean(r[i]) for i, c in enumerate(VOUCHER_COLUMNS)} for r in cur.fetchall()]
    return {
        "dataset": "vouchers",
        "label": "Billed documents",
        "columns": [{"key": c[0], "label": c[1], "format": c[2], "align": "right" if c[2] == "money" else "left"} for c in VOUCHER_COLUMNS],
        "rows": rows_out,
        "total": total_rows,
        "totals": sums,
        "page": 1 if export else max(1, int(page)),
        "size": size,
        "sort": {"key": key, "dir": order.lower()},
        "link": None,
        "period_applies": True,
        "truncated": export and total_rows > 20000,
        "filterable": True,
    }
