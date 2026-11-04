
from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, Response, UploadFile, status
from pydantic import BaseModel, Field

import psycopg2
from psycopg2 import errors as pg_errors

from app.routers.column_filter_params import filters_or_400, values_or_400
from app.db_utils import (
    count_rows,
    fetch_by_id,
    fetch_dropdown,
    fetch_column_values,
    fetch_preview_ex,
    MergeError,
    source_without,
    upsert_many,
)
from app.auth import can_write_bank, can_write_ods
from app.dependencies import get_current_user, require_ods, require_ods_write
from app.record_history import record_history
from app.entities import DUPLICATE_WINDOW_DAYS, ENTITIES, create_fields, dropdown_spec, duplicate_note, find_possible_duplicates, locked_reason, merge_columns, merge_fallback, with_create_fields
from app.excel_import import (
    EXPORT_LIMITS,
    INLINE_PREVIEW_LIMITS,
    build_template,
    excel_file_response,
    parse_preview_limit,
    parse_workbook,
)
from app import entity_service, idempotency, opportunity_followups
from app.idempotency import Idempotency
from app.ai import features as ai_features
from app.entity_service import hydrate_lookup_labels as _hydrate_lookup_labels, serialize_record as _serialize_record, serialize_value as _serialize_value
from app.payload import PayloadError, clean_payload

router = APIRouter(prefix="/entities", tags=["entities"])

MAX_EXCEL_BYTES = 5 * 1024 * 1024


def _get_entity(name: str) -> dict:
    if name not in ENTITIES:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown entity")
    return ENTITIES[name]


def _shown_source(entity: dict, user: dict) -> str | None:
    """What the table preview and the export read from. An entity with private columns (the Employee's Aadhaar, PAN
    and salary) shows them only to people who can change operational data; for anyone else they are not read at all."""
    private = entity.get("private_columns")
    if not private or can_write_ods(user):
        return None
    return source_without(entity["table"], private)


def _validate_payload(entity: dict, payload: dict, *, for_update: bool = False, existing: dict | None = None) -> dict:
    try:
        return clean_payload(entity, payload, for_update=for_update, existing=existing)
    except PayloadError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _once(request: Request, user: dict, operation: str, *parts) -> Idempotency | None:
    """The request's one-time key, if it sent one (``Idempotency-Key``). With ``ORION_IDEMPOTENCY_REQUIRED=1`` it must."""
    try:
        key = idempotency.clean_key(request.headers.get("Idempotency-Key"))
    except idempotency.IdempotencyError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if key is None:
        if idempotency.required():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This page is out of date. Reload it and try again.")
        return None
    return Idempotency(user["id"], key, operation, idempotency.fingerprint(operation, user["id"], *parts))


class RecordPayload(BaseModel):
    data: dict
    #: The record's last_updated_timestamp as the form loaded it. When the record has been saved since, the change is refused.
    expected_updated: str | None = None


def _serviced(work):
    """Runs a record operation of ``entity_service`` and turns its refusal into the HTTP error a route gives."""
    try:
        return work()
    except entity_service.EntityError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.message) from exc


def _database_refusal(exc: Exception) -> HTTPException:
    """A value the database rules out, as a message the user can act on rather than an internal error."""
    refusal = entity_service.database_refusal(exc)
    return HTTPException(status_code=refusal.status, detail=refusal.message)


DATABASE_REFUSALS = (pg_errors.CheckViolation, psycopg2.DataError)


@router.get("")
def list_entity_names(user=Depends(get_current_user)):
    from app.auth import can_access_ods

    if not can_access_ods(user):
        raise HTTPException(status_code=403, detail="ODS access required")
    return {
        "entities": [
            {
                "name": name,
                "primary_key": meta["primary_key"],
                "display_column": meta["display_column"],
                "form_fields": meta["form_fields"],
                # Asked only when a record is added, and only of a person who may change the bank (they record a payment): see entities.create_fields
                "create_fields": create_fields(meta) if can_write_bank(user) else {},
                "checks_duplicates": bool(meta.get("duplicate_check")),
                "merge_key": merge_columns(name, meta),
            }
            for name, meta in ENTITIES.items()
        ]
    }


def _limit(raw: str, allowed: set[int | None]) -> int | None:
    try:
        return parse_preview_limit(raw, allowed)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{name}/preview")
