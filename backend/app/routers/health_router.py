from fastapi import APIRouter, Depends

from app import health
from app.dependencies import require_admin

# /api/health and /api/health/ready are public and live in main.py (a launcher polls them before anyone can sign in).
router = APIRouter(prefix="/health", tags=["health"])


@router.get("/details")
def health_details(_admin=Depends(require_admin)):
    """What the System page in Admin shows: the database, the loads, the backup, the request counters, the recent problems."""
    return health.details()
