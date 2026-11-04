from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query

from app import billing, gst_position
from app.dependencies import require_billing

router = APIRouter(prefix="/gst", tags=["gst"])


@router.get("/position")
def position(fy: Optional[int] = Query(default=None, ge=2000, le=2100), _user=Depends(require_billing)):
    """The GST on the bills, the input tax credit on the costs and the net, by month of a financial year (the current one by default)."""
    return gst_position.position(fy or billing.fy_start_year(date.today()))
