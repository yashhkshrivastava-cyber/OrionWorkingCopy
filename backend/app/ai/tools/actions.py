"""Tools that do something: keep a reminder, change a record, make a file, send an email, open a page.

How much care each one gets depends on what it can do:

* **ui**    open a page or switch the appearance. Nothing is written; the browser does it.
* **low**   keep a reminder or task, make an export or report for the person who asked. Done at once, shown, and removable.
* **medium / high**   create, change or delete a record, email a file. The assistant only *prepares* these. The person sees
  exactly what will happen (worked out here from the checked arguments, not from what the model said) and must confirm it
  on screen. Delete and email are marked high and shown in red.

Records are changed only through ``entity_service``, the code the data screens use, so every rule there applies.
"""

from __future__ import annotations

import csv
import io
import re
from datetime import datetime, time as dtime
from typing import Any

from app import entity_service, mail, receivables, xlsx_io
from app.ai import reports, store
from app.ai.tools import analytics
from app.ai.tools.analytics import DIM_FILTERS, PERIOD_PROPS, _resolve_dimensions, _window
from app.ai.tools.core import READ, UI, WRITE, ToolContext, ToolError, ToolResult, tool
from app.ai.tools.records import ENTITY_NAMES, _entity, _private, _shown_columns
from app.auth import (
    can_access_bank,
    can_access_billing,
    can_access_documents,
    can_access_ods,
    can_access_orion_dashboard,
    can_write_ods,
    is_admin,
)
from app.dashboard import VIEWS, view_allowed
from app.dashboard import records as dash_records
from app.dashboard.filters import clean_filters
from app.database import db_cursor
from app.db_utils import fetch_by_id, fetch_preview, source_without
from app.entities import locked_reason
from app.entity_service import EntityError, serialize_value

MAX_EXPORT_ROWS = 5000

# The themes the browser knows (frontend/src/theme/themes.ts). A test keeps this list in step with that file.
THEME_IDS = ["default", "midnight", "aurora", "obsidian", "ivory", "flux", "lumen", "lumen-ocean", "lumen-sunrise"]


# ---------------------------------------------------------------------------------------- reminders and tasks


def _page_link(ctx: ToolContext) -> str | None:
    path = ctx.page.get("path")
    if not path:
        return None
    filters = ctx.page.get("filters")
    if filters and "?" not in path:
        from urllib.parse import urlencode

        path += "?" + urlencode(filters)
    return path[:300]


