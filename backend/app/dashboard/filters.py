"""The filter engine every Orion dashboard view shares, over the Orion warehouse (``orion_dw``).

A single dictionary of selections drives all views. Each fact declares the dimensions it carries, so a
selection a fact does not understand is ignored for that fact rather than blanking it. Visuals exclude the
dimension they plot themselves, which is what keeps a click reversible.

Everything reads ``orion_dw``. Facts are SCD2, so every scope keeps only the live version of each row
(``is_current`` and not ``is_expired``). The case-linked facts carry the surrogate keys of the case, client,
capability and domain *as they were on the date of the event*, so a client's state, type and priority are
those of the day the bill was raised, not today's. Rosters that are not events (employees, cases, cars,
opportunities) are read as they stand now.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Iterable, Sequence

# Dimensions shared by every case-linked fact. Measures that combine facts are
# computed on these alone so one side of a sum cannot be narrowed while the
# other stays whole.
GLOBAL_KEYS = (
    "month",
    "fy",
    "business_domain",
    "capability",
    "client",
    "case",
    "state",
    "client_type",
    "priority",
    "case_status",
)

# Selections only some facts carry.
LOCAL_KEYS = (
    "status",
    "pay_status",
    "bucket",
    "expense_type",
    "is_regular",
    "stage",
    "opp_type",
    "designation",
    "employee_type",
    "salary_paid",
    "car_model",
    "driver",
)

# Inclusive calendar bounds. Applied as a range, not as an equality, so they
# are not listed as scope fields. Kept on every combined measure so a period
# cannot shrink one fact and leave another covering all history.
RANGE_KEYS = ("from", "to")

DIMENSION_KEYS = GLOBAL_KEYS + LOCAL_KEYS
FILTER_KEYS = DIMENSION_KEYS + RANGE_KEYS


def live(alias: str) -> str:
    """The version of a warehouse row that is current and has not been deleted at the source."""
    return f"{alias}.is_current AND NOT {alias}.is_expired"


def fiscal_year(date_expr: str) -> str:
    """The start year of the Indian financial year (April to March) a date falls in, as text."""
    return (
        f"(EXTRACT(YEAR FROM {date_expr})::int - CASE WHEN EXTRACT(MONTH FROM {date_expr}) < 4 THEN 1 ELSE 0 END)::text"
    )


# Case, client, capability and domain as they were on the event date (the fact's surrogate keys), plus the case as it
# stands now, so "case status" means whether the case is running today.
_PIT_JOINS = (
    " LEFT JOIN orion_dw.dim_case c ON c.case_sk = {a}.case_sk"
    " LEFT JOIN orion_dw.dim_client cl ON cl.client_sk = {a}.client_sk"
    " LEFT JOIN orion_dw.dim_capability cap ON cap.capability_sk = {a}.capability_sk"
    " LEFT JOIN orion_dw.dim_business_domain bd ON bd.business_domain_sk = {a}.business_domain_sk"
    " LEFT JOIN orion_dw.dim_case cc ON cc.case_code = c.case_code AND cc.is_current AND NOT cc.is_expired"
)

# The same dimensions as they stand now, reached through a case code.
_CURRENT_JOINS = (
    " LEFT JOIN orion_dw.dim_case c ON c.case_code = {case_column} AND c.is_current AND NOT c.is_expired"
    " LEFT JOIN orion_dw.dim_client cl ON cl.client_code = c.client_code AND cl.is_current AND NOT cl.is_expired"
    " LEFT JOIN orion_dw.dim_capability cap ON cap.capability_code = c.capability_code"
    " AND cap.is_current AND NOT cap.is_expired"
    " LEFT JOIN orion_dw.dim_business_domain bd ON bd.business_domain_code = c.business_domain_code"
    " AND bd.is_current AND NOT bd.is_expired"
)


def _shared_fields(case_status: str) -> dict[str, str]:
    return {
        "business_domain": "bd.business_domain_code",
        "capability": "cap.capability_code",
        "client": "cl.client_code",
        "case": "c.case_code",
        "state": "cl.client_location_state",
        "client_type": "cl.client_type",
        "priority": "cl.firm_priority",
        "case_status": case_status,
    }


def _scope(
    source: str,
    joins: str,
    *,
    fields: dict[str, str],
    base: Sequence[str] = (),
    case_status: str = "cc.case_status",
    status_column: str | None = None,
    date: str | None = None,
    date_grain: str = "day",
    active_from: str | None = None,
    active_to: str | None = None,
) -> dict[str, Any]:
    return {
        "from": source + joins,
        "base": list(base),
        "status_column": status_column,
        "fields": {**_shared_fields(case_status), **fields},
        "date": date,
        "date_grain": date_grain,
        "active_from": active_from,
        "active_to": active_to,
    }


# An expense's type. EPFO and ESIC paid over (STATUTORY) and what a client held back that is not TDS (SHORTFALL) have no row in the expense types and are named here.
EXPENSE_TYPE_CODE = "COALESCE(xt.expense_type_code, e.expense_type_code)"
EXPENSE_TYPE_NAME = (
    "COALESCE(xt.expense_type_name, CASE e.expense_type_code WHEN 'STATUTORY' THEN 'EPFO and ESIC paid'"
    " WHEN 'SHORTFALL' THEN 'Penalties and short payments' END)"
)

# The money a bill still has to receive: what it was for, less what has been committed against it.
BILL_PAID = "COALESCE(p.collected, 0)"  # what has settled the bill: the cash and what the client held back (TDS and the like)
BILL_TDS = "COALESCE(p.deducted, 0)"  # of that, what the client held back
BILL_CASH = "(COALESCE(p.collected, 0) - COALESCE(p.deducted, 0))"  # of that, what reached the bank
BILL_OPEN = "GREATEST(b.grand_total - COALESCE(b.credited_amount, 0) - COALESCE(p.collected, 0), 0)"
BILL_AGE = "(CURRENT_DATE - b.bill_date)"

# What has been received against each bill so far.
_BILL_PAYMENTS = (
    " LEFT JOIN (SELECT bill_code, SUM(amount_after_tax_gst) AS collected, SUM(COALESCE(deducted_amount, 0)) AS deducted,"
    " MIN(received_date) AS first_received, MAX(received_date) AS last_received"
    " FROM orion_dw.fact_case_transaction"
    " WHERE is_current AND NOT is_expired AND transaction_status = 'Committed' AND bill_code IS NOT NULL"
    " GROUP BY bill_code) p ON p.bill_code = b.bill_code"
)

# Settled: nothing is owed, but only because a credit note took some of it off (not Paid, which is the bill settled by the client).
PAY_STATUS_SQL = (
    f"CASE WHEN {BILL_OPEN} < 1 THEN CASE WHEN COALESCE(b.credited_amount, 0) > 0 AND {BILL_PAID} < b.grand_total - 1 THEN 'Settled' ELSE 'Paid' END"
    f" WHEN {BILL_PAID} > 0 THEN 'Part paid' ELSE 'Unpaid' END"
)
BUCKET_SQL = (
    f"CASE WHEN {BILL_OPEN} < 1 THEN NULL WHEN {BILL_AGE} <= 30 THEN '0-30'"
    f" WHEN {BILL_AGE} <= 60 THEN '31-60' WHEN {BILL_AGE} <= 90 THEN '61-90' ELSE '90+' END"
)

SCOPES: dict[str, dict[str, Any]] = {
    # Tax invoices, one live version each. The month is the month the service was for.
    "bill": _scope(
        "orion_dw.fact_bill b",
        _PIT_JOINS.format(a="b") + _BILL_PAYMENTS,
        base=[live("b")],
        status_column="b.status",
        fields={
            "month": "to_char(b.service_month, 'YYYY-MM')",
            "fy": fiscal_year("b.service_month"),
            "status": "b.status",
            "pay_status": PAY_STATUS_SQL,
            "bucket": BUCKET_SQL,
        },
        date="to_char(b.service_month, 'YYYY-MM')",
        date_grain="month",
    ),
    # Revenue entries by their own status: Committed is received, Prospective is still to come, Cancelled is leakage.
    "revenue": _scope(
        "orion_dw.fact_case_transaction t",
        _PIT_JOINS.format(a="t"),
        base=[live("t")],
        status_column="t.transaction_status",
        fields={
            "month": "to_char(t.transaction_date, 'YYYY-MM')",
            "fy": fiscal_year("t.transaction_date"),
            "status": "t.transaction_status",
        },
        date="t.transaction_date",
    ),
    # Money received: Committed entries, dated the day it came in (or the entry date when none was recorded).
    "collection": _scope(
        "orion_dw.fact_case_transaction t",
        _PIT_JOINS.format(a="t"),
        base=[live("t"), "t.transaction_status = 'Committed'"],
        fields={
            "month": "to_char(COALESCE(t.received_date, t.transaction_date), 'YYYY-MM')",
            "fy": fiscal_year("COALESCE(t.received_date, t.transaction_date)"),
        },
        date="COALESCE(t.received_date, t.transaction_date)",
    ),
    # Expenses, EPFO and ESIC paid over, and penalties and short payments held back by clients (the view orion_dw.expense_cost: see dw_schema.sql), so every cost and margin figure counts them.
    "expense": _scope(
        "orion_dw.expense_cost e",
        _PIT_JOINS.format(a="e") + " LEFT JOIN orion_dw.dim_expense_type xt ON xt.expense_type_sk = e.expense_type_sk",
        base=[live("e")],
        status_column="e.transaction_status",
        fields={
            "month": "to_char(e.transaction_date, 'YYYY-MM')",
            "fy": fiscal_year("e.transaction_date"),
            "status": "e.transaction_status",
            "expense_type": EXPENSE_TYPE_CODE,
            "is_regular": "e.is_regular_expense",
        },
        date="e.transaction_date",
    ),
    "payroll": _scope(
        "orion_dw.fact_employee_transaction et",
        _PIT_JOINS.format(a="et") + " LEFT JOIN orion_dw.dim_employee emp ON emp.employee_sk = et.employee_sk",
        base=[live("et")],
        fields={
            "month": "et.month_year",
            "fy": fiscal_year("to_date(et.month_year || '-01', 'YYYY-MM-DD')"),
            "designation": "emp.employee_designation",
            "employee_type": "emp.employee_type",
            "salary_paid": "et.salary_paid",
        },
        date="et.month_year",
        date_grain="month",
    ),
    "fleet": _scope(
        "orion_dw.fact_car_transaction ct",
        _PIT_JOINS.format(a="ct")
        + " LEFT JOIN orion_dw.dim_car car ON car.car_sk = ct.car_sk"
        + " LEFT JOIN orion_dw.dim_employee drv ON drv.employee_sk = ct.driver_sk",
        base=[live("ct")],
        fields={
            "month": "to_char(ct.driving_date, 'YYYY-MM')",
            "fy": fiscal_year("ct.driving_date"),
            "car_model": "car.car_model",
            "driver": "drv.employee_code",
        },
        date="ct.driving_date",
    ),
    "opportunity": _scope(
        "orion_dw.dim_opportunity o",
        _CURRENT_JOINS.format(case_column="o.opportunity_case_code"),
        base=[live("o")],
        case_status="c.case_status",
        fields={
            "month": "to_char(o.opportunity_start_date, 'YYYY-MM')",
            "fy": fiscal_year("o.opportunity_start_date"),
            "stage": "o.opportunity_status",
            "opp_type": "o.opportunity_type",
            "state": "o.state",
        },
        date="o.opportunity_start_date",
    ),
    # Earnest money deposits, one live version each, dated the day the money was deposited. Cancelled ones were never paid, so they are left out.
    "emd": _scope(
        "orion_dw.fact_emd e",
        _PIT_JOINS.format(a="e"),
        base=[live("e"), "e.emd_status <> 'Cancelled'"],
        fields={
            "month": "to_char(e.deposit_date, 'YYYY-MM')",
            "fy": fiscal_year("e.deposit_date"),
        },
        date="e.deposit_date",
    ),
    # The people known at clients, as they stand now. The client comes from the contact itself; a case is optional.
    "contact": _scope(
        "orion_dw.dim_contact ct",
        " LEFT JOIN orion_dw.dim_client cl ON cl.client_code = ct.client_code AND cl.is_current AND NOT cl.is_expired"
        " LEFT JOIN orion_dw.dim_case c ON c.case_code = ct.case_code AND c.is_current AND NOT c.is_expired"
        " LEFT JOIN orion_dw.dim_capability cap ON cap.capability_code = c.capability_code AND cap.is_current AND NOT cap.is_expired"
        " LEFT JOIN orion_dw.dim_business_domain bd ON bd.business_domain_code = c.business_domain_code"
        " AND bd.is_current AND NOT bd.is_expired",
        base=[live("ct")],
        case_status="c.case_status",
        fields={},
        active_from="ct.contact_start_date",
        active_to="ct.contact_end_date",
    ),
    "employee": _scope(
        "orion_dw.dim_employee emp",
        _CURRENT_JOINS.format(case_column="emp.employee_case_code"),
        base=[live("emp")],
        case_status="c.case_status",
        fields={
            "designation": "emp.employee_designation",
            "employee_type": "emp.employee_type",
        },
        active_from="emp.emp_start_date",
        active_to="emp.emp_end_date",
    ),
    "car": _scope(
        "orion_dw.dim_car car",
        _CURRENT_JOINS.format(case_column="car.case_code"),
        base=[live("car")],
        case_status="c.case_status",
        fields={"car_model": "car.car_model", "driver": "car.car_driven_by"},
        active_from="c.case_start_date",
        active_to="c.case_end_date",
    ),
    "case": _scope(
        "orion_dw.dim_case c",
        " LEFT JOIN orion_dw.dim_client cl ON cl.client_code = c.client_code AND cl.is_current AND NOT cl.is_expired"
        " LEFT JOIN orion_dw.dim_capability cap ON cap.capability_code = c.capability_code"
        " AND cap.is_current AND NOT cap.is_expired"
        " LEFT JOIN orion_dw.dim_business_domain bd ON bd.business_domain_code = c.business_domain_code"
        " AND bd.is_current AND NOT bd.is_expired",
        base=[live("c")],
        case_status="c.case_status",
        fields={},
        active_from="c.case_start_date",
        active_to="c.case_end_date",
    ),
}

STAGE_ORDER = [
    "Proposal",
    "Qualified",
    "Technical Bid",
    "Financial Bid",
    "Closed Won",
    "Closed Lost",
    "Disqualified",
]
STATUS_ORDER = ["Committed", "Prospective", "Cancelled"]
BUCKET_ORDER = ["0-30", "31-60", "61-90", "90+"]
PAY_ORDER = ["Paid", "Settled", "Part paid", "Unpaid"]

# Filters whose display value is the stored value.
_PLAIN_LABELS = {
    "month": "Month",
    "status": "Status",
    "pay_status": "Payment",
    "bucket": "Ageing",
    "state": "State",
    "stage": "Pipeline stage",
    "opp_type": "Tender type",
    "designation": "Designation",
    "client_type": "Client type",
    "priority": "Priority",
    "case_status": "Case status",
    "employee_type": "Employee type",
    "salary_paid": "Salary paid",
    "car_model": "Car model",
    "is_regular": "Recurring expense",
}

_CODE_LABELS = {
    "business_domain": ("orion_dw.dim_business_domain", "business_domain_code", "business_domain_name", "Domain"),
    "capability": ("orion_dw.dim_capability", "capability_code", "capability_name", "Capability"),
    "client": ("orion_dw.dim_client", "client_code", "client_name", "Client"),
    "case": ("orion_dw.dim_case", "case_code", "case_name", "Case"),
    "expense_type": ("orion_dw.dim_expense_type", "expense_type_code", "expense_type_name", "Expense type"),
    "driver": ("orion_dw.dim_employee", "employee_code", "employee_name", "Driver"),
}


def _day(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        datetime.strptime(text, "%Y-%m-%d")
    except ValueError:
        return None
    return text


def clean_filters(raw: dict[str, Any]) -> dict[str, str]:
    cleaned = {
        key: str(raw[key]).strip()
        for key in DIMENSION_KEYS
        if raw.get(key) not in (None, "", "all")
    }
    start, end = _day(raw.get("from")), _day(raw.get("to"))
    if start and end and start > end:
        start, end = end, start
    if start:
        cleaned["from"] = start
    if end:
        cleaned["to"] = end
    return cleaned


def shared_only(filters: dict[str, str]) -> dict[str, str]:
    return {key: value for key, value in filters.items() if key in GLOBAL_KEYS or key in RANGE_KEYS}


def common(filters: dict[str, str], *scopes: str) -> dict[str, str]:
    """Filters that every named fact understands.

    When a measure subtracts one fact from another, a selection only one side
    carries would shrink that side alone. Restricting to the dimensions they
    have in common keeps the subtraction honest. The calendar range is always
    kept, because every fact that participates in a combined measure has a date.
    """
    understood = set.intersection(*(set(SCOPES[scope]["fields"]) for scope in scopes))
    understood.update(RANGE_KEYS)
    return {key: value for key, value in filters.items() if key in understood}


def _apply_range(config: dict[str, Any], filters: dict[str, str]) -> tuple[list[str], list[Any]]:
    """Inclusive from/to against an event date, a month grain, or an active span."""
    start, end = filters.get("from"), filters.get("to")
    if not start and not end:
        return [], []

    parts: list[str] = []
    params: list[Any] = []
    date_expr = config.get("date")
    if date_expr:
        if config.get("date_grain") == "month":
            if start:
                parts.append(f"{date_expr} >= to_char(%s::date, 'YYYY-MM')")
                params.append(start)
            if end:
                parts.append(f"{date_expr} <= to_char(%s::date, 'YYYY-MM')")
                params.append(end)
        else:
            if start:
                parts.append(f"{date_expr} >= %s::date")
                params.append(start)
            if end:
                parts.append(f"{date_expr} <= %s::date")
                params.append(end)

    began, finished = config.get("active_from"), config.get("active_to")
    if began:
        # Overlap: started on or before the window ends, and has not finished
        # before the window begins. Open-ended records (NULL end) stay in.
        if end:
            parts.append(f"({began} IS NULL OR {began} <= %s::date)")
            params.append(end)
        if start and finished:
            parts.append(f"({finished} IS NULL OR {finished} >= %s::date)")
            params.append(start)
    return parts, params


def clause(
    scope: str,
    filters: dict[str, str],
    exclude: Iterable[str] = (),
    *,
    include_cancelled: bool = False,
    extra: Sequence[str] = (),
) -> tuple[str, list[Any]]:
    config = SCOPES[scope]
    fields: dict[str, str] = config["fields"]
    skip = set(exclude)
    parts: list[str] = list(config.get("base", ()))
    params: list[Any] = []

    for key, value in filters.items():
        if key in skip or key in RANGE_KEYS or key not in fields:
            continue
        parts.append(f"{fields[key]} = %s")
        params.append(value)

    range_parts, range_params = _apply_range(config, filters)
    parts.extend(range_parts)
    params.extend(range_params)

    status_column = config.get("status_column")
    if status_column and not include_cancelled and "status" not in filters:
        parts.append(f"{status_column} <> 'Cancelled'")

    parts.extend(extra)
    return (" WHERE " + " AND ".join(parts) if parts else ""), params


def rows(cur, sql: str, params: Sequence[Any] = ()) -> list[tuple]:
    cur.execute(sql, list(params))
    return cur.fetchall()


def num(value: Any) -> float:
    return float(value or 0)


def inr(value: float) -> str:
    value = num(value)
    sign = "-" if value < 0 else ""
    value = abs(value)
    if value >= 1_00_00_000:
        return f"{sign}₹{value / 1_00_00_000:.2f} Cr"
    if value >= 1_00_000:
        return f"{sign}₹{value / 1_00_000:.1f} L"
    if value >= 1_000:
        return f"{sign}₹{value / 1_000:.1f} K"
    return f"{sign}₹{value:,.0f}"


def qty(value: float) -> str:
    return f"{int(round(num(value))):,}"


def delta(current: float, previous: float) -> tuple[str, str]:
    if not previous:
        return "", "neutral"
    change = (current - previous) / abs(previous) * 100
    if abs(change) < 0.05:
        return "flat", "neutral"
    return f"{change:+.1f}%", "positive" if change > 0 else "negative"


def month_label(value: str) -> str:
    try:
        return datetime.strptime(value, "%Y-%m").strftime("%b %y")
    except (ValueError, TypeError):
        return value or "—"


def day_label(value: str) -> str:
    try:
        return datetime.strptime(value, "%Y-%m-%d").strftime("%d %b %Y")
    except (ValueError, TypeError):
        return value or "—"


def months_between(start: str | None, end: str | None) -> list[str] | None:
    """YYYY-MM values covering an inclusive calendar window. None means unbounded."""
    if not start:
        return None
    first = datetime.strptime(start, "%Y-%m-%d").date()
    last = datetime.strptime(end, "%Y-%m-%d").date() if end else date.today()
    months: list[str] = []
    year, month = first.year, first.month
    while (year, month) <= (last.year, last.month):
        months.append(f"{year:04d}-{month:02d}")
        month += 1
        if month == 13:
            year, month = year + 1, 1
    return months


def data_span(cur) -> dict[str, str]:
    """Earliest and latest dates present in the warehouse facts the dashboards read."""
    row = rows(
        cur,
        """
        SELECT
          LEAST(
            (SELECT MIN(service_month) FROM orion_dw.fact_bill WHERE is_current AND NOT is_expired),
            (SELECT MIN(transaction_date) FROM orion_dw.expense_cost WHERE is_current AND NOT is_expired),
            (SELECT MIN(driving_date) FROM orion_dw.fact_car_transaction WHERE is_current AND NOT is_expired),
            (SELECT MIN(to_date(month_year || '-01', 'YYYY-MM-DD')) FROM orion_dw.fact_employee_transaction
              WHERE is_current AND NOT is_expired)
          ),
          GREATEST(
            (SELECT MAX(bill_date) FROM orion_dw.fact_bill WHERE is_current AND NOT is_expired),
            (SELECT MAX(transaction_date) FROM orion_dw.expense_cost WHERE is_current AND NOT is_expired),
            (SELECT MAX(driving_date) FROM orion_dw.fact_car_transaction WHERE is_current AND NOT is_expired),
            (SELECT MAX(to_date(month_year || '-01', 'YYYY-MM-DD')) FROM orion_dw.fact_employee_transaction
              WHERE is_current AND NOT is_expired)
          )
        """,
    )[0]
    start, end = row[0], row[1]
    return {
        "min": start.isoformat() if start else "",
        "max": end.isoformat() if end else date.today().isoformat(),
    }


def kpi(
    key: str,
    label: str,
    value: str,
    *,
    change: str = "",
    change_type: str = "neutral",
    hint: str = "",
    tone: str = "blue",
) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "value": value,
        "delta": change,
        "delta_type": change_type,
        "hint": hint,
        "tone": tone,
    }


def filter_chips(cur, filters: dict[str, str]) -> list[dict[str, str]]:
    """Human readable chips describing the active selection.

    The calendar range has its own control, so from/to are omitted here.
    """
    chips: list[dict[str, str]] = []
    for key, value in filters.items():
        if key in RANGE_KEYS:
            continue
        if key in _CODE_LABELS:
            table, pk, name, label = _CODE_LABELS[key]
            found = rows(cur, f"SELECT {name} FROM {table} WHERE {pk} = %s AND is_current", [value])
            chips.append(
                {"key": key, "label": label, "value": value, "display": found[0][0] if found else value}
            )
        elif key == "fy":
            display = f"FY {value}-{str(int(value) + 1)[2:]}" if value.isdigit() else value
            chips.append({"key": key, "label": "Financial year", "value": value, "display": display})
        elif key in _PLAIN_LABELS:
            display = month_label(value) if key == "month" else value
            chips.append({"key": key, "label": _PLAIN_LABELS[key], "value": value, "display": display})
    return chips
