"""The SQL editor API. Administrators only, and only while the editor is switched on (``ORION_SQL_EDITOR``). See ``app.sql_lab``."""

import logging
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel

from app import sql_guard, sql_lab
from app.dependencies import get_current_user

log = logging.getLogger(__name__)

router = APIRouter(prefix="/sql", tags=["sql"])


def require_sql(user=Depends(get_current_user)):
    """Admin, with the editor switched on. Anyone else is told it is not there."""
    if not sql_lab.can_use(user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="The SQL editor is for administrators, and it may be switched off on this server.")
    return user


def _bad(exc: Exception) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


class RunRequest(BaseModel):
    sql: str
    write: bool = False
    rollback: bool = True  # with changes allowed: run them and roll back, to see what they would do
    limit: int = sql_lab.DEFAULT_LIMIT
    timeout: int = sql_lab.DEFAULT_TIMEOUT
    run_id: Optional[str] = None
    confirm: bool = False


class ExportRequest(BaseModel):
    sql: str
    limit: int = sql_lab.EXPORT_LIMIT


class CancelRequest(BaseModel):
    run_id: str


class SavedRequest(BaseModel):
    title: str
    sql: str
    folder: Optional[str] = None
    description: Optional[str] = None
    shared: bool = False


@router.get("/status")
def get_status(_user=Depends(require_sql)):
    return sql_lab.status()


@router.get("/catalog")
def get_catalog(_user=Depends(require_sql)):
    """Every schema with its tables, views and columns, for the tree and for autocomplete."""
    return sql_lab.catalog()


@router.get("/objects/{schema}/{name}")
def get_object(schema: str, name: str, _user=Depends(require_sql)):
    try:
        return sql_lab.object_detail(schema, name)
    except sql_lab.RunError as exc:
        raise _bad(exc) from exc


@router.post("/run")
def run(body: RunRequest, user=Depends(require_sql)):
    """Run a script. Answers 200 with `ok: false` and the reason when a statement is refused or fails, and with `needs_confirmation` when something must be confirmed first."""
    try:
        return sql_lab.run(user, body.sql, write=body.write, rollback=body.rollback, limit=body.limit, timeout=body.timeout, run_id=body.run_id, confirm=body.confirm)
    except sql_lab.RunError as exc:
        raise _bad(exc) from exc


@router.post("/cancel")
def cancel(body: CancelRequest, user=Depends(require_sql)):
    return {"cancelled": sql_lab.cancel(user, body.run_id)}


@router.post("/check")
def check(body: RunRequest, _user=Depends(require_sql)):
    """What would happen to this script if it were run in this mode, without running it: each statement's kind and what must be confirmed."""
    try:
        plan = sql_guard.vet_script(body.sql, may_change=body.write and sql_lab.mode() == "full")
    except sql_guard.Blocked as exc:
        return {"ok": False, "message": str(exc)}
    return {"ok": True, "statements": [{"kind": verdict.kind, "first": statement.first, "confirm": verdict.confirm} for statement, verdict in plan]}


@router.post("/export")
def export(body: ExportRequest, user=Depends(require_sql)):
    try:
        name, text = sql_lab.export_csv(user, body.sql, body.limit)
    except (sql_lab.RunError, sql_guard.Blocked) as exc:
        raise _bad(exc) from exc
    return Response(content="﻿" + text, media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"})


@router.get("/saved")
def list_saved(user=Depends(require_sql)):
    return {"queries": sql_lab.saved_queries(user)}


@router.post("/saved", status_code=status.HTTP_201_CREATED)
def create_saved(body: SavedRequest, user=Depends(require_sql)):
    try:
        return sql_lab.save_query(user, None, body.title, body.sql, body.folder, body.description, body.shared)
    except sql_lab.RunError as exc:
        raise _bad(exc) from exc


@router.put("/saved/{query_id}")
def update_saved(query_id: int, body: SavedRequest, user=Depends(require_sql)):
    try:
        return sql_lab.save_query(user, query_id, body.title, body.sql, body.folder, body.description, body.shared)
    except sql_lab.RunError as exc:
        raise _bad(exc) from exc


@router.delete("/saved/{query_id}")
def delete_saved(query_id: int, user=Depends(require_sql)):
    if not sql_lab.delete_query(user, query_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="That saved query is not yours, or it is already gone.")
    return {"ok": True}


@router.get("/history")
def get_history(everyone: bool = False, q: str = Query(default="", max_length=100), limit: int = Query(default=100, ge=1, le=500), user=Depends(require_sql)):
    return {"runs": sql_lab.history(user, everyone=everyone, q=q, limit=limit)}
