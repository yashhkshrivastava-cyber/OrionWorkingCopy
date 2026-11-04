"""Drill-through: the rows behind a dashboard figure.

Every dataset is read from the warehouse with the same filter engine the charts use, so "view records" on a chart shows
exactly the rows that make up its figure. Datasets that expose people or money row by row say who may open them (``needs``);
the dashboard flag alone is not enough for salaries.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Sequence

from app import column_filters
from app.dashboard.engine import without_period
from app.dashboard.filters import (
    EXPENSE_TYPE_NAME,
    BILL_AGE,
    BILL_CASH,
    BILL_OPEN,
    BILL_TDS,
    SCOPES,
    clause,
    rows,
)

MAX_PAGE = 100
MAX_EXPORT = 20000

BILLED_TO_DATE = (
    "(SELECT COALESCE(SUM(fb.taxable_total - COALESCE(fb.credited_taxable, 0)), 0) FROM orion_dw.fact_bill fb WHERE fb.case_code = c.case_code"
    " AND fb.is_current AND NOT fb.is_expired AND fb.status = 'Issued')"
)


def _col(key: str, label: str, fmt: str, expr: str, *, search: bool = False, total: bool = False) -> dict[str, Any]:
    return {"key": key, "label": label, "format": fmt, "expr": expr, "search": search, "total": total,
            "align": "right" if fmt in ("money", "number", "percent") else "left"}


FLDS = SCOPES["bill"]["fields"]

DATASETS: dict[str, dict[str, Any]] = {
    "bills": {
        "label": "Bills",
        "scope": "bill",
        "needs": "billing",
        "id": "b.bill_code",
        "link": "/utility/billing/{id}",
        "sort": ("bill_date", "desc"),
        "columns": [
            _col("number", "Bill", "bill", "b.bill_number", search=True),
            _col("bill_date", "Bill date", "text", "b.bill_date"),
            _col("service_month", "Service month", "text", "to_char(b.service_month, 'Mon YYYY')"),
            _col("client", "Client", "text", "cl.client_name", search=True),
            _col("case", "Case", "text", "c.case_name", search=True),
            _col("taxable", "Taxable", "money", "b.taxable_total - COALESCE(b.credited_taxable, 0)", total=True),
            _col("gst", "GST", "money", "b.cgst_amount + b.sgst_amount - COALESCE(b.credited_cgst, 0) - COALESCE(b.credited_sgst, 0)", total=True),
            _col("billed", "Billed", "money", "b.grand_total", total=True),
            _col("credited", "Credited", "money", "COALESCE(b.credited_amount, 0)", total=True),
            _col("received", "Received", "money", BILL_CASH, total=True),
            _col("tds", "TDS held back", "money", BILL_TDS, total=True),
            _col("open", "Owed", "money", BILL_OPEN, total=True),
            _col("payment", "Payment", "text", FLDS["pay_status"]),
            _col("status", "Status", "text", "b.status"),
            _col("version", "Version", "number", "b.version_no"),
            _col("gst_paid", "GST paid", "text", "CASE WHEN b.gst_paid THEN 'Yes' WHEN COALESCE(b.gst_paid_amount, 0) > 0 THEN 'Part paid' ELSE 'No' END"),
            _col("gst_left", "GST to pay", "money", "(b.cgst_amount + b.sgst_amount - COALESCE(b.credited_cgst, 0) - COALESCE(b.credited_sgst, 0) - COALESCE(b.gst_paid_amount, 0))", total=True),
            _col("epf_charged", "EPFO charged", "money", "b.epf_amount", total=True),
            _col("epf_left", "EPFO to pay", "money", "GREATEST(b.epf_amount - COALESCE(b.epf_paid_amount, 0), 0)", total=True),
            _col("esic_charged", "ESIC charged", "money", "b.esic_amount", total=True),
            _col("esic_left", "ESIC to pay", "money", "GREATEST(b.esic_amount - COALESCE(b.esic_paid_amount, 0), 0)", total=True),
        ],
    },
    "receivables": {
        "label": "Unpaid bills",
        "scope": "bill",
        "needs": "billing",
        "period": False,
        "extra": [f"{BILL_OPEN} >= 1"],
        "id": "b.bill_code",
        "link": "/utility/billing/{id}",
        "sort": ("age", "desc"),
        "columns": [
            _col("number", "Bill", "bill", "b.bill_number", search=True),
            _col("client", "Client", "text", "cl.client_name", search=True),
            _col("case", "Case", "text", "c.case_name", search=True),
            _col("bill_date", "Bill date", "text", "b.bill_date"),
            _col("age", "Age (days)", "number", BILL_AGE),
            _col("bucket", "Ageing", "text", FLDS["bucket"]),
            _col("billed", "Billed", "money", "b.grand_total", total=True),
            _col("credited", "Credited", "money", "COALESCE(b.credited_amount, 0)", total=True),
            _col("received", "Received", "money", BILL_CASH, total=True),
            _col("tds", "TDS held back", "money", BILL_TDS, total=True),
            _col("open", "Owed", "money", BILL_OPEN, total=True),
        ],
    },
    "receipts": {
        "label": "Payments received",
        "scope": "collection",
        "needs": "billing",
        "join": " LEFT JOIN orion_dw.fact_bill rb ON rb.bill_sk = t.bill_sk",
        "id": "rb.bill_code",
        "link": "/utility/billing/{id}",
        "sort": ("received", "desc"),
        "columns": [
            _col("received", "Received", "text", "COALESCE(t.received_date, t.transaction_date)"),
            _col("client", "Client", "text", "cl.client_name", search=True),
            _col("case", "Case", "text", "c.case_name", search=True),
            _col("bill", "Bill", "bill", "rb.bill_number", search=True),
            _col("amount", "Cash received", "money", "t.amount_after_tax_gst - COALESCE(t.deducted_amount, 0)", total=True),
            _col("tds", "TDS held back", "money", "COALESCE(t.deducted_amount, 0)", total=True),
            _col("note", "Note", "text", "t.transaction_description", search=True),
        ],
    },
    "expenses": {
        "label": "Expenses",
        "scope": "expense",
        "needs": None,
        "sort": ("date", "desc"),
        "columns": [
            _col("date", "Date", "text", "e.transaction_date"),
            _col("case", "Case", "text", "c.case_name", search=True),
            _col("client", "Client", "text", "cl.client_name", search=True),
            _col("type", "Expense type", "text", EXPENSE_TYPE_NAME, search=True),
            _col("amount", "Amount", "money", "e.transaction_amount", total=True),
            _col("gst", "GST", "money", "e.gst", total=True),
            _col("total", "Total", "money", "e.amount_after_tax_gst", total=True),
            _col("status", "Status", "text", "e.transaction_status"),
            _col("recurring", "Recurring", "text", "e.is_regular_expense"),
        ],
    },
    "payroll": {
        "label": "Payroll lines",
        "scope": "payroll",
        "needs": "ods",
        "sort": ("month", "desc"),
        "columns": [
            _col("month", "Month", "text", "et.month_year"),
            _col("employee", "Employee", "text", "emp.employee_name", search=True),
            _col("designation", "Designation", "text", "emp.employee_designation", search=True),
            _col("case", "Case", "text", "c.case_name", search=True),
            _col("days", "Days", "number", "et.days_worked"),
            _col("salary", "Salary", "money", "et.salary_amount", total=True),
            _col("paid", "Paid", "text", "et.salary_paid"),
        ],
    },
    "employees": {
        "label": "Employees",
        "scope": "employee",
        "needs": "ods",
        "period": False,
        "sort": ("name", "asc"),
        "columns": [
            _col("code", "Code", "text", "emp.employee_code", search=True),
            _col("name", "Name", "text", "emp.employee_name", search=True),
            _col("designation", "Designation", "text", "emp.employee_designation", search=True),
            _col("type", "Type", "text", "emp.employee_type"),
            _col("case", "Case", "text", "c.case_name", search=True),
            _col("started", "Started", "text", "emp.emp_start_date"),
            _col("left", "Left", "text", "emp.emp_end_date"),
            _col("status", "Status", "text", "emp.employee_status"),
        ],
    },
    "cases": {
        "label": "Cases",
        "scope": "case",
        "needs": None,
        "period": False,
        "sort": ("billed", "desc"),
        "columns": [
            _col("case", "Case", "text", "c.case_name", search=True),
            _col("client", "Client", "text", "cl.client_name", search=True),
            _col("domain", "Domain", "text", "bd.business_domain_name"),
            _col("capability", "Capability", "text", "cap.capability_name"),
            _col("status", "Status", "text", "c.case_status"),
            _col("started", "Started", "text", "c.case_start_date"),
            _col("ended", "Ended", "text", "c.case_end_date"),
            _col("expected", "Expected / month", "money", "c.monthly_expected_revenue", total=True),
            _col("billed", "Revenue to date", "money", BILLED_TO_DATE, total=True),
        ],
    },
    "fleet": {
        "label": "Car logs",
        "scope": "fleet",
        "needs": None,
        "sort": ("date", "desc"),
        "columns": [
            _col("date", "Date", "text", "ct.driving_date"),
            _col("car", "Car", "text", "car.car_number", search=True),
            _col("model", "Model", "text", "car.car_model", search=True),
            _col("driver", "Driver", "text", "drv.employee_name", search=True),
            _col("case", "Case", "text", "c.case_name", search=True),
            _col("initial", "Start reading", "number", "ct.initial_reading"),
            _col("final", "End reading", "number", "ct.final_reading"),
            _col("km", "Km", "number", "ct.driven_km", total=True),
            _col("cost", "Cost", "money", "ct.driven_km * COALESCE(car.per_km_price, 0)", total=True),
        ],
    },
    "opportunities": {
        "label": "Opportunities",
        "scope": "opportunity",
        "needs": None,
        "sort": ("started", "desc"),
        "columns": [
            _col("name", "Opportunity", "text", "o.opportunity_name", search=True),
            _col("tender", "Tender", "text", "o.tender_id", search=True),
            _col("stage", "Stage", "text", "o.opportunity_status"),
            _col("type", "Type", "text", "o.opportunity_type"),
            _col("place", "Where", "text", "COALESCE(o.city || ', ', '') || COALESCE(o.state, '')", search=True),
            _col("started", "Started", "text", "o.opportunity_start_date"),
            _col("closed", "Closed", "text", "o.opportunity_end_date"),
            _col("workers", "Workers", "number", "o.workers", total=True),
            _col("reason", "Reason", "text", "o.reason", search=True),
        ],
    },
    "emds": {
        "label": "EMDs",
        "scope": "emd",
        "needs": "ods",
        "sort": ("deposited", "desc"),
        "columns": [
            _col("case", "Case", "text", "c.case_name", search=True),
            _col("client", "Client", "text", "cl.client_name", search=True),
            _col("tender", "Tender", "text", "e.tender_reference", search=True),
            _col("status", "Status", "text", "e.emd_status"),
            _col("mode", "Paid by", "text", "e.payment_mode"),
            _col("instrument", "Instrument no.", "text", "e.instrument_number", search=True),
            _col("deposited", "Deposited", "text", "e.deposit_date"),
            _col("valid_until", "Valid till", "text", "e.valid_until"),
            _col("refund_due", "Refund due", "text", "e.refund_due_date"),
            _col("refunded_on", "Refunded on", "text", "e.refund_received_date"),
            _col("amount", "Amount", "money", "e.emd_amount", total=True),
            _col("refunded", "Refunded", "money", "e.refund_amount", total=True),
            _col("deducted", "Deducted", "money", "e.deduction_amount", total=True),
        ],
    },
    "contacts": {
        "label": "Client contacts",
        "scope": "contact",
        "needs": "ods",
        "period": False,
        "sort": ("name", "asc"),
        "columns": [
            _col("name", "Contact", "text", "ct.contact_name", search=True),
            _col("client", "Client", "text", "cl.client_name", search=True),
            _col("case", "Case", "text", "c.case_name", search=True),
            _col("designation", "Designation", "text", "ct.designation", search=True),
            _col("role", "Role", "text", "ct.contact_role"),
            _col("status", "Status", "text", "ct.contact_status"),
            _col("primary", "Primary", "text", "ct.is_primary_contact"),
            _col("since", "Since", "text", "ct.contact_start_date"),
            _col("last", "Last contacted", "text", "ct.last_contacted_date"),
            _col("follow_up", "Follow-up", "text", "ct.next_follow_up_date"),
        ],
    },
}


def _variant(base: str, label: str, *, extra: tuple[str, ...] = (), **over: Any) -> dict[str, Any]:
    """A record set that is another set with a condition added. Reached from a figure's drill-down, not the menu."""
    spec = {**DATASETS[base], "label": label, "hidden": True, **over}
    spec["extra"] = [*DATASETS[base].get("extra", ()), *extra]
    return spec


