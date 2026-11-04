"""The follow-ups of won opportunities: the notifications to create a case and record an EMD. Only people who can change operational data
see them or act on them, since only they can do what they ask."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app import opportunity_followups as followups
from app.dependencies import require_ods_write

router = APIRouter(prefix="/followups", tags=["followups"])


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="That follow-up does not exist.")


def _bad(exc: followups.FollowupError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


class Dismissal(BaseModel):
    note: Optional[str] = Field(default=None, max_length=followups.NOTE_LIMIT + 200)


@router.get("")
def list_followups(_user=Depends(require_ods_write)):
    """What is waiting to be done for won opportunities, and what people decided is not needed."""
    return followups.listing()


@router.get("/opportunity/{opportunity_code}")
def opportunity_context(opportunity_code: str, _user=Depends(require_ods_write)):
    """The won opportunity and the cases made for it, for the form opened from a follow-up."""
    found = followups.context(opportunity_code)
    if found is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="That opportunity does not exist.")
    return found


@router.post("/{followup_id}/dismiss")
def dismiss(followup_id: int, body: Dismissal, user=Depends(require_ods_write)):
    """Say that the case, or the EMD, is not required. This is the only way a waiting follow-up goes away without being done."""
    try:
        if not followups.dismiss(followup_id, user["id"], body.note):
            raise _not_found()
    except followups.FollowupError as exc:
        raise _bad(exc) from exc
    return {"ok": True}


@router.post("/{followup_id}/reopen")
def reopen(followup_id: int, user=Depends(require_ods_write)):
    """Take back a dismissal."""
    try:
        if not followups.reopen(followup_id, user["id"]):
            raise _not_found()
    except followups.FollowupError as exc:
        raise _bad(exc) from exc
    return {"ok": True}
