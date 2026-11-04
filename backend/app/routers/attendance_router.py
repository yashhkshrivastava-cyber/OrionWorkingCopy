"""The Attendance API. Seeing the registers needs Attendance access; making and changing them, posting and saving people need permission to change attendance."""

import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, Response, UploadFile, status
from pydantic import BaseModel, Field

from app import attendance, idempotency
from app.dependencies import require_attendance, require_attendance_write
from app.idempotency import Idempotency

log = logging.getLogger(__name__)

router = APIRouter(prefix="/attendance", tags=["attendance"])

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _bad(exc: Exception) -> HTTPException:
    code = status.HTTP_409_CONFLICT if isinstance(exc, (attendance.AttendanceConflict, idempotency.IdempotencyConflict)) else status.HTTP_400_BAD_REQUEST
    return HTTPException(status_code=code, detail=str(exc))


def _not_found(what: str = "register") -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"That {what} does not exist.")


def _once(request: Request, user: dict, operation: str, *parts: Any) -> Optional[Idempotency]:
    """The request's one-time key, if it sent one (``Idempotency-Key``). With ``ORION_IDEMPOTENCY_REQUIRED=1`` it must."""
    try:
        key = idempotency.clean_key(request.headers.get("Idempotency-Key"))
    except idempotency.IdempotencyError as exc:
        raise _bad(exc) from exc
    if key is None:
        if idempotency.required():
            raise _bad(idempotency.IdempotencyError("This page is out of date. Reload it and try again."))
        log.info("%s arrived without an Idempotency-Key, so a repeat of it would not be caught", operation)
        return None
    return Idempotency(user["id"], key, operation, idempotency.fingerprint(operation, user["id"], *parts))


class SheetIn(BaseModel):
    """A register as the screen has it. ``lines`` are checked one by one by ``attendance`` (each is one person)."""

    case_code: Optional[str] = Field(default=None, max_length=40)
    month_year: Optional[str] = Field(default=None, max_length=7)
    lines: list[dict[str, Any]] = Field(max_length=attendance.MAX_LINES)
    remarks: Optional[str] = Field(default=None, max_length=600)
    expense_type_code: Optional[str] = Field(default=None, max_length=40)


class PostIn(BaseModel):
    confirm: bool = False
    seen_count: int
    seen_total: float | str


class ReopenIn(BaseModel):
    confirm: bool = False
    reason: str = Field(max_length=attendance.REASON_MAX + 200)


class WorkerIn(BaseModel):
    name: str = Field(max_length=120)
    phone: Optional[str] = Field(default=None, max_length=30)
    designation: Optional[str] = Field(default=None, max_length=80)
    rate_per_day: Optional[float | str] = None
    case_code: Optional[str] = Field(default=None, max_length=40)
    status: Optional[str] = Field(default=None, max_length=10)


@router.get("/cases")
def cases(q: str = Query(default="", max_length=100), _user=Depends(require_attendance)):
    return {"cases": attendance.cases(q)}


@router.get("/expense-types")
def expense_types(_user=Depends(require_attendance)):
    return {"expense_types": attendance.expense_types()}


@router.get("/roster")
def roster(case_code: str = Query(max_length=40), month: str = Query(max_length=7), _user=Depends(require_attendance)):
    try:
        return attendance.roster(case_code, month)
    except attendance.AttendanceError as exc:
        raise _bad(exc) from exc


@router.get("/people")
def people(q: str = Query(default="", max_length=100), kind: str = Query(default="all", max_length=10), month: Optional[str] = Query(default=None, max_length=7), _user=Depends(require_attendance)):
    try:
        return attendance.search_people(q, kind, month)
    except attendance.AttendanceError as exc:
        raise _bad(exc) from exc


@router.get("/sheets")
def list_sheets(
    case_code: Optional[str] = Query(default=None, max_length=40), month: Optional[str] = Query(default=None, max_length=7), sheet_status: Optional[str] = Query(default=None, alias="status", max_length=10),
    q: str = Query(default="", max_length=100), _user=Depends(require_attendance),
):
    try:
        return {"sheets": attendance.list_sheets(case_code=case_code, month_year=month, status=sheet_status, query=q)}
    except attendance.AttendanceError as exc:
        raise _bad(exc) from exc


@router.get("/sheets/{sheet_code}")
def get_sheet(sheet_code: str, _user=Depends(require_attendance)):
    found = attendance.get_sheet(sheet_code)
    if found is None:
        raise _not_found()
    return found


