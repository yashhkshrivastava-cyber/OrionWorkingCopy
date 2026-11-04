from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app import tds
from app.dependencies import require_billing, require_billing_write

router = APIRouter(prefix="/tds", tags=["tds"])


class MatchIn(BaseModel):
    matched: bool
    certificate_ref: Optional[str] = Field(default=None, max_length=120)


@router.get("/ledger")
def ledger(
    fy: Optional[int] = Query(default=None, ge=2000, le=2100),
    client_code: Optional[str] = Query(default=None, max_length=40),
    section: Optional[str] = Query(default=None, max_length=8),
    match: str = Query(default="all", max_length=12),
    quarter: Optional[str] = Query(default=None, pattern="^Q[1-4]$"),
    _user=Depends(require_billing),
):
    """The TDS clients held back, by financial year, for checking against Form 26AS."""
    try:
        return tds.ledger(fy, client_code, section, match, quarter)
    except tds.TdsError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/suggestion")
def suggestion(
    client_code: Optional[str] = Query(default=None, max_length=40),
    bill_code: Optional[str] = Query(default=None, max_length=40),
    _user=Depends(require_billing),
):
    """The section and rate to suggest when recording a client's payment (what that client was last deducted under)."""
    return tds.suggestion(client_code, bill_code)


@router.put("/deductions/{deduction_id}/matched")
def match(deduction_id: int, body: MatchIn, user=Depends(require_billing_write)):
    try:
        return tds.set_matched(deduction_id, body.matched, body.certificate_ref, user["id"])
    except tds.TdsError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