def preview_records(
    name: str,
    limit: str = Query("3"),
    q: str = Query(""),
    sort: str = Query(""),
    dir: str = Query("desc"),
    f: str = Query(""),
    user=Depends(require_ods),
):
    entity = _get_entity(name)
    size = _limit(limit, INLINE_PREVIEW_LIMITS)
    found = fetch_preview_ex(
        entity["table"],
        size,
        search=q,
        sort=sort or None,
        direction=dir,
        source_sql=_shown_source(entity, user),
        filters=filters_or_400(f),
    )
    cols, rows, matched = found.columns, found.rows, found.matched
    return {
        "columns": cols,
        "rows": [{cols[i]: _serialize_value(row[i]) for i in range(len(cols))} for row in rows],
        "total": count_rows(entity["table"]),
        "matched": matched,
        "kinds": found.kinds,
        "limit": size,
        "q": q,
        "sort": sort,
        "dir": dir,
    }


@router.get("/{name}/values")
def column_values(
    name: str,
    column: str = Query(...),
    q: str = Query(""),
    contains: str = Query(""),
    f: str = Query(""),
    user=Depends(require_ods),
):
    """The values a column holds (with how many rows each is on), to pick from in the column's filter."""
    entity = _get_entity(name)
    return values_or_400(
        lambda: fetch_column_values(entity["table"], column, search=q, source_sql=_shown_source(entity, user), filters=filters_or_400(f), contains=contains)
    )


@router.get("/{name}/export")
def export_records(
    name: str,
    limit: str = Query("100"),
    q: str = Query(""),
    sort: str = Query(""),
    dir: str = Query("desc"),
    f: str = Query(""),
    user=Depends(require_ods),
):
    entity = _get_entity(name)
    size = _limit(limit, EXPORT_LIMITS)
    found = fetch_preview_ex(
        entity["table"],
        size,
        search=q,
        sort=sort or None,
        direction=dir,
        source_sql=_shown_source(entity, user),
        filters=filters_or_400(f),
    )
    cols, rows, _matched = found.columns, found.rows, found.matched
    # created_by and last_updated_by are user ids: meaningless in a spreadsheet. History shows the names.
    keep = [i for i, col in enumerate(cols) if col not in ("created_by", "last_updated_by")]
    return excel_file_response(name, size, [cols[i] for i in keep], [[row[i] for i in keep] for row in rows])


@router.get("/{name}/options")
def entity_options(name: str, _user=Depends(require_ods_write)):
    entity = _get_entity(name)
    table, display, pk, from_sql = dropdown_spec(entity)
    records = fetch_dropdown(table, display, pk, from_sql=from_sql)
    return [{"id": r[0], "label": r[1]} for r in records]


@router.get("/{name}/field-options/{field_name}")
def field_options(name: str, field_name: str, _user=Depends(require_ods_write)):
    entity = _get_entity(name)
    config = entity["form_fields"].get(field_name) or create_fields(entity).get(field_name)
    if not config:
        raise HTTPException(status_code=404, detail="Unknown field")
    if "options" in config:
        return [{"id": o, "label": o} for o in config["options"]]
    if "source_table" in config:
        # Form fields show the related row's name (client_name, case_name, …).
        # The update record picker uses dropdown_spec() for a longer identity label.
        records = fetch_dropdown(
            config["source_table"],
            config["source_display_column"],
            config.get("source_pk_column", "id"),
            from_sql=config.get("source_from"),
        )
        return [{"id": r[0], "label": r[1]} for r in records]
    raise HTTPException(status_code=400, detail="Field has no options")


