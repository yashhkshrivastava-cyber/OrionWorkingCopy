"""Drill-down for a key figure: the figure by year and month, by every dimension that applies, and the rows behind it.

Opening a tile asks for ``explore(measure, filters)``. The answer is built from the same scopes and filter engine the
dashboards use, so a figure here equals the tile it came from, and every bar is a filter the page can apply and undo.

A measure is one or more *parts* (an aggregate over one scope) and a rule that combines them. Revenue is one part. Margin is
three: revenue, payroll and expenses. A ratio is worked out per bar from its own parts, never from the bars' ratios.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Callable

from app.dashboard.engine import (
    BILLED,
    COLLECTED,
    CREDITED,
    ITC,
    SETTLED,
    TDS_HELD,
    EXPENSE,
    FLEET_COST,
    EPF_UNPAID,
    ESIC_UNPAID,
    GST,
    KM,
    OPEN,
    OPEN_STAGES,
    DECIDED_STAGES,
    REVENUE,
    SALARY,
    UNALLOCATED,
)
from app.dashboard.filters import (
    EXPENSE_TYPE_NAME,
    BILL_AGE,
    BILL_OPEN,
    SCOPES,
    clause,
    common,
    filter_chips,
    month_label,
    num,
    rows,
)

TOP = 12
MONTHS = 36

DIM_LABEL = {
    "business_domain": "Business domain",
    "capability": "Capability",
    "client": "Client",
    "case": "Case",
    "client_type": "Client type",
    "state": "State",
    "priority": "Priority",
    "pay_status": "Payment status",
    "bucket": "Age of bill",
    "status": "Status",
    "expense_type": "Expense type",
    "is_regular": "Recurring cost",
    "designation": "Designation",
    "employee_type": "Employment type",
    "salary_paid": "Salary paid",
    "car_model": "Car model",
    "driver": "Driver",
    "stage": "Stage",
    "opp_type": "Tender type",
    "case_status": "Case status",
}

# Where a dimension's readable name lives. Anything not listed reads as its own code.
NAME_EXPR = {
    "business_domain": "bd.business_domain_name",
    "capability": "cap.capability_name",
    "client": "cl.client_name",
    "case": "c.case_name",
    "expense_type": EXPENSE_TYPE_NAME,
    "driver": "drv.employee_name",
}

CASE_DIMS = ("business_domain", "capability", "state", "client_type", "priority", "client", "case")
BILL_DIMS = (*CASE_DIMS, "pay_status", "bucket")


@dataclass(frozen=True)
class Part:
    scope: str
    expr: str
    extra: tuple[str, ...] = ()
    include_cancelled: bool = False


@dataclass(frozen=True)
class Measure:
    key: str
    label: str
    fmt: str  # money | number | percent
    parts: dict[str, Part]
    dims: tuple[str, ...]
    records: tuple[tuple[str, str], ...]
    combine: Callable[[dict[str, float]], float] = field(default=lambda v: v["v"])
    additive: bool = True  # bars add up to the total, so a share of the whole means something
    trend: bool = True
    note: str = ""
    # The rows that count towards the figure, for each record set it opens: extra conditions, and whether cancelled rows
    # count. Without these a table opened from "Won" would list every opportunity.
    population: dict[str, tuple[tuple[str, ...], bool]] = field(default_factory=dict)
    population_note: str = ""


def one(scope: str, expr: str, **kw: Any) -> dict[str, Part]:
    return {"v": Part(scope, expr, **kw)}


def ratio(num_key: str, den_key: str, scale: float = 100.0) -> Callable[[dict[str, float]], float]:
    return lambda v: v[num_key] / v[den_key] * scale if v.get(den_key) else 0.0


def _bill(key: str, label: str, fmt: str, expr: str, records=(("bills", "Bills"),), **kw: Any) -> Measure:
    extra_part = kw.pop("part", {})
    return Measure(key, label, fmt, one("bill", expr, **extra_part), BILL_DIMS, records, **kw)


COMMON = ("business_domain", "capability", "state", "client_type", "priority", "client", "case")

_EMD_OPEN = "e.emd_status IN ('Deposited', 'Refund requested')"
_EMD_LOST = "CASE WHEN e.emd_status = 'Forfeited' THEN e.emd_amount ELSE COALESCE(e.deduction_amount, 0) END"

MEASURES: dict[str, Measure] = {
    m.key: m
    for m in [
        _bill("revenue", "Revenue", "money", REVENUE),
        _bill("billed", "Billed", "money", BILLED),
        _bill("gst", "GST on bills", "money", GST),
        _bill("bills", "Bills raised", "number", "COUNT(*)"),
        _bill("avg_bill", "Average bill", "money", "COALESCE(SUM(b.grand_total) / NULLIF(COUNT(*), 0), 0)", additive=False),
        _bill("clients", "Clients billed", "number", "COUNT(DISTINCT cl.client_code)", additive=False),
        _bill("cases_billed", "Cases billed", "number", "COUNT(DISTINCT c.case_code)", additive=False),
        _bill(
            "days_to_collect", "Days to collect", "number",
            f"COALESCE(AVG(p.last_received - b.bill_date) FILTER (WHERE {BILL_OPEN} < 1 AND p.last_received IS NOT NULL), 0)",
            additive=False,
        ),
        _bill(
            "gst_unpaid", "GST not marked paid", "money",
            "COALESCE(SUM(b.cgst_amount + b.sgst_amount - COALESCE(b.credited_cgst, 0) - COALESCE(b.credited_sgst, 0) - COALESCE(b.gst_paid_amount, 0)) FILTER (WHERE NOT b.gst_paid), 0)",
            records=(("gst_pending", "Bills with GST to mark paid"),),
        ),
        _bill("epf_unpaid", "EPFO not marked paid", "money", EPF_UNPAID, records=(("statutory_pending", "Bills with EPFO or ESIC to pay"),)),
        _bill("esic_unpaid", "ESIC not marked paid", "money", ESIC_UNPAID, records=(("statutory_pending", "Bills with EPFO or ESIC to pay"),)),
        _bill(
            "edited_bills", "Edited bills", "number", "COUNT(*) FILTER (WHERE b.version_no > 1)",
            records=(("edited", "Bills edited after issue"),),
        ),
        _bill(
            "cancelled_bills", "Cancelled bills", "number", "COUNT(*) FILTER (WHERE b.status = 'Cancelled')",
            records=(("cancelled", "Cancelled bills"),), part={"include_cancelled": True},
        ),
        # money still owed: a position today, so bars are the bills of each year
        _bill("outstanding", "Outstanding", "money", OPEN, records=(("owed", "Unpaid bills"),)),
        _bill(
            "overdue_90", "Overdue 90+ days", "money", f"COALESCE(SUM({BILL_OPEN}) FILTER (WHERE {BILL_AGE} > 90), 0)",
            records=(("overdue", "Bills over 90 days old"),),
        ),
        _bill("open_bills", "Unpaid bills", "number", f"COUNT(*) FILTER (WHERE {BILL_OPEN} >= 1)", records=(("owed", "Unpaid bills"),)),
        Measure("collected", "Cash collected", "money", one("collection", COLLECTED), COMMON, (("receipts", "Payments received"),)),
        Measure(
            "collection_rate", "Collection rate", "percent",
            {"c": Part("collection", SETTLED), "b": Part("bill", BILLED)},
            COMMON, (("receipts", "Payments received"), ("bills", "Bills")),
            combine=ratio("c", "b"), additive=False,
            note="Cash received plus the TDS clients held back, as a share of what was billed. A bar above 100% collected more than it billed.",
        ),
        Measure("tds_held", "TDS held back", "money", one("collection", TDS_HELD), COMMON, (("receipts", "Payments received"),)),
        _bill("credit_notes", "Credit notes", "money", CREDITED, records=(("bills", "Bills"),)),
        Measure("itc", "Input tax credit", "money", one("expense", ITC), (*COMMON, "expense_type", "is_regular", "status"), (("expenses", "Expenses"),)),
        Measure("expenses", "Operating expenses", "money", one("expense", EXPENSE), (*COMMON, "expense_type", "is_regular", "status"), (("expenses", "Expenses"),)),
        Measure("payroll", "Payroll", "money", one("payroll", SALARY), (*COMMON, "designation", "employee_type", "salary_paid"), (("payroll", "Payroll lines"),)),
        Measure(
            "salary_pending", "Salary pending", "money",
            one("payroll", "COALESCE(SUM(et.salary_amount) FILTER (WHERE et.salary_paid = 'No'), 0)"),
            (*COMMON, "designation", "employee_type"), (("payroll_pending", "Payroll lines not paid"),),
        ),
        Measure("days_worked", "Days worked", "number", one("payroll", "COALESCE(AVG(et.days_worked), 0)"), (*COMMON, "designation", "employee_type"), (("payroll", "Payroll lines"),), additive=False),
        Measure(
            "heads", "Staff on payroll", "number",
            one("payroll", "COALESCE(COUNT(*)::float / NULLIF(COUNT(DISTINCT et.month_year), 0), 0)"),
            (*COMMON, "designation", "employee_type"), (("payroll", "Payroll lines"),), additive=False,
        ),
        Measure(
            "cost", "Total cost", "money", {"p": Part("payroll", SALARY), "e": Part("expense", EXPENSE)}, COMMON,
            (("payroll", "Payroll lines"), ("expenses", "Expenses")), combine=lambda v: v["p"] + v["e"],
        ),
        Measure(
            "margin", "Operating margin", "money",
            {"r": Part("bill", REVENUE), "p": Part("payroll", SALARY), "e": Part("expense", EXPENSE)}, COMMON,
            (("bills", "Bills"), ("payroll", "Payroll lines"), ("expenses", "Expenses")), combine=lambda v: v["r"] - v["p"] - v["e"],
            note="Revenue less payroll and expenses. A case or domain shows its contribution margin: before head-office cost.",
        ),
        Measure(
            "margin_pct", "Operating margin %", "percent",
            {"r": Part("bill", REVENUE), "p": Part("payroll", SALARY), "e": Part("expense", EXPENSE)}, COMMON,
            (("bills", "Bills"), ("payroll", "Payroll lines"), ("expenses", "Expenses")),
            combine=lambda v: (v["r"] - v["p"] - v["e"]) / v["r"] * 100 if v["r"] else 0.0, additive=False,
        ),
        Measure(
            "payroll_pct", "Payroll share of revenue", "percent", {"r": Part("bill", REVENUE), "p": Part("payroll", SALARY)}, COMMON,
            (("payroll", "Payroll lines"), ("bills", "Bills")), combine=ratio("p", "r"), additive=False,
        ),
        Measure(
            "expense_pct", "Expense share of revenue", "percent", {"r": Part("bill", REVENUE), "e": Part("expense", EXPENSE)}, COMMON,
            (("expenses", "Expenses"), ("bills", "Bills")), combine=ratio("e", "r"), additive=False,
        ),
        Measure(
            "rev_per_head", "Revenue per employee", "money", {"r": Part("bill", REVENUE), "n": Part("payroll", "COUNT(*)")}, COMMON,
            (("bills", "Bills"), ("payroll", "Payroll lines")), combine=ratio("r", "n", 1.0), additive=False,
            note="Revenue for each employee-month on payroll.",
        ),
        Measure("km", "Kilometres", "number", one("fleet", KM), (*COMMON, "car_model", "driver"), (("fleet", "Car logs"),)),
        Measure("fleet_cost", "Fleet cost", "money", one("fleet", FLEET_COST), (*COMMON, "car_model", "driver"), (("fleet", "Car logs"),)),
        Measure(
            "cost_per_km", "Cost per km", "money",
            one("fleet", "COALESCE(SUM(ct.driven_km * COALESCE(car.per_km_price, 0)) / NULLIF(SUM(ct.driven_km), 0), 0)"),
            (*COMMON, "car_model", "driver"), (("fleet", "Car logs"),), additive=False,
        ),
        Measure("cars_active", "Cars on the road", "number", one("fleet", "COUNT(DISTINCT ct.car_code)"), (*COMMON, "car_model", "driver"), (("fleet", "Car logs"),), additive=False),
        Measure(
            "km_per_day", "Km per driving day", "number",
            one("fleet", "COALESCE(SUM(ct.driven_km) / NULLIF(COUNT(DISTINCT ct.driving_date), 0), 0)"),
            (*COMMON, "car_model", "driver"), (("fleet", "Car logs"),), additive=False,
        ),
        Measure("opps", "Opportunities", "number", one("opportunity", "COUNT(*)"), ("stage", "opp_type", "state", "business_domain", "capability"), (("opportunities", "Opportunities"),)),
        Measure(
            "won", "Won", "number", one("opportunity", "COUNT(*) FILTER (WHERE o.opportunity_status = 'Closed Won')"),
            ("opp_type", "state"), (("opportunities", "Opportunities"),),
        ),
        Measure(
            "win_rate", "Win rate", "percent",
            {"w": Part("opportunity", "COUNT(*) FILTER (WHERE o.opportunity_status = 'Closed Won')"),
             "d": Part("opportunity", f"COUNT(*) FILTER (WHERE o.opportunity_status IN {DECIDED_STAGES})")},
            ("opp_type", "state"), (("opportunities", "Opportunities"),), combine=ratio("w", "d"), additive=False,
        ),
        Measure(
            "open_pipeline", "Open opportunities", "number",
            one("opportunity", f"COUNT(*) FILTER (WHERE o.opportunity_status IN {OPEN_STAGES})"), ("stage", "opp_type", "state"),
            (("opportunities", "Opportunities"),),
        ),
        Measure(
            "pipeline_staff", "Staff to be hired", "number",
            one("opportunity", f"COALESCE(SUM(o.workers) FILTER (WHERE o.opportunity_status IN {OPEN_STAGES}), 0)"),
            ("stage", "opp_type", "state"), (("opportunities", "Opportunities"),),
        ),
        Measure(
            "cycle_days", "Days to decide", "number",
            one("opportunity", f"COALESCE(AVG(o.opportunity_end_date - o.opportunity_start_date) FILTER (WHERE o.opportunity_status IN {DECIDED_STAGES}), 0)"),
            ("stage", "opp_type", "state"), (("opportunities", "Opportunities"),), additive=False,
        ),
        Measure("emd_held", "EMD held by clients", "money", one("emd", f"COALESCE(SUM(e.emd_amount) FILTER (WHERE {_EMD_OPEN}), 0)"), COMMON, (("emds", "EMDs"),)),
        Measure(
            "emd_overdue", "EMD refund overdue", "money",
            one("emd", f"COALESCE(SUM(e.emd_amount) FILTER (WHERE {_EMD_OPEN} AND e.refund_due_date < CURRENT_DATE), 0)"), COMMON, (("emds", "EMDs"),),
        ),
        Measure("emd_lost", "EMD forfeited or deducted", "money", one("emd", f"COALESCE(SUM({_EMD_LOST}), 0)"), COMMON, (("emds", "EMDs"),)),
        Measure(
            "contact_follow_ups", "Follow-ups due", "number",
            one("contact", "COUNT(*) FILTER (WHERE ct.contact_status = 'Active' AND ct.next_follow_up_date <= CURRENT_DATE)"), COMMON,
            (("contacts", "Client contacts"),), trend=False,
        ),
        Measure(
            "headcount", "Employees", "number", one("employee", "COUNT(*) FILTER (WHERE emp.employee_status = 'Active')"),
            (*COMMON, "designation", "employee_type"), (("employees", "Employees"),), trend=False,
        ),
        Measure(
            "active_cases", "Active cases", "number", one("case", "COUNT(*) FILTER (WHERE c.case_status = 'Active')"), COMMON,
            (("cases", "Cases"),), trend=False,
        ),
        Measure(
            "run_rate", "Contracted monthly billing", "money",
            one("case", "COALESCE(SUM(c.monthly_expected_revenue) FILTER (WHERE c.case_status = 'Active'), 0)"), COMMON,
            (("cases", "Cases"),), trend=False,
        ),
    ]
}

def _context(key: str, records: tuple[tuple[str, str], ...], dataset: str, extra: tuple[str, ...], note: str, cancelled: bool = False) -> None:
    measure = MEASURES[key]
    MEASURES[key] = replace(measure, records=records, population={dataset: (extra, cancelled)}, population_note=note)


_OWED = f"{BILL_OPEN} >= 1"
_DECIDED = f"o.opportunity_status IN {DECIDED_STAGES}"
_OPEN = f"o.opportunity_status IN {OPEN_STAGES}"

_context("days_to_collect", (("bills", "Bills paid in full"),), "bills", (f"{BILL_OPEN} < 1", "p.last_received IS NOT NULL"), "Bills that have been paid in full: the ones this average is worked out from.")
_context("gst_unpaid", (("bills", "Bills with GST to mark paid"),), "bills", ("NOT b.gst_paid",), "Bills whose GST is not yet marked as paid.")
_context("epf_unpaid", (("bills", "Bills with EPFO to pay"),), "bills", ("b.epf_amount - COALESCE(b.epf_paid_amount, 0) > 0.004",), "Bills whose EPFO has not all been paid over.")
_context("esic_unpaid", (("bills", "Bills with ESIC to pay"),), "bills", ("b.esic_amount - COALESCE(b.esic_paid_amount, 0) > 0.004",), "Bills whose ESIC has not all been paid over.")
_context("edited_bills", (("bills", "Bills edited after issue"),), "bills", ("b.version_no > 1",), "Bills that are on version 2 or later.")
_context("cancelled_bills", (("bills", "Cancelled bills"),), "bills", ("b.status = 'Cancelled'",), "Bills that were cancelled. Their numbers stay on record.", cancelled=True)
_context("outstanding", (("bills", "Unpaid bills"),), "bills", (_OWED,), "Bills with a balance still to be received. The Owed column is that balance.")
_context("open_bills", (("bills", "Unpaid bills"),), "bills", (_OWED,), "Bills with a balance still to be received.")
_context("overdue_90", (("bills", "Bills over 90 days old"),), "bills", (_OWED, f"{BILL_AGE} > 90"), "Unpaid bills dated more than 90 days ago.")
_context("salary_pending", (("payroll", "Payroll lines not paid"),), "payroll", ("et.salary_paid = 'No'",), "Payroll lines whose salary is not yet marked paid.")
_context("won", (("opportunities", "Won opportunities"),), "opportunities", ("o.opportunity_status = 'Closed Won'",), "Only the opportunities that were won.")
_context("win_rate", (("opportunities", "Decided opportunities"),), "opportunities", (_DECIDED,), "The decided opportunities (won, lost or disqualified): the rate is the won ones out of these.")
_context("cycle_days", (("opportunities", "Decided opportunities"),), "opportunities", (_DECIDED,), "The decided opportunities the average is worked out from.")
_context("open_pipeline", (("opportunities", "Open opportunities"),), "opportunities", (_OPEN,), "Opportunities still being worked: Proposal, Qualified, Technical Bid or Financial Bid.")
_context("pipeline_staff", (("opportunities", "Open opportunities"),), "opportunities", (_OPEN,), "Open opportunities. The Workers column is the staff each would need.")
_context("emd_held", (("emds", "EMDs still to come back"),), "emds", (_EMD_OPEN,), "Deposits not yet refunded, adjusted or forfeited: the money still with the authority.")
_context("emd_overdue", (("emds", "EMDs past their refund due date"),), "emds", (_EMD_OPEN, "e.refund_due_date < CURRENT_DATE"), "Deposits still out whose refund due date has passed.")
_context("emd_lost", (("emds", "EMDs forfeited or deducted"),), "emds", ("(e.emd_status = 'Forfeited' OR COALESCE(e.deduction_amount, 0) > 0)",), "Deposits forfeited, or returned with a deduction.")
_context("contact_follow_ups", (("contacts", "Contacts due a follow-up"),), "contacts", ("ct.contact_status = 'Active'", "ct.next_follow_up_date <= CURRENT_DATE"), "Active contacts whose next follow-up date has come.")
_context("headcount", (("employees", "Active employees"),), "employees", ("emp.employee_status = 'Active'",), "Employees whose status is Active.")
_context("active_cases", (("cases", "Active cases"),), "cases", ("c.case_status = 'Active'",), "Cases whose status is Active.")
_context("run_rate", (("cases", "Active cases"),), "cases", ("c.case_status = 'Active'",), "Active cases. Expected per month is what each is meant to bill.")


def record_context(key: str, dataset: str) -> tuple[tuple[str, ...], bool]:
    """The conditions that make a row count towards a figure, for the rows opened from it. Cancelled rows never count unless
    the figure is about them, as on the dashboards."""
    return MEASURES[key].population.get(dataset, ((), False))


# A figure that is a position today, not a flow: the period filters do not narrow it.
SNAPSHOT = {"outstanding", "overdue_90", "open_bills", "headcount", "active_cases", "run_rate", "emd_held", "emd_overdue", "emd_lost", "contact_follow_ups"}


def _label(dim: str, code: Any, label: Any) -> str:
    if code in (None, ""):
        return UNALLOCATED
    return str(label if label not in (None, "") else code)


def _grouped(cur, part: Part, filters: dict[str, str], group: str, label: str, *, exclude: tuple[str, ...]) -> dict[str, tuple[str, float]]:
    where, params = clause(part.scope, filters, exclude=exclude, include_cancelled=part.include_cancelled, extra=part.extra)
    sql = f"SELECT {group}, {label}, {part.expr} FROM {SCOPES[part.scope]['from']}{where} GROUP BY 1, 2"
    return {("" if r[0] is None else str(r[0])): (r[1], num(r[2])) for r in rows(cur, sql, params)}


def _shared(measure: Measure, filters: dict[str, str]) -> dict[str, str]:
    scopes = sorted({p.scope for p in measure.parts.values()})
    return common(filters, *scopes) if len(scopes) > 1 else filters


def _combine(measure: Measure, values: dict[str, float]) -> float:
    return round(measure.combine({k: values.get(k, 0.0) for k in measure.parts}), 2)


def _by(cur, measure: Measure, filters: dict[str, str], dim_key: str, *, group: str, label: str, exclude: tuple[str, ...], fy_scope_key: str | None = None) -> list[dict[str, Any]]:
    """The measure for each value of a grouping, parts merged and combined."""
    flt = _shared(measure, filters)
    per_part: dict[str, dict[str, tuple[str, float]]] = {}
    for name, part in measure.parts.items():
        fields = SCOPES[part.scope]["fields"]
        g = fields[dim_key] if dim_key in fields else group
        lab = label if label else g
        per_part[name] = _grouped(cur, part, flt, g, lab, exclude=exclude)
    codes = set().union(*[set(d) for d in per_part.values()])
    out = []
    for code in codes:
        values = {n: per_part[n].get(code, ("", 0.0))[1] for n in measure.parts}
        name = next((per_part[n][code][0] for n in measure.parts if code in per_part[n] and per_part[n][code][0]), None)
        out.append({"code": code, "label": _label(dim_key, code, name), "value": _combine(measure, values)})
    return out


def _fy_label(code: str) -> str:
    return f"FY {code}-{str(int(code) + 1)[2:]}" if code.isdigit() else code


def _total(cur, measure: Measure, filters: dict[str, str]) -> float:
    flt = _shared(measure, filters)
    values = {}
    for name, part in measure.parts.items():
        where, params = clause(part.scope, flt, include_cancelled=part.include_cancelled, extra=part.extra)
        values[name] = num(rows(cur, f"SELECT {part.expr} FROM {SCOPES[part.scope]['from']}{where}", params)[0][0])
    return _combine(measure, values)


def explore(cur, key: str, filters: dict[str, str]) -> dict[str, Any]:
    measure = MEASURES[key]
    total = _total(cur, measure, filters)

    # The years: every year, with the selected one marked. A pick of a year or month is not applied to its own chart.
    years: list[dict[str, Any]] = []
    months: list[dict[str, Any]] = []
    if measure.trend:
        first = next(iter(measure.parts.values()))
        fy_code = SCOPES[first.scope]["fields"]["fy"]
        month_code = SCOPES[first.scope]["fields"]["month"]
        years = sorted(_by(cur, measure, filters, "fy", group=fy_code, label="", exclude=("fy", "month")), key=lambda r: r["code"])
        for r in years:
            r["label"] = _fy_label(r["code"])
        scoped = {k: v for k, v in filters.items() if k != "month"}
        months = sorted(_by(cur, measure, scoped, "month", group=month_code, label="", exclude=("month",)), key=lambda r: r["code"])
        months = [{**r, "label": month_label(r["code"])} for r in months if r["code"]][-MONTHS:]

    breakdowns = []
    for dim in measure.dims:
        first = next(iter(measure.parts.values()))
        fields = SCOPES[first.scope]["fields"]
        if dim not in fields:
            continue
        label_expr = NAME_EXPR.get(dim, "")
        items = _by(cur, measure, filters, dim, group=fields[dim], label=label_expr, exclude=(dim,))
        items = [i for i in items if i["value"] or measure.fmt == "percent"]
        items.sort(key=lambda r: abs(r["value"]), reverse=True)
        shown = items[:TOP]
        if measure.additive and total:
            for i in shown:
                i["share"] = round(i["value"] / total * 100, 1)
        if len(shown) > 1 or (shown and filters.get(dim)):
            breakdowns.append({"key": dim, "label": DIM_LABEL.get(dim, dim), "items": shown, "more": max(0, len(items) - TOP)})

    return {
        "measure": measure.key,
        "label": measure.label,
        "format": measure.fmt,
        "additive": measure.additive,
        "snapshot": key in SNAPSHOT,
        "note": measure.note,
        "total": total,
        "years": years,
        "months": months,
        "breakdowns": breakdowns,
        "records": [{"dataset": d, "label": label} for d, label in measure.records],
        "population_note": measure.population_note,
        "chips": filter_chips(cur, filters),
    }