@tool(
    name="create_reminder_or_task",
    label="Setting a reminder",
    kind=WRITE,
    risk="low",
    needs=lambda user: True,
    description=(
        "Keeps a reminder (it shows up at the time you give) or a task (a to-do) for the person. It is private to them. Use it for 'remind me', "
        "'set up a reminder for this', 'create a task'. If they say 'this' and are on a page, set link_to_current_page."
    ),
    schema={"properties": {
        "kind": {"type": "string", "enum": ["reminder", "task"]},
        "title": {"type": "string", "minLength": 3, "maxLength": 160},
        "note": {"type": "string", "maxLength": 600},
        "due_date": {"type": "string", "pattern": r"\d{4}-\d{2}-\d{2}", "description": "The date it is due (YYYY-MM-DD). Work it out from today's date."},
        "due_time": {"type": "string", "pattern": r"\d{2}:\d{2}", "description": "The time (24-hour HH:MM). Defaults to 09:00."},
        "link_to_current_page": {"type": "boolean", "description": "Open the page the person is on when they follow the reminder."},
    }, "required": ["kind", "title"]},
)
def create_reminder_or_task(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    due = None
    if args.get("due_date"):
        try:
            hour, minute = (int(x) for x in (args.get("due_time") or "09:00").split(":"))
            due = datetime.combine(datetime.fromisoformat(args["due_date"]).date(), dtime(hour, minute)).astimezone()
        except ValueError as exc:
            raise ToolError("That date or time is not valid.") from exc
        if due.year < 2000 or due.year > 2100:
            raise ToolError("That date is out of range.")
    if args["kind"] == "reminder" and due is None:
        raise ToolError("A reminder needs a date. Ask the person when they want to be reminded.")
    task = store.create_task(ctx.user["id"], args["kind"], args["title"], args.get("note"), due, _page_link(ctx) if args.get("link_to_current_page") else None, ctx.conversation_id)
    block = ctx.block("task", id=task["id"], task_kind=task["kind"], title=task["title"], due=task["due_at"], link=task["link"])
    return ToolResult({"created": {"id": task["id"], "kind": task["kind"], "title": task["title"], "due": task["due_at"]}, "blocks": [{"id": block, "shows": "the reminder card"}]},
                      f"Saved a {args['kind']}: {task['title']}")


# ---------------------------------------------------------------------------------------------- record rules


def _write_ok(user: dict[str, Any]) -> bool:
    return can_write_ods(user)


def _form_fields(entity: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return entity["form_fields"]


def _lookup(cfg: dict[str, Any], value: str) -> str:
    """A linked record given by name becomes its code. Several matches, or none, is a question for the person."""
    table, pk, display = cfg["source_table"], cfg.get("source_pk_column", "id"), cfg["source_display_column"]
    with db_cursor() as cur:
        cur.execute(f"SELECT {pk}, {display} FROM {table} WHERE {pk}::text = %s OR lower({display}) = lower(%s) LIMIT 5", (value, value))
        rows = cur.fetchall()
        if not rows:
            cur.execute(f"SELECT {pk}, {display} FROM {table} WHERE {display} ILIKE %s ORDER BY 2 LIMIT 5", ("%" + value.replace("%", "") + "%",))
            rows = cur.fetchall()
    if not rows:
        raise ToolError(f"I could not find '{value}'. Check the name or code.")
    if len(rows) > 1:
        raise ToolError("'" + value + "' matches more than one: " + "; ".join(f"{name} ({code})" for code, name in rows) + ". Ask which one is meant.")
    return str(rows[0][0])


def _prepare_fields(entity_name: str, fields: dict[str, Any]) -> dict[str, Any]:
    entity = _entity(entity_name)
    form = _form_fields(entity)
    private = set(_private(entity))
    prepared: dict[str, Any] = {}
    for key, value in fields.items():
        if key in private:
            raise ToolError(f"{form.get(key, {}).get('label', key)} is a private field. I do not handle those; use the {entity_name} screen.")
        if key not in form:
            raise ToolError(f"{entity_name} has no field '{key}'. Its fields are: " + ", ".join(f"{k} ({v.get('label', k)})" for k, v in form.items()) + ".")
        cfg = form[key]
        prepared[key] = _lookup(cfg, str(value)) if cfg.get("source_table") and value not in (None, "") else value
    return prepared


def _label_for(entity: dict[str, Any], record: dict[str, Any]) -> str:
    return str(record.get(entity["display_column"]) or record.get(entity["primary_key"]) or "")


def _show(entity: dict[str, Any], key: str, value: Any) -> str:
    cfg = _form_fields(entity).get(key, {})
    if value in (None, ""):
        return "—"
    if cfg.get("source_table"):
        from app.db_utils import fetch_display_label

        label = fetch_display_label(cfg["source_table"], cfg["source_display_column"], cfg.get("source_pk_column", "id"), value, from_sql=cfg.get("source_from"))
        return f"{label} ({value})" if label else str(value)
    if isinstance(value, bool):
        return "Yes" if value else "No"
    return str(serialize_value(value))


def _field_rows(entity: dict[str, Any], values: dict[str, Any], before: dict[str, Any] | None = None) -> list[dict[str, str]]:
    rows = []
    for key, value in values.items():
        label = _form_fields(entity).get(key, {}).get("label", key)
        row = {"label": label, "value": _show(entity, key, value)}
        if before is not None:
            row["before"] = _show(entity, key, before.get(key))
        rows.append(row)
    return rows


def _refuse(exc: EntityError) -> ToolError:
    return ToolError(exc.message)


@tool(
    name="get_record_fields",
    label="Checking what a record needs",
    kind=READ,
    needs=can_access_ods,
    description="The fields of a kind of record: their names (keys), labels, types, allowed values and which are required. Call this before creating or changing a record so you use the right keys.",
    schema={"properties": {"entity": {"type": "string", "enum": ENTITY_NAMES}}, "required": ["entity"]},
    entity_arg="entity",
)
def get_record_fields(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    entity = _entity(args["entity"])
    private = set(_private(entity))
    fields = [
        {"key": k, "label": v.get("label", k), "type": v.get("type"), "required": bool(v.get("required")), "options": v.get("options"), "linked_to": v.get("source_table")}
        for k, v in _form_fields(entity).items() if k not in private
    ]
    return ToolResult({"record_type": args["entity"], "primary_key": entity["primary_key"], "fields": fields, "dates": "YYYY-MM-DD", "linked_fields": "give the linked record's name or code"}, f"Looked up the {args['entity']} fields")


# ------------------------------------------------------------------------------------------ create/change/delete


@tool(
    name="create_record",
    label="Preparing a new record",
    kind=WRITE,
    risk="medium",
    confirm=True,
    needs=_write_ok,
    entity_arg="entity",
    description=(
        "Prepares a new record (client, case, opportunity, employee ...). Nothing is saved until the person confirms on screen. "
        "Call get_record_fields first to use the right keys. For a linked field (a case's client) give the name or code."
    ),
    schema={"properties": {"entity": {"type": "string", "enum": ENTITY_NAMES}, "fields": {"type": "object", "description": "Field key to value."}}, "required": ["entity", "fields"]},
)
def _create_record_run(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    _entity(args["entity"])
    try:
        code = entity_service.create(args["entity"], args["fields"], ctx.user["id"])
    except EntityError as exc:
        raise _refuse(exc) from exc
    return ToolResult({"created": args["entity"], "id": code}, f"Created {args['entity']} {code}")


def _prepare_create(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    entity = _entity(args["entity"])
    prepared = _prepare_fields(args["entity"], args["fields"])
    try:
        cleaned = entity_service.validate(entity, prepared)
    except EntityError as exc:
        raise _refuse(exc) from exc
    if not cleaned:
        raise ToolError("No values were given.")
    args["fields"] = prepared
    rows = _field_rows(entity, cleaned)
    try:
        for match in entity_service.possible_duplicates(args["entity"], prepared)[:2]:
            rows.append({"label": "Possible duplicate", "value": match["note"]})
    except EntityError:
        pass  # the refusal that matters was given above; this is only a warning
    return {"title": f"Create a new {args['entity']}", "rows": rows, "danger": False, "confirm_label": "Create"}


@tool(
    name="update_record",
    label="Preparing a change",
    kind=WRITE,
    risk="medium",
    confirm=True,
    needs=_write_ok,
    entity_arg="entity",
    description="Prepares a change to an existing record by its code. Only the fields in 'changes' are altered. Nothing is saved until the person confirms on screen, where they see before and after.",
    schema={"properties": {"entity": {"type": "string", "enum": ENTITY_NAMES}, "id": {"type": "string", "maxLength": 60}, "changes": {"type": "object", "description": "Field key to new value."}}, "required": ["entity", "id", "changes"]},
)
def _update_record_run(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    try:
        entity_service.change(args["entity"], args["id"], args["changes"], ctx.user["id"])
    except EntityError as exc:
        raise _refuse(exc) from exc
    return ToolResult({"updated": args["entity"], "id": args["id"]}, f"Updated {args['entity']} {args['id']}")


def _prepare_update(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    entity = _entity(args["entity"])
    existing = fetch_by_id(entity["table"], args["id"], entity["primary_key"])
    if not existing:
        raise ToolError(f"There is no {args['entity']} with the code {args['id']}.")
    reason = locked_reason(args["entity"], existing)
    if reason:
        raise ToolError(reason)
    prepared = _prepare_fields(args["entity"], args["changes"])
    try:
        cleaned = entity_service.validate(entity, prepared, for_update=True, existing=existing)
    except EntityError as exc:
        raise _refuse(exc) from exc
    differing = {k: v for k, v in cleaned.items() if serialize_value(existing.get(k)) != serialize_value(v) and str(existing.get(k)) != str(v)}
    if not differing:
        raise ToolError("Those values are already what the record has, so nothing would change.")
    args["changes"] = {k: v for k, v in prepared.items() if k in differing}
    return {"title": f"Change {args['entity']} {_label_for(entity, existing)} ({args['id']})", "rows": _field_rows(entity, differing, existing), "danger": False, "confirm_label": "Save changes"}


@tool(
    name="delete_record",
    label="Preparing a deletion",
    kind=WRITE,
    risk="high",
    confirm=True,
    needs=_write_ok,
    entity_arg="entity",
    description="Prepares the deletion of ONE record by its code. This cannot be undone. Nothing is deleted until the person confirms on screen. There is no way to delete many records at once; refuse requests to delete everything or many things.",
    schema={"properties": {"entity": {"type": "string", "enum": ENTITY_NAMES}, "id": {"type": "string", "maxLength": 60}}, "required": ["entity", "id"]},
)
def _delete_record_run(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    try:
        entity_service.remove(args["entity"], args["id"], ctx.user["id"])
    except EntityError as exc:
        raise _refuse(exc) from exc
    return ToolResult({"deleted": args["entity"], "id": args["id"]}, f"Deleted {args['entity']} {args['id']}")


def _prepare_delete(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    entity = _entity(args["entity"])
    existing = fetch_by_id(entity["table"], args["id"], entity["primary_key"])
    if not existing:
        raise ToolError(f"There is no {args['entity']} with the code {args['id']}.")
    reason = locked_reason(args["entity"], existing)
    if reason:
        raise ToolError(reason)
    shown = {k: v for k, v in existing.items() if k in _shown_columns(list(existing), entity)}
    rows = [{"label": k.replace("_", " ").capitalize(), "value": str(serialize_value(v))} for k, v in list(shown.items())[:8] if v not in (None, "")]
    return {"title": f"Delete {args['entity']} {_label_for(entity, existing)} ({args['id']})", "rows": rows, "danger": True, "warning": "This cannot be undone.", "confirm_label": "Delete"}


# ------------------------------------------------------------------------------------------------- files


def _rows_for_export(ctx: ToolContext, args: dict[str, Any]) -> tuple[str, list[str], list[list[Any]], str]:
    """(title, header, rows, source description). Uses the same access rules as the screens' own exports."""
    limit = min(args.get("limit", 1000), MAX_EXPORT_ROWS)
    if args.get("dataset"):
        name = args["dataset"]
        if name not in dash_records.DATASETS or not can_access_orion_dashboard(ctx.user) or not dash_records.allowed(name, ctx.user):
            raise ToolError("You do not have access to export that.")
        window = _window(args, ctx, "all_time")
        with db_cursor() as cur:
            dims, _notes = _resolve_dimensions(cur, args.get("filters"))
            out = dash_records.fetch(cur, name, clean_filters({**dims, **window.filters}), q=args.get("query") or "", sort=None, direction=None, page=1, size=limit, export=True)
        header = [c["label"] for c in out["columns"]]
        rows = [[row.get(c["key"]) for c in out["columns"]] for row in out["rows"][:limit]]
        return out["label"], header, rows, f"{out['label']} · {window.label}"
    if args.get("entity"):
        if not can_access_ods(ctx.user):
            raise ToolError("You do not have access to export operational records.")
        entity = _entity(args["entity"])
        private = _private(entity)
        cols, data, matched = fetch_preview(entity["table"], limit, search=args.get("query") or None, source_sql=source_without(entity["table"], private) if private else None)
        shown = _shown_columns(cols, entity)
        rows = [[serialize_value(row[cols.index(c)]) for c in shown] for row in data]
        return args["entity"], [c.replace("_", " ").capitalize() for c in shown], rows, f"{args['entity']} records · {matched:,} match"
    raise ToolError("Say what to export: a record type (entity) or one of the dashboard record sets (dataset).")


@tool(
    name="export_data",
    label="Preparing the export",
    kind=WRITE,
    risk="low",
    needs=lambda user: can_access_ods(user) or can_access_orion_dashboard(user),
    description=(
        "Makes a downloadable file (Excel or CSV) of records for the person: either a kind of record (entity), or one of the dashboard record sets (dataset) "
        "for a period and filters. At most 5,000 rows. Private fields are never included."
    ),
    schema={"properties": {
        "entity": {"type": "string", "enum": ENTITY_NAMES},
        "dataset": {"type": "string", "enum": sorted(dash_records.DATASETS)},
        "format": {"type": "string", "enum": ["xlsx", "csv"]},
        **PERIOD_PROPS, "filters": DIM_FILTERS,
        "query": {"type": "string", "maxLength": 100},
        "limit": {"type": "integer", "minimum": 1, "maximum": MAX_EXPORT_ROWS},
    }},
)
def export_data(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    title, header, rows, source = _rows_for_export(ctx, args)
    if not rows:
        raise ToolError("There is nothing to export for that selection.")
    fmt = args.get("format", "xlsx")
    stamp = ctx.today.strftime("%Y%m%d")
    base = re.sub(r"[^A-Za-z0-9]+", "_", title).strip("_").lower() or "export"
    if fmt == "csv":
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(header)
        writer.writerows(rows)
        data, content_type, name = ("﻿" + buffer.getvalue()).encode("utf-8"), "text/csv; charset=utf-8", f"{base}_{stamp}.csv"
    else:
        data = xlsx_io.write_xlsx({title[:30] or "Export": [header, *rows]})
        content_type, name = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", f"{base}_{stamp}.xlsx"
    file_id = store.save_file(ctx.user["id"], name, content_type, data)
    block = ctx.block("file", id=file_id, name=name, size=len(data), url=f"/api/ai/files/{file_id}", format=fmt, rows=len(rows), description=source)
    ctx.source(source, f"{len(rows):,} row(s) exported", None)
    return ToolResult({"file": {"id": file_id, "name": name, "rows": len(rows), "format": fmt}, "blocks": [{"id": block, "shows": "the download card"}]}, f"Prepared {name} ({len(rows):,} rows)")


@tool(
    name="generate_report",
    label="Building the report",
    kind=WRITE,
    risk="low",
    needs=can_access_orion_dashboard,
    description=(
        "Builds a PDF report from the dashboard data for a period: monthly_summary (headline figures, what is owed, top clients, month by month, "
        "findings), receivables (ageing and who owes), or revenue_by_client. The report contains only retrieved figures. Returns a download card."
    ),
    schema={"properties": {"kind": {"type": "string", "enum": list(reports.KINDS)}, **PERIOD_PROPS, "filters": DIM_FILTERS}, "required": ["kind"]},
)
def generate_report(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    kind = args["kind"]
    if kind == "receivables" and not can_access_billing(ctx.user):
        raise ToolError("The receivables report needs billing access.")
    report = reports.build(kind, ctx, {k: v for k, v in args.items() if k != "kind"})
    pdf = reports.render_pdf(report)
    name = f"{kind}_{ctx.today.strftime('%Y%m%d')}.pdf"
    file_id = store.save_file(ctx.user["id"], name, "application/pdf", pdf)
    block = ctx.block("file", id=file_id, name=name, size=len(pdf), url=f"/api/ai/files/{file_id}", format="pdf", description=f"{report['title']} · {report['subtitle']}")
    return ToolResult({"report": {"title": report["title"], "period": report["subtitle"], "sections": [s["heading"] for s in report["sections"]], "file": {"id": file_id, "name": name}},
                       "blocks": [{"id": block, "shows": "the report download card"}]}, f"Built the {report['title'].lower()} report")


@tool(
    name="email_file",
    label="Preparing an email",
    kind=WRITE,
    risk="high",
    confirm=True,
    needs=lambda user: True,
    description="Prepares an email with a file you made earlier in this conversation (an export or report) attached. Nothing is sent until the person confirms on screen, where they see who it goes to.",
    schema={"properties": {
        "file_id": {"type": "string", "maxLength": 64},
        "to": {"type": "string", "maxLength": 300, "description": "One to three email addresses, separated by commas."},
        "subject": {"type": "string", "maxLength": 150},
        "message": {"type": "string", "maxLength": 1200},
    }, "required": ["file_id", "to"]},
)
def _email_run(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    found = store.get_file(ctx.user["id"], args["file_id"])
    if not found:
        raise ToolError("That file has expired or is not yours.")
    sender = ctx.user.get("display_name") or "Orion"
    text = (args.get("message") or "").strip() or f"{sender} has sent you {found['name']} from Orion."
    mail.send_mail(
        args["to"], (args.get("subject") or found["name"])[:150], text + f"\n\nSent by {sender} using the Orion Copilot.",
        attachments=[(found["name"], found["data"], found["content_type"].split(";")[0])], raise_on_error=True,
    )
    return ToolResult({"sent": found["name"], "to": args["to"]}, f"Emailed {found['name']} to {args['to']}")


def _prepare_email(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    found = store.get_file(ctx.user["id"], args["file_id"])
    if not found:
        raise ToolError("I can only email a file made in this conversation, and it has expired or is not available.")
    try:
        to = receivables.parse_emails(args["to"])
    except Exception as exc:  # noqa: BLE001
        raise ToolError("Those email addresses are not valid.") from exc
    if not to or len([a for a in to.split(",") if a.strip()]) > 3:
        raise ToolError("Give between one and three valid email addresses.")
    args["to"] = to
    rows = [{"label": "To", "value": to}, {"label": "File", "value": f"{found['name']} ({found['size_bytes'] // 1024 or 1} KB)"}, {"label": "Subject", "value": args.get("subject") or found["name"]}]
    if args.get("message"):
        rows.append({"label": "Message", "value": args["message"]})
    return {"title": f"Email {found['name']} to {to}", "rows": rows, "danger": True, "warning": "Once sent, it cannot be recalled.", "confirm_label": "Send email"}


# Confirmation tools are registered with their preparation step.
from app.ai.tools.core import REGISTRY  # noqa: E402

REGISTRY["create_record"].prepare = _prepare_create
REGISTRY["update_record"].prepare = _prepare_update
REGISTRY["delete_record"].prepare = _prepare_delete
REGISTRY["email_file"].prepare = _prepare_email


# ----------------------------------------------------------------------------------------------- ui actions

PAGES = {
    "dashboard": ("Orion dashboard", "/dashboard/orion", can_access_orion_dashboard),
    "billing": ("Billing", "/utility/billing", can_access_billing),
    "receivables": ("Outstanding bills", "/utility/receivables", can_access_billing),
    "bills_to_raise": ("Monthly billing", "/utility/due", can_access_billing),
    "documents": ("Document Center", "/documents", can_access_documents),
    "bank": ("Bank", "/bank", can_access_bank),
    "records": ("Operational data", "/data/orion", can_access_ods),
    "settings": ("Settings", "/settings", lambda user: True),
    "appearance": ("Appearance settings", "/settings?tab=appearance", lambda user: True),
    "ai_settings": ("AI Copilot settings", "/settings?tab=ai", lambda user: True),
    "admin": ("Admin", "/admin", is_admin),
}


@tool(
    name="open_page",
    label="Opening the page",
    kind=UI,
    needs=lambda user: True,
    description=(
        "Opens a page in the application for the person, and for dashboards can set the tab, period and filters (this is how to 'filter the dashboard "
        "to last quarter' or 'open the revenue dashboard for Civil Hospital'). Pages: " + ", ".join(PAGES) + ". Dashboard tabs: " + ", ".join(VIEWS) + "."
    ),
    schema={"properties": {
        "page": {"type": "string", "enum": list(PAGES)},
        "view": {"type": "string", "enum": list(VIEWS), "description": "For page=dashboard: which tab."},
        **PERIOD_PROPS, "filters": DIM_FILTERS,
        "bill_id": {"type": "string", "maxLength": 40, "description": "Open this bill (for page=billing), for example BILL-0041."},
    }, "required": ["page"]},
)
def open_page(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    label, path, allowed = PAGES[args["page"]]
    if not allowed(ctx.user):
        raise ToolError(f"You do not have access to {label}.")
    if args["page"] == "dashboard":
        view = args.get("view", "overview")
        if not view_allowed(view, ctx.user):
            raise ToolError("You do not have access to that dashboard.")
        window = _window(args, ctx, "all_time") if (args.get("period") or args.get("from") or args.get("to")) else None
        with db_cursor() as cur:
            dims, _notes = _resolve_dimensions(cur, args.get("filters"))
        selection = {**dims, **(window.filters if window else {})}
        path = analytics._link(view, selection)
        label = f"{view.capitalize()} dashboard" + (f" · {window.label}" if window else "")
    elif args["page"] == "billing" and args.get("bill_id"):
        if not re.fullmatch(r"BILL-\d{1,8}", args["bill_id"]):
            raise ToolError("That is not a bill id.")
        path, label = f"/utility/billing/{args['bill_id']}", f"Bill {args['bill_id']}"
    action = {"type": "navigate", "path": path, "label": label}
    ctx.ui_actions.append(action)
    return ToolResult({"opened": label, "path": path, "instruction": "The page is opening for the person now. Say briefly what you opened."}, f"Opening {label}")


@tool(
    name="set_appearance",
    label="Changing the look",
    kind=UI,
    needs=lambda user: True,
    description=f"Changes how the application looks for this person: light or dark mode, and/or a theme ({', '.join(THEME_IDS)}). It affects only their own display.",
    schema={"properties": {"mode": {"type": "string", "enum": ["light", "dark", "system"]}, "theme": {"type": "string", "enum": THEME_IDS}}},
)
def set_appearance(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    if not args.get("mode") and not args.get("theme"):
        raise ToolError("Say whether to change the mode or the theme.")
    action = {"type": "appearance", **{k: args[k] for k in ("mode", "theme") if args.get(k)}}
    ctx.ui_actions.append(action)
    label = ", ".join(f"{k} {v}" for k, v in action.items() if k != "type")
    return ToolResult({"applied": label, "instruction": "The change is applied on the person's screen now."}, f"Changed the appearance: {label}")
