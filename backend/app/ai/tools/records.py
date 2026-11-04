"""Read tools over records, bills, receivables, documents, reminders, and arithmetic.

Records are read through the same functions the data screens use, with the same access check (operational data access).
An employee's Aadhaar, PAN and salary are never given to the assistant, even to someone who may see them on screen: they
are the application's private columns and a third-party model has no need of them.
"""

from __future__ import annotations

from typing import Any

from app import billing, documents, receivables
from app.ai import safety, store
from app.ai.tools.analytics import DIM_FILTERS, PERIOD_PROPS, _resolve_dimensions, _window
from app.ai.tools.core import READ, ToolContext, ToolError, ToolResult, tool
from app.auth import can_access_billing, can_access_documents, can_access_ods, can_access_orion_dashboard
from app.dashboard import records as dash_records
from app.dashboard.filters import clean_filters
from app.database import db_cursor
from app.db_utils import count_rows, fetch_by_id, fetch_preview, source_without
from app.entities import ENTITIES, locked_reason
from app.entity_service import hydrate_lookup_labels, serialize_record, serialize_value

ENTITY_NAMES = sorted(ENTITIES)
HIDDEN_COLUMNS = {"created_by", "last_updated_by", "record_deleted"}
MAX_COLUMNS = 14


def _entity(name: str) -> dict[str, Any]:
    if name not in ENTITIES:
        raise ToolError(f"There is no record type called '{name}'. Choose one of: {', '.join(ENTITY_NAMES)}.")
    return ENTITIES[name]


def _private(entity: dict[str, Any]) -> list[str]:
    return list(entity.get("private_columns") or [])


def _shown_columns(columns: list[str], entity: dict[str, Any]) -> list[str]:
    hidden = set(_private(entity)) | HIDDEN_COLUMNS
    keep = [c for c in columns if c not in hidden and not c.endswith("_timestamp")]
    return keep[:MAX_COLUMNS]


def _needs_ods(user: dict[str, Any]) -> bool:
    return can_access_ods(user)


# --------------------------------------------------------------------------------------------------------- records


