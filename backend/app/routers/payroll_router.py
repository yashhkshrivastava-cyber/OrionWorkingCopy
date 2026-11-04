"""The Payroll API: salary pay runs. Reading the months and the runs needs Bank access (they are totals); seeing who is in a month's unpaid salary, marking
it paid and reversing a run need permission to change the bank, because a pay run moves the bank balance."""

import logging
from datetime import date
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, Field

from app import idempotency, payroll
from app.dependencies import require_bank, require_bank_write
from app.idempotency import Idempotency

log = logging.getLogger(__name__)

router = APIRouter(prefix="/payroll", tags=["payroll"])


def _bad(exc: Exception) -> HTTPException:
    code = status.HTTP_409_CONFLICT if isinstance(exc, (payroll.PayrollConflict, idempotency.IdempotencyConflict)) else status.HTTP_400_BAD_REQUEST
    return HTTPException(status_code=code, detail=str(exc))


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


class RunIn(BaseModel):
    month_year: str = Field(max_length=7)
    line_codes: list[str] = Field(max_length=payroll.MAX_LINES)
    seen_count: int
    seen_total: float | str
    paid_date: date
    account_id: Optional[int] = None
    reference: Optional[str] = Field(default=None, max_length=payroll.REFERENCE_MAX)
    confirm: bool = False


class ReversalIn(BaseModel):
    reason: str = Field(max_length=payroll.REASON_MAX)
    confirm: bool = False


@router.get("/months")
def list_months(limit: int = Query(default=36, ge=1, le=120), _user=Depends(require_bank)):
    return {"months": payroll.months(limit)}


@router.get("/months/{month_year}/unpaid")
def unpaid(month_year: str, _user=Depends(require_bank_write)):
    try:
        return payroll.unpaid_lines(month_year)
    except payroll.PayrollError as exc:
        raise _bad(exc) from exc


@router.get("/runs")
def list_runs(month_year: Optional[str] = Query(default=None, max_length=7), limit: int = Query(default=50, ge=1, le=200), _user=Depends(require_bank)):
    try:
        return {"runs": payroll.runs(month_year=month_year, limit=limit)}
    except payroll.PayrollError as exc:
        raise _bad(exc) from exc


@router.post("/runs")
def record_run(body: RunIn, request: Request, response: Response, user=Depends(require_bank_write)):
    idem = _once(
        request, user, "salary.run", body.month_year, ",".join(sorted(body.line_codes)), str(body.paid_date), body.account_id, str(body.seen_total), body.reference or "",
    )
    try:
        saved = payroll.record_run(
            user["id"], confirm=body.confirm, month_year=body.month_year, line_codes=body.line_codes, seen_count=body.seen_count, seen_total=body.seen_total,
            paid_date=body.paid_date, account_id=body.account_id, reference=body.reference, idem=idem,
        )
    except (payroll.PayrollError, idempotency.IdempotencyConflict) as exc:
        raise _bad(exc) from exc
    if idem is not None and idem.replayed:
        response.headers["Idempotent-Replayed"] = "true"
    return saved


@router.post("/runs/{run_id}/reverse")
def reverse_run(run_id: int, body: ReversalIn, user=Depends(require_bank_write)):
    try:
        return payroll.reverse_run(run_id, user["id"], confirm=body.confirm, reason=body.reason)
    except payroll.PayrollError as exc:
        raise _bad(exc) from exc