@router.get("/{name}/excel-template")
def excel_template(name: str, user=Depends(require_ods_write)):
    entity = _get_entity(name)
    slug = name.lower().replace(" ", "_")
    content = build_template(name, with_create_fields(entity) if can_write_bank(user) else entity)
    filename = f"orion_{slug}_template.xlsx"
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/{name}/excel")
def upload_excel(name: str, file: UploadFile = File(...), user=Depends(require_ods_write)):
    entity = _get_entity(name)
    # A person who may change the bank may also say, in the file, which new records were paid (Paid On, Paid From, Payment Reference).
    sheet = with_create_fields(entity) if can_write_bank(user) else entity
    filename = (file.filename or "").lower()
    if not filename.endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="Please upload an .xlsx Excel file")
    content = file.file.read()
    if not content:
        raise HTTPException(status_code=400, detail="The uploaded file is empty")
    if len(content) > MAX_EXCEL_BYTES:
        raise HTTPException(status_code=400, detail="File is larger than 5 MB")
    try:
        rows, errors = parse_workbook(sheet, content, entity_name=name)
    except PayloadError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if errors:
        return {"ok": False, "inserted": 0, "updated": 0, "errors": errors}
    keys = merge_columns(name, entity)

    def finalize(stored: dict, changes: dict) -> dict:
        # A blank cell keeps the stored value, and the column a row is matched on is not rewritten, so a total the file worked
        # out from blank cells is worked out again from the stored record. A row that does not touch the amounts leaves it be.
        for key, config in entity["form_fields"].items():
            sources = config.get("compute_from") or []
            if not sources or config.get("compute_op", "sum") != "sum":
                continue
            if (key in changes or any(src in changes for src in sources)) and any(src not in changes for src in sources):
                parts = [changes[src] if src in changes else stored.get(src) for src in sources]
                if parts[0] is not None:
                    changes[key] = round(sum(float(part) if part is not None else 0.0 for part in parts), 2)
        return changes

    warnings = _upload_warnings(name, rows)
    extra_keys = create_fields(entity)
    for row in rows:
        extra = {key: row.pop(key) for key in list(row) if key in extra_keys and row[key] not in (None, "")}
        for key in [k for k in list(row) if k in extra_keys]:
            row.pop(key)
        if extra:
            row["__extra"] = extra

    def after_insert(cur, code, extra: dict, excel_row) -> None:
        if extra.get("paid_on") is None:
            raise MergeError("Say the day it was paid (Paid On), or leave Paid From and Payment Reference empty.", excel_row)
        try:
            entity_service.pay_new_record(cur, name, code, extra, user["id"])
        except entity_service.EntityError as exc:
            raise MergeError(exc.message, excel_row) from exc

    try:
        inserted, updated = upsert_many(
            entity["table"], rows, keys, entity["primary_key"], match_filter=entity.get("merge_filter"),
            user_id=user["id"], fallback_cols=merge_fallback(name), finalize=finalize, after_insert=after_insert,
        )
    except MergeError as exc:
        return {"ok": False, "inserted": 0, "updated": 0, "errors": [{"row": exc.row or 0, "message": str(exc)}]}
    except pg_errors.UniqueViolation as exc:
        raise HTTPException(status_code=400, detail=f"Upload failed: a merge key already exists ({exc})") from exc
    except pg_errors.CheckViolation as exc:
        raise HTTPException(status_code=400, detail=f"Upload failed: {_database_refusal(exc).detail}") from exc
    except psycopg2.DataError as exc:
        raise HTTPException(status_code=400, detail=f"Upload failed: {_database_refusal(exc).detail}") from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Upload failed: {exc}") from exc
    opportunity_followups.sync_quietly()  # an upload may have won an opportunity, or made its case or EMD
    return {"ok": True, "inserted": inserted, "updated": updated, "errors": [], "warnings": warnings}


def _upload_warnings(name: str, rows: list[dict]) -> list[dict]:
    """Rows of an upload that look like another record (see entities.find_possible_duplicates): one of the same file, or one already recorded on another day.
    Said with the result, since an upload saves at once; nothing is refused."""
    if not ENTITIES[name].get("duplicate_check"):
        return []
    found: list[dict] = []
    seen: list[tuple[int, tuple]] = []
    for row in rows:
        if row.get("__code"):
            continue  # a row about a record that exists is a change, not a new one
        line = row.get("__row") or 0
        total = row.get("amount_after_tax_gst") if row.get("amount_after_tax_gst") is not None else row.get("transaction_amount")
        day = row.get("transaction_date")
        key = (row.get("expense_type_code"), row.get("case_code"), round(float(total), 2) if total is not None else None)
        if total is not None and day is not None:
            for earlier_line, earlier in seen:
                if earlier[:3] == key and abs((earlier[3] - day).days) <= DUPLICATE_WINDOW_DAYS and earlier[3] != day:
                    found.append({"row": line, "message": f"Looks like the expense on row {earlier_line} (same type, case and amount within {DUPLICATE_WINDOW_DAYS} days)."})
                    break
            seen.append((line, (*key, day)))
        for match in find_possible_duplicates(name, row, other_days_only=True, limit=1):
            found.append({"row": line, "message": f"Looks like {duplicate_note(match)} (same type, case and amount within {DUPLICATE_WINDOW_DAYS} days)."})
        if len(found) >= 50:
            break
    return found