# The same unpaid bills, but narrowed by the period, for a figure that is drilled into by year.
DATASETS["owed"] = _variant("receivables", "Unpaid bills", period=True)
DATASETS["overdue"] = _variant("receivables", "Bills over 90 days old", period=True, extra=(f"{BILL_AGE} > 90",))
DATASETS["gst_pending"] = _variant("bills", "Bills with GST to mark paid", extra=("NOT b.gst_paid",))
DATASETS["statutory_pending"] = _variant(
    "bills", "Bills with EPFO or ESIC to pay",
    extra=("(b.epf_amount - COALESCE(b.epf_paid_amount, 0) > 0.004 OR b.esic_amount - COALESCE(b.esic_paid_amount, 0) > 0.004)",),
)
DATASETS["edited"] = _variant("bills", "Bills edited after issue", extra=("b.version_no > 1",))
DATASETS["cancelled"] = _variant("bills", "Cancelled bills", extra=("b.status = 'Cancelled'",), include_cancelled=True)
DATASETS["active_employees"] = _variant("employees", "Active employees", extra=("emp.employee_status = 'Active'",))
DATASETS["open_opps"] = _variant(
    "opportunities", "Open opportunities", extra=("o.opportunity_status IN ('Proposal', 'Qualified', 'Technical Bid', 'Financial Bid')",)
)
DATASETS["emds_open"] = _variant("emds", "EMDs still to come back", period=False, extra=("e.emd_status IN ('Deposited', 'Refund requested')",))
DATASETS["emds_overdue"] = _variant(
    "emds", "EMDs past their refund due date", period=False,
    extra=("e.emd_status IN ('Deposited', 'Refund requested')", "e.refund_due_date < CURRENT_DATE"),
)
DATASETS["emds_not_returned"] = _variant(
    "emds", "EMDs forfeited or deducted", period=False, extra=("(e.emd_status = 'Forfeited' OR COALESCE(e.deduction_amount, 0) > 0)",)
)
DATASETS["contacts_follow_up"] = _variant(
    "contacts", "Contacts due a follow-up", extra=("ct.contact_status = 'Active'", "ct.next_follow_up_date <= CURRENT_DATE")
)
DATASETS["payroll_pending"] =_variant("payroll", "Payroll lines not marked paid", extra=("et.salary_paid = 'No'",))


