from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status

from app import auth, employees
from app.dependencies import require_ods

router = APIRouter(prefix="/employees", tags=["employees"])


@router.get("")
def list_employees(search: Optional[str] = Query(default=None, max_length=80), _user=Depends(require_ods)):
    """Every employee with their designation, case and client. Nothing private (Aadhaar, PAN, salary) is in it."""
    return {"employees": employees.directory(search)}


@router.get("/{employee_code}")
def get_employee(employee_code: str = Path(max_length=40), user=Depends(require_ods)):
    """One employee. Their recent pay is included only for someone with bank access (the people who run payroll)."""
    found = employees.profile(employee_code, auth.can_access_bank(user))
    if found is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found")
    return found