class FillIn(BaseModel):
    text: str = Field(max_length=ai_features.FORM_TEXT_LIMIT + 2000)
    allow_cloud_once: bool = False


@router.post("/{name}/ai/fill")
def ai_fill(name: str, body: FillIn, user=Depends(require_ods_write)):
    """Reads pasted text (an email, a work order) and suggests values for this form. Nothing is saved: the person checks the
    values on the form and saves it as they would a form they had typed. Lookups and private columns are never offered."""
    entity = _get_entity(name)
    result = ai_features.fill_form(user, entity, body.text, allow_cloud_once=body.allow_cloud_once)
    if result.get("status") == "invalid":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=result["message"])
    return result


@router.get("/{name}/records/{record_id}")
def get_record(name: str, record_id: str, _user=Depends(require_ods_write)):
    entity = _get_entity(name)
    record = fetch_by_id(entity["table"], record_id, entity["primary_key"])
    if not record:
        raise HTTPException(status_code=404, detail="Record not found")
    reason = locked_reason(name, record)
    record = _hydrate_lookup_labels(entity, _serialize_record(record))
    if reason:
        record["__locked"] = reason
    return record


@router.get("/{name}/records/{record_id}/history")
def record_history_view(name: str, record_id: str, user=Depends(require_ods)):
    """Who changed this record and what they changed, read from the warehouse."""
    entity = _get_entity(name)
    # Private fields (an employee's salary) are in the history only for people who can change the records.
    hide = set() if can_write_ods(user) else set(entity.get("private_columns") or [])
    found = record_history(name, record_id, hide)
    if found is None:
        raise HTTPException(status_code=404, detail="This record type has no history")
    return found


def _paying(entity: dict, data: dict) -> bool:
    """Whether what was sent says the new record was also paid (the extra questions of ``create_fields`` answered)."""
    return any(data.get(key) not in (None, "") for key in create_fields(entity))


@router.post("/{name}/records")
def create_record(name: str, body: RecordPayload, request: Request, response: Response, user=Depends(require_ods_write)):
    # The new record's code comes back so a screen can attach something to it straight away (an employee's documents).
    entity = _get_entity(name)
    idem = None
    if _paying(entity, body.data):
        # A payment moves the bank balance: it needs the same permission as recording one in Bank > Payables, and it is made once however often it is sent.
        if not can_write_bank(user):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Marking an expense as paid changes the bank, and you do not have permission to change it.")
        idem = _once(request, user, "expense.create_paid", name, str(sorted((k, str(v)) for k, v in body.data.items())))
    try:
        created = _serviced(lambda: entity_service.create(name, body.data, user["id"], idem))
    except idempotency.IdempotencyConflict as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if idem is not None and idem.replayed:
        response.headers["Idempotent-Replayed"] = "true"
    return {"ok": True, "id": created}


@router.post("/{name}/duplicate-check")
def duplicate_check(name: str, body: RecordPayload, _user=Depends(require_ods_write)):
    """What already recorded looks like the record about to be added (nothing is saved). A warning to show before the save, never a refusal."""
    _get_entity(name)
    matches = _serviced(lambda: entity_service.possible_duplicates(name, body.data))
    return {"matches": [_serialize_record(m) for m in matches]}


@router.put("/{name}/records/{record_id}")
def update_record(name: str, record_id: str, body: RecordPayload, user=Depends(require_ods_write)):
    _serviced(lambda: entity_service.change(name, record_id, body.data, user["id"], body.expected_updated))
    return {"ok": True}


@router.delete("/{name}/records/{record_id}")
def remove_record(name: str, record_id: str, user=Depends(require_ods_write)):
    _serviced(lambda: entity_service.remove(name, record_id, user["id"]))
    return {"ok": True}
