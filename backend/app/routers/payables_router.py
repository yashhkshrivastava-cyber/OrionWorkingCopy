"""The Payables API: what the firm owes on expenses, and recording and reversing the payments. Reading needs Bank access; a payment moves the bank
balance, so recording or reversing one needs permission to change the bank."""

import logging
from datetime import date
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, Field

from app import idempotency, payables
from app.dependencies import require_bank, require_bank_write
from app.idempotency import Idempotency

log = logging.getLogger(__name__)

router = APIRouter(prefix="/payables", tags=["payables"])


def _bad(exc: Exception) -> HTTPException:
    code = status.HTTP_409_CONFLICT if isinstance(exc, (payables.PayableConflict, idempotency.IdempotencyConflict)) else status.HTTP_400_BAD_REQUEST
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


class PaymentIn(BaseModel):
    amount: float | str
    paid_date: date
    account_id: Optional[int] = None
    reference: Optional[str] = Field(default=None, max_length=payables.REFERENCE_MAX)
    seen_paid: float | str
    confirm: bool = False


class ReversalIn(BaseModel):
    reason: str = Field(max_length=payables.REASON_MAX)
    confirm: bool = False


@router.get("")
def list_payables(
    status_filter: str = Query(default="open", alias="status"),
    bucket: Optional[str] = Query(default=None, max_length=10),
    q: Optional[str] = Query(default=None, max_length=80),
    case_code: Optional[str] = Query(default=None, max_length=40),
    page: int = Query(default=1, ge=1, le=100000),
    limit: int = Query(default=50, ge=1, le=payables.PAGE_MAX),
    _user=Depends(require_bank),
):
    try:
        return payables.list_payables(status=status_filter, bucket=bucket, q=q, page=page, limit=limit, case_code=case_code)
    except payables.PayableError as exc:
        raise _bad(exc) from exc


@router.get("/{expense_code}")
def get_expense(expense_code: str, _user=Depends(require_bank)):
    found = payables.get_expense(expense_code)
    if found is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="That expense does not exist.")
    return found


@router.post("/{expense_code}/payments")
def record_payment(expense_code: str, body: PaymentIn, request: Request, response: Response, user=Depends(require_bank_write)):
    idem = _once(request, user, "expense.payment", expense_code, str(body.amount), str(body.paid_date), body.account_id, str(body.seen_paid))
    try:
        saved = payables.record_payment(
            expense_code, user["id"], confirm=body.confirm, seen_paid=body.seen_paid, amount=body.amount, paid_date=body.paid_date,
            reference=body.reference, account_id=body.account_id, idem=idem,
        )
    except (payables.PayableError, idempotency.IdempotencyConflict) as exc:
        raise _bad(exc) from exc
    if idem is not None and idem.replayed:
        response.headers["Idempotent-Replayed"] = "true"
    return saved


@router.post("/payments/{payment_id}/reverse")
def reverse_payment(payment_id: int, body: ReversalIn, user=Depends(require_bank_write)):
    try:
        return payables.reverse_payment(payment_id, user["id"], confirm=body.confirm, reason=body.reason)
    except payables.PayableError as exc:
        raise _bad(exc) from exc