@tool(
    name="search_records",
    label="Searching records",
    kind=READ,
    needs=_needs_ods,
    entity_arg="entity",
    description=(
        "Searches one kind of operational record (clients, cases, employees, opportunities, transactions ...) by any text in it, and "
        "returns the matching rows. Use it to find a record's code or to list records. Record types: " + ", ".join(ENTITY_NAMES) + "."
    ),
    schema={"properties": {
        "entity": {"type": "string", "enum": ENTITY_NAMES},
        "query": {"type": "string", "maxLength": 100, "description": "Words to look for. Leave empty for the latest records."},
        "limit": {"type": "integer", "minimum": 1, "maximum": 20},
    }, "required": ["entity"]},
)
def search_records(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    entity = _entity(args["entity"])
    private = _private(entity)
    cols, rows, matched = fetch_preview(entity["table"], args.get("limit", 10), search=args.get("query") or None,
                                        source_sql=source_without(entity["table"], private) if private else None)
    shown = _shown_columns(cols, entity)
    items = [{c: serialize_value(row[cols.index(c)]) for c in shown} for row in rows]
    total = count_rows(entity["table"])
    ctx.block("table", title=f"{args['entity']} records", columns=[{"key": c, "label": c.replace("_", " ").capitalize()} for c in shown[:6]], rows=[{c: i.get(c) for c in shown[:6]} for i in items])
    block_id = f"b{len(ctx.blocks)}"
    ctx.source(f"{args['entity']} records", f"{matched:,} of {total:,} match" if args.get("query") else f"{total:,} records", None)
    data = {"record_type": args["entity"], "primary_key": entity["primary_key"], "matched": matched, "total_records": total, "showing": len(items), "records": items,
            "private_fields_withheld": private or None, "blocks": [{"id": block_id, "shows": "the matching records as a table"}]}
    return ToolResult(data, f"Found {matched:,} {args['entity']} record(s)")


@tool(
    name="get_record",
    label="Opening a record",
    kind=READ,
    needs=_needs_ods,
    entity_arg="entity",
    description="One record in full, by its code (for example CL-0003 for a client). Gives every field except private ones, with names for linked records.",
    schema={"properties": {"entity": {"type": "string", "enum": ENTITY_NAMES}, "id": {"type": "string", "maxLength": 60}}, "required": ["entity", "id"]},
)
def get_record(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    entity = _entity(args["entity"])
    found = fetch_by_id(entity["table"], args["id"], entity["primary_key"])
    if not found:
        raise ToolError(f"There is no {args['entity']} with the code {args['id']}.")
    reason = locked_reason(args["entity"], found)
    record = hydrate_lookup_labels(entity, serialize_record(found))
    labels = record.pop("__labels", {})
    shown = {k: v for k, v in record.items() if k not in set(_private(entity)) | HIDDEN_COLUMNS and not str(k).startswith("__")}
    ctx.source(f"{args['entity']} {args['id']}", "Operational data", None)
    data = {"record_type": args["entity"], "id": args["id"], "fields": shown, "linked_names": labels or None, "locked": reason or None, "private_fields_withheld": _private(entity) or None}
    return ToolResult(data, f"Opened {args['entity']} {args['id']}")


@tool(
    name="count_records",
    label="Counting records",
    kind=READ,
    needs=_needs_ods,
    entity_arg="entity",
    description="How many records of a kind there are, optionally matching some words.",
    schema={"properties": {"entity": {"type": "string", "enum": ENTITY_NAMES}, "query": {"type": "string", "maxLength": 100}}, "required": ["entity"]},
)
def count_records(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    entity = _entity(args["entity"])
    private = _private(entity)
    _cols, _rows, matched = fetch_preview(entity["table"], 1, search=args.get("query") or None, source_sql=source_without(entity["table"], private) if private else None)
    total = count_rows(entity["table"])
    ctx.source(f"{args['entity']} records", "Operational data", None)
    return ToolResult({"record_type": args["entity"], "total": total, "matching": matched if args.get("query") else total}, f"Counted {args['entity']} records")


# --------------------------------------------------------------------------------------- records behind figures

DATASET_NAMES = sorted(dash_records.DATASETS)


@tool(
    name="get_records_behind_figures",
    label="Opening the rows behind the figures",
    kind=READ,
    needs=can_access_orion_dashboard,
    description=(
        "The rows behind the dashboard figures, with the same period and filters: bills, unpaid bills (owed), bills over 90 days (overdue), "
        "revenue entries, employees, payroll lines, opportunities and more. Use this to list the actual bills or items. Sets: "
        + ", ".join(DATASET_NAMES)
        + "."
    ),
    schema={"properties": {
        "dataset": {"type": "string", "enum": DATASET_NAMES},
        **PERIOD_PROPS, "filters": DIM_FILTERS,
        "query": {"type": "string", "maxLength": 100},
        "size": {"type": "integer", "minimum": 1, "maximum": 25},
    }, "required": ["dataset"]},
    entity_arg="dataset",
)
def get_records_behind_figures(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    name = args["dataset"]
    if not dash_records.allowed(name, ctx.user):
        raise ToolError("Opening these records needs access to operational data or billing, which this person does not have.")
    window = _window(args, ctx, "all_time")
    with db_cursor() as cur:
        dims, notes = _resolve_dimensions(cur, args.get("filters"))
        out = dash_records.fetch(cur, name, clean_filters({**dims, **window.filters}), q=args.get("query") or "", sort=None, direction=None, page=1, size=args.get("size", 15))
    columns = [{"key": c["key"], "label": c["label"], "align": "right" if c.get("kind") in ("money", "number") else "left"} for c in out["columns"][:7]]
    rows = [{c["key"]: row.get(c["key"]) for c in columns} for row in out["rows"]]
    table = ctx.block("table", title=f"{out['label']}", columns=[{**c, "format": ("inr" if c["key"] in ("taxable", "billed", "gst", "received", "open") else None)} for c in columns], rows=rows,
                      link=None)
    ctx.source(out["label"], f"{window.label} · {out['total']:,} records", None)
    shown = [{k: v for k, v in row.items() if not str(k).startswith("_")} for row in out["rows"]]
    data = {"dataset": name, "label": out["label"], "period": window.label, "filter_notes": notes, "total_matching": out["total"], "totals": out.get("totals"), "showing": len(shown), "rows": shown,
            "truncated": out["total"] > len(shown), "blocks": [{"id": table, "shows": "the rows as a table"}]}
    return ToolResult(data, f"Opened {out['label'].lower()}: {out['total']:,} record(s)")


# --------------------------------------------------------------------------------------------- bills and money


@tool(
    name="get_receivables",
    label="Checking what is owed",
    kind=READ,
    needs=can_access_billing,
    description="Money owed to the company by client right now, with ageing (0-30, 31-60, 61-90, 90+ days) and the unpaid bills of each. Use for 'who owes us', 'what is overdue', 'who should we remind'.",
    schema={"properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 20}, "client": {"type": "string", "maxLength": 80, "description": "Only this client (code or exact name)."}}},
)
def get_receivables(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    report = receivables.list_receivables()
    clients = report["clients"]
    if args.get("client"):
        with db_cursor() as cur:
            dims, _notes = _resolve_dimensions(cur, {"client": args["client"]})
        clients = [c for c in clients if c["client_code"] == dims.get("client")]
    labels = [str(x) for x in report["bucket_labels"]]
    top = clients[: args.get("limit", 10)]
    rows = [{"client": c["client_name"], "owed": c["total"], "oldest_days": c["oldest_days"], "unpaid_bills": len(c["bills"]), "over_90": c["buckets"][-1]} for c in top]
    table = ctx.block("table", title="Who owes us", columns=[{"key": "client", "label": "Client"}, {"key": "owed", "label": "Owed", "format": "inr", "align": "right"}, {"key": "over_90", "label": "Over 90 days", "format": "inr", "align": "right"},
                                                          {"key": "oldest_days", "label": "Oldest (days)", "align": "right"}], rows=rows, link="/utility/receivables")
    chart = ctx.block("chart", title="Receivables by age", type="bar", unit="inr", x=labels, series=[{"name": "Owed", "values": report["totals"]["buckets"]}], link="/utility/receivables")
    ctx.source("Receivables", f"As of {report['as_of']} · {report['totals']['bills']} unpaid bills", "/utility/receivables")
    data = {"as_of": report["as_of"], "ageing_buckets": labels, "totals": report["totals"], "clients": [
        {"code": c["client_code"], "client": c["client_name"], "total_owed": c["total"], "by_age": dict(zip(labels, c["buckets"])), "oldest_days": c["oldest_days"], "unpaid_bills": len(c["bills"]),
         "last_reminder": c.get("last_reminder"), "bills": [{"number": b["bill_number"], "date": b["bill_date"], "balance": b["balance"], "days": b["days"], "id": b["id"]} for b in c["bills"][:6]]} for c in top],
        "blocks": [{"id": table, "shows": "who owes the most"}, {"id": chart, "shows": "owed money by age"}]}
    return ToolResult(data, f"Retrieved receivables: {report['totals']['bills']} unpaid bill(s)")


@tool(
    name="list_bills",
    label="Looking up bills",
    kind=READ,
    needs=can_access_billing,
    description="Bills (tax invoices) with number, date, party, amount, status. Search by bill number, client, case or reference, and filter by financial year start (for example 2026 for FY 2026-27).",
    schema={"properties": {"search": {"type": "string", "maxLength": 100}, "fy_start_year": {"type": "integer", "minimum": 2000, "maximum": 2100}, "limit": {"type": "integer", "minimum": 1, "maximum": 25}}},
)
def list_bills(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    bills = billing.list_bills(args.get("fy_start_year"), args.get("search"), args.get("limit", 12))
    slim = [{"id": b.get("id") or b.get("bill_code"), "number": b.get("bill_number"), "date": b.get("bill_date"), "party": b.get("party_name"), "case": b.get("case_name"), "total": b.get("grand_total"), "status": b.get("status"),
             "received": b.get("received"), "balance": b.get("balance")} for b in bills]
    table = ctx.block("table", title="Bills", columns=[{"key": "number", "label": "Bill", "format": "bill"}, {"key": "date", "label": "Date"}, {"key": "party", "label": "Party"}, {"key": "total", "label": "Total", "format": "inr", "align": "right"}, {"key": "status", "label": "Status"}],
                      rows=slim, link="/utility/billing")
    ctx.source("Billing", f"{len(slim)} bill(s) shown", "/utility/billing")
    return ToolResult({"bills": slim, "showing": len(slim), "blocks": [{"id": table, "shows": "the bills table"}]}, f"Found {len(slim)} bill(s)")


@tool(
    name="get_bills_to_raise",
    label="Checking which bills are due",
    kind=READ,
    needs=can_access_billing,
    description="Cases that were billed before but have no bill yet for a month (default: last month). Use for 'what do I still need to bill'.",
    schema={"properties": {"month": {"type": "string", "pattern": r"\d{4}-\d{2}", "description": "The service month, YYYY-MM."}}},
)
def get_bills_to_raise(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    try:
        due = billing.list_due_to_bill(args.get("month"))
    except billing.BillError as exc:
        raise ToolError(str(exc)) from exc
    cases = [{"case": c["case_name"], "client": c["client_name"], "last_billed_month": c["service_month"][:7], "last_amount": c["grand_total"], "months_behind": c["months_behind"]} for c in due["cases"]]
    table = ctx.block("table", title=f"Not yet billed for {due['month']}", columns=[{"key": "case", "label": "Case"}, {"key": "client", "label": "Client"}, {"key": "last_amount", "label": "Last bill", "format": "inr", "align": "right"},
                                                                                {"key": "months_behind", "label": "Months behind", "align": "right"}], rows=cases, link="/utility/due")
    ctx.source("Monthly billing", f"Service month {due['month']}", "/utility/due")
    return ToolResult({"service_month": due["month"], "count": len(cases), "cases": cases, "blocks": [{"id": table, "shows": "cases still to bill"}]}, f"{len(cases)} case(s) still to bill for {due['month']}")


# -------------------------------------------------------------------------------------------------- documents


def _see_confidential(user: dict[str, Any]) -> bool:
    return documents.can_see_confidential(user)


@tool(
    name="search_documents",
    label="Searching documents",
    kind=READ,
    needs=can_access_documents,
    description="Finds documents in the Document Center by words in the title, tags or the text inside, optionally in one place (company, a case or a client), by status or by expiry.",
    schema={"properties": {
        "query": {"type": "string", "maxLength": 120},
        "scope": {"type": "string", "enum": ["company", "case", "client"]},
        "case_code": {"type": "string", "maxLength": 40}, "client_code": {"type": "string", "maxLength": 40},
        "expiry": {"type": "string", "enum": ["expired", "expiring", "valid", "none"]},
        "limit": {"type": "integer", "minimum": 1, "maximum": 20},
    }},
)
def search_documents(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    filters = {k: args[k] for k in ("scope", "case_code", "client_code", "expiry") if args.get(k)}
    if args.get("query"):
        filters["q"] = args["query"]
    try:
        found = documents.search_documents(filters, _see_confidential(ctx.user), args.get("limit", 10), 0)
    except documents.DocumentCenterError as exc:
        raise ToolError(str(exc)) from exc
    items = [{"id": d["id"], "code": d["code"], "title": d["title"], "category": d["category"], "place": d["case_name"] or d["client_name"] or "Company", "status": d["status"], "expires": d["expiry_date"], "expiry_state": d["expiry_state"]} for d in found["items"]]
    table = ctx.block("table", title="Documents", columns=[{"key": "title", "label": "Document"}, {"key": "place", "label": "Belongs to"}, {"key": "expires", "label": "Expires", "align": "right"}], rows=items, link="/documents")
    ctx.source("Document Center", f"{found['total']:,} document(s) match", "/documents")
    return ToolResult({"total_matching": found["total"], "documents": items, "blocks": [{"id": table, "shows": "the documents"}]}, f"Found {found['total']} document(s)")


@tool(
    name="get_document_alerts",
    label="Checking document expiry",
    kind=READ,
    needs=can_access_documents,
    description="Documents that have expired or will expire soon, and how many documents there are. Use for 'what is expiring', 'any licences about to lapse'.",
)
def get_document_alerts(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    ov = documents.overview(_see_confidential(ctx.user))
    pick = lambda d: {"code": d["code"], "title": d["title"], "place": d["case_name"] or d["client_name"] or "Company", "expires": d["expiry_date"], "state": d["expiry_state"]}  # noqa: E731
    expired, soon = [pick(d) for d in ov["expired_documents"]], [pick(d) for d in ov["expiring_documents"]]
    table = ctx.block("table", title="Expired and expiring documents", columns=[{"key": "title", "label": "Document"}, {"key": "place", "label": "Belongs to"}, {"key": "expires", "label": "Expires", "align": "right"}, {"key": "state", "label": ""}],
                      rows=expired + soon, link="/documents?view=all&expiry=expired")
    ctx.source("Document Center", f"{ov['total']:,} documents", "/documents")
    return ToolResult({"documents_total": ov["total"], "expired_count": ov["expired"], "expiring_count": ov["expiring"], "expired": expired, "expiring_soon": soon, "blocks": [{"id": table, "shows": "documents needing attention"}]},
                      f"{ov['expired']} expired, {ov['expiring']} expiring")


# ----------------------------------------------------------------------------------------- reminders, sums


@tool(
    name="get_reminders",
    label="Reading your reminders",
    kind=READ,
    needs=lambda user: True,
    description="The person's own open reminders and tasks.",
)
def get_reminders(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    tasks = store.list_tasks(ctx.user["id"], "open", 30)
    items = [{"id": t["id"], "kind": t["kind"], "title": t["title"], "due": t["due_at"]} for t in tasks]
    return ToolResult({"open": items, "count": len(items)}, f"{len(items)} open reminder(s) and task(s)")


@tool(
    name="calculate",
    label="Calculating",
    kind=READ,
    needs=lambda user: True,
    description=(
        "Does arithmetic exactly: + - * / % ** and brackets, abs, round, min, max. Use it for any sum, difference, percentage or ratio of figures you "
        "have retrieved, instead of working it out yourself. Put plain numbers in the expression (no ₹ signs or commas), for example (125000-110000)/110000*100."
    ),
    schema={"properties": {"expression": {"type": "string", "maxLength": 300}, "meaning": {"type": "string", "maxLength": 160, "description": "What the result is, in a few words."}}, "required": ["expression"]},
)
def calculate(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    try:
        value = safety.safe_calc(args["expression"])
    except safety.CalcError as exc:
        raise ToolError(str(exc)) from exc
    return ToolResult({"expression": args["expression"], "result": round(value, 4), "meaning": args.get("meaning")}, "Calculated")
