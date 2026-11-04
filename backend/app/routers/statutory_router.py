from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query

from app import billing, statutory_position
from app.dependencies import require_billing

router = APIRouter(prefix="/statutory", tags=["statutory"])


@router.get("/position")
def position(fy: Optional[int] = Query(default=None, ge=2000, le=2100), _user=Depends(require_billing)):
    """The EPFO and ESIC charged on the bills and paid over, by month of a financial year (the current one by default), and the bills with something still to pay."""
    return statutory_position.position(fy or billing.fy_start_year(date.today()))