@router.post("/sheets", status_code=status.HTTP_201_CREATED)
def create_sheet(body: SheetIn, user=Depends(require_attendance_write)):
    try:
        return attendance.save_sheet(user["id"], case_code=body.case_code, month_year=body.month_year, lines=body.lines, remarks=body.remarks, expense_type_code=body.expense_type_code)
    except attendance.AttendanceError as exc:
        raise _bad(exc) from exc


@router.put("/sheets/{sheet_code}")
def save_sheet(sheet_code: str, body: SheetIn, user=Depends(require_attendance_write)):
    try:
        return attendance.save_sheet(user["id"], sheet_code=sheet_code, lines=body.lines, remarks=body.remarks, expense_type_code=body.expense_type_code)
    except attendance.AttendanceError as exc:
        raise _bad(exc) from exc


@router.delete("/sheets/{sheet_code}")
def delete_sheet(sheet_code: str, user=Depends(require_attendance_write)):
    try:
        if not attendance.delete_sheet(user["id"], sheet_code):
            raise _not_found()
    except attendance.AttendanceError as exc:
        raise _bad(exc) from exc
    return {"ok": True}


@router.post("/sheets/{sheet_code}/post")
def post_sheet(sheet_code: str, body: PostIn, request: Request, response: Response, user=Depends(require_attendance_write)):
    idem = _once(request, user, "attendance.post", sheet_code, body.seen_count, str(body.seen_total))
    try:
        saved = attendance.post_sheet(user["id"], sheet_code, confirm=body.confirm, seen_count=body.seen_count, seen_total=body.seen_total, idem=idem)
    except (attendance.AttendanceError, idempotency.IdempotencyConflict) as exc:
        raise _bad(exc) from exc
    if idem is not None and idem.replayed:
        response.headers["Idempotent-Replayed"] = "true"
    return saved


@router.post("/sheets/{sheet_code}/reopen")
def reopen_sheet(sheet_code: str, body: ReopenIn, user=Depends(require_attendance_write)):
    try:
        return attendance.reopen_sheet(user["id"], sheet_code, confirm=body.confirm, reason=body.reason)
    except attendance.AttendanceError as exc:
        raise _bad(exc) from exc


@router.get("/sheets/{sheet_code}/export")
def export_sheet(sheet_code: str, _user=Depends(require_attendance)):
    found = attendance.sheet_file(sheet_code)
    if found is None:
        raise _not_found()
    name, data = found
    return Response(content=data, media_type=XLSX, headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.get("/template")
def template(case_code: str = Query(max_length=40), month: str = Query(max_length=7), _user=Depends(require_attendance)):
    try:
        name, data = attendance.template_file(case_code, month)
    except attendance.AttendanceError as exc:
        raise _bad(exc) from exc
    return Response(content=data, media_type=XLSX, headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.post("/parse")
def parse(case_code: str = Query(max_length=40), month: str = Query(max_length=7), file: UploadFile = File(...), _user=Depends(require_attendance_write)):
    """Read a filled attendance workbook into lines for the register. Nothing is saved: the person checks the lines and saves the register."""
    if not (file.filename or "").lower().endswith(".xlsx"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Please upload an .xlsx Excel file.")
    content = file.file.read(attendance.UPLOAD_LIMIT + 1)
    try:
        return attendance.parse_upload(case_code, month, content)
    except attendance.AttendanceError as exc:
        raise _bad(exc) from exc


@router.get("/workers")
def workers(q: str = Query(default="", max_length=100), worker_status: str = Query(default="Active", alias="status", max_length=10), _user=Depends(require_attendance)):
    return {"workers": attendance.list_workers(q, worker_status)}


@router.post("/workers", status_code=status.HTTP_201_CREATED)
def create_worker(body: WorkerIn, user=Depends(require_attendance_write)):
    try:
        return attendance.create_worker(user["id"], body.model_dump())
    except attendance.AttendanceError as exc:
        raise _bad(exc) from exc


@router.put("/workers/{worker_code}")
def update_worker(worker_code: str, body: WorkerIn, user=Depends(require_attendance_write)):
    try:
        if not attendance.update_worker(user["id"], worker_code, body.model_dump()):
            raise _not_found("person")
    except attendance.AttendanceError as exc:
        raise _bad(exc) from exc
    return {"ok": True}