def clean(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()[:10]
    return value


def allowed(dataset: str, user: dict[str, Any]) -> bool:
    from app.auth import can_access_billing, can_access_ods, is_admin

    need = DATASETS[dataset]["needs"]
    if need is None or is_admin(user):
        return True
    if need == "billing":
        return bool(can_access_billing(user) or can_access_ods(user))
    return bool(can_access_ods(user))


def datasets_for(user: dict[str, Any]) -> list[dict[str, str]]:
    # Narrowed sets (only won, only cancelled) are listed too, marked hidden: charts open them, the menu does not offer them.
    return [
        {"id": key, "label": spec["label"], "hidden": bool(spec.get("hidden"))}
        for key, spec in DATASETS.items()
        if allowed(key, user)
    ]


def fetch(
    cur,
    dataset: str,
    filters: dict[str, str],
    *,
    q: str = "",
    sort: str | None = None,
    direction: str | None = None,
    page: int = 1,
    size: int = 25,
    export: bool = False,
    extra: Sequence[str] = (),
    include_cancelled: bool | None = None,
    column_filters_: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """``extra`` and ``include_cancelled`` carry the context of a figure the rows were opened from: the conditions that
    make a row count towards it, such as "only won" for the Won tile, so the table holds exactly what the figure summed."""
    spec = DATASETS[dataset]
    scope = spec["scope"]
    use = without_period(filters) if spec.get("period") is False else filters
    keep_cancelled = bool(spec.get("include_cancelled")) if include_cancelled is None else include_cancelled
    where, params = clause(scope, use, include_cancelled=keep_cancelled, extra=[*spec.get("extra", ()), *extra])
    source = SCOPES[scope]["from"] + spec.get("join", "")
    columns = spec["columns"]
    by_key = {c["key"]: c for c in columns}

    needle = q.strip()
    if needle:
        searchable = [c["expr"] for c in columns if c["search"]]
        if searchable:
            where += (" AND " if where else " WHERE ") + "(" + " OR ".join(f"{expr}::text ILIKE %s" for expr in searchable) + ")"
            params = [*params, *([f"%{needle}%"] * len(searchable))]

    if column_filters_:  # a condition on a column, as the table's headers offer them
        sql, more = column_filters.build(column_filters_, {c["key"]: (c["expr"], column_filters.kind_of_format(c["format"])) for c in columns})
        if sql:
            where += (" AND " if where else " WHERE ") + sql
            params = [*params, *more]

    default_key, default_dir = spec["sort"]
    sort_key = sort if sort in by_key else default_key
    sort_dir = "ASC" if (direction or default_dir).lower() == "asc" else "DESC"

    total = int(rows(cur, f"SELECT COUNT(*) FROM {source}{where}", params)[0][0])
    sums = [c for c in columns if c["total"]]
    totals: dict[str, float] = {}
    if sums:
        sel = ", ".join(f"COALESCE(SUM({c['expr']}), 0)" for c in sums)
        got = rows(cur, f"SELECT {sel} FROM {source}{where}", params)[0]
        totals = {c["key"]: float(v or 0) for c, v in zip(sums, got)}

    size = MAX_EXPORT if export else max(1, min(int(size), MAX_PAGE))
    offset = 0 if export else (max(1, int(page)) - 1) * size
    id_expr = spec.get("id")
    select = ", ".join(f"{c['expr']} AS {c['key']}" for c in columns)
    if id_expr:
        select = f"{id_expr} AS _id, {select}"
    sql = (
        f"SELECT {select} FROM {source}{where} ORDER BY {by_key[sort_key]['expr']} {sort_dir} NULLS LAST"
        f" LIMIT {size} OFFSET {offset}"
    )
    data = rows(cur, sql, params)
    shift = 1 if id_expr else 0
    records = []
    for r in data:
        record = {c["key"]: clean(r[i + shift]) for i, c in enumerate(columns)}
        if id_expr:
            record["_id"] = r[0]
        records.append(record)
    return {
        "dataset": dataset,
        "label": spec["label"],
        "columns": [{k: c[k] for k in ("key", "label", "format", "align")} for c in columns],
        "rows": records,
        "total": total,
        "totals": totals,
        "page": 1 if export else max(1, int(page)),
        "size": size,
        "sort": {"key": sort_key, "dir": sort_dir.lower()},
        "link": spec.get("link"),
        "period_applies": spec.get("period") is not False,
        "truncated": export and total > MAX_EXPORT,
        "filterable": True,
    }
