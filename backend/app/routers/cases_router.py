from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status

from app import auth, cases
from app.dependencies import require_ods

router = APIRouter(prefix="/cases", tags=["cases"])


@router.get("")
def list_cases(search: Optional[str] = Query(default=None, max_length=80), user=Depends(require_ods)):
    """Every case with its client; what each owes only for someone who may see billing."""
    return {"cases": cases.directory(search, auth.can_access_billing(user))}


@router.get("/{case_code}")
def get_case(case_code: str = Path(max_length=40), user=Depends(require_ods)):
    """One case: its people, contacts, deposits and expenses, and its bills and what it owes for someone who may see billing."""
    found = cases.profile(case_code, auth.can_access_billing(user))
    if found is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found")
    return found
