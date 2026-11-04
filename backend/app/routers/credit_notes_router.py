import logging
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, Field

from app import billing, credit_notes, idempotency
from app.auth import is_admin
from app.dependencies import require_admin, require_billing, require_billing_write
from app.routers.billing_router import _conflict, _finish, _once

log = logging.getLogger(__name__)

router = APIRouter(prefix="/credit-notes", tags=["credit-notes"])


class CreditNoteIn(BaseModel):
    bill_code: str = Field(max_length=40)
    kind: str = Field(max_length=30)
    total: float | str  # the amount credited, GST included
    note_date: date
    reason: str = Field(max_length=credit_notes.REASON_MAX * 2)


class ApproveIn(BaseModel):
    confirm: bool = False
    seen_total: Optional[float | str] = None


class RejectIn(BaseModel):
    note: str = Field(max_length=credit_notes.REASON_MAX * 2)


class ReverseIn(BaseModel):
    reason: str = Field(max_length=credit_notes.REASON_MAX * 2)


def _bad_request(exc: Exception) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="That credit note does not exist.")


@router.get("")
def listing(
    state: Optional[str] = Query(default=None, alias="status", max_length=20),
    fy: Optional[int] = Query(default=None, ge=2000, le=2100),
    user=Depends(require_billing),
):
    """Credit notes newest first, with how many are waiting for a decision."""
    try:
        return credit_notes.listing(state, fy, user["id"], is_admin(user))
    except billing.BillError as exc:
        raise _bad_request(exc) from exc


@router.get("/bill/{bill_code}")
def for_bill(bill_code: str, user=Depends(require_billing)):
    return {"credit_notes": credit_notes.list_for_bill(bill_code, user["id"], is_admin(user))}


@router.get("/preview")
def preview(bill_code: str = Query(max_length=40), total: str = Query(max_length=30), _user=Depends(require_billing)):
    """What a credit of this amount would be made of and what would still be owed, before it is made."""
    try:
        return credit_notes.preview(bill_code, total)
    except billing.BillError as exc:
        raise _bad_request(exc) from exc


@router.post("", status_code=status.HTTP_201_CREATED)
def create(body: CreditNoteIn, request: Request, response: Response, user=Depends(require_billing_write)):
    """Make a credit note. It waits for approval and changes nothing until then."""
    idem = _once(request, response, user, "credit_note.create", body.bill_code, body.kind, str(body.total), str(body.note_date), body.reason)
    try:
        made = credit_notes.create(body.bill_code, body.kind, body.total, body.note_date, body.reason, user["id"], idem)
    except billing.BillError as exc:
        raise _bad_request(exc) from exc
    except idempotency.IdempotencyConflict as exc:
        raise _conflict(exc) from exc
    _finish(idem, response)
    return made


@router.get("/{credit_note_id}")
def one(credit_note_id: int, user=Depends(require_billing)):
    found = credit_notes.get(credit_note_id, user["id"], is_admin(user))
    if not found:
        raise _not_found()
    return found


@router.post("/{credit_note_id}/approve")
def approve(credit_note_id: int, body: ApproveIn, user=Depends(require_billing_write)):
    try:
        return credit_notes.approve(credit_note_id, user["id"], is_admin(user), confirm=body.confirm, seen_total=body.seen_total)
    except billing.BillError as exc:
        raise _bad_request(exc) from exc


@router.post("/{credit_note_id}/reject")
def reject(credit_note_id: int, body: RejectIn, user=Depends(require_billing_write)):
    try:
        return credit_notes.reject(credit_note_id, user["id"], is_admin(user), body.note)
    except billing.BillError as exc:
        raise _bad_request(exc) from exc


@router.post("/{credit_note_id}/withdraw")
def withdraw(credit_note_id: int, user=Depends(require_billing_write)):
    try:
        return credit_notes.withdraw(credit_note_id, user["id"], is_admin(user))
    except billing.BillError as exc:
        raise _bad_request(exc) from exc


@router.post("/{credit_note_id}/reverse")
def reverse(credit_note_id: int, body: ReverseIn, user=Depends(require_admin)):
    try:
        return credit_notes.reverse(credit_note_id, user["id"], True, body.reason)
    except billing.BillError as exc:
        raise _bad_request(exc) from exc
