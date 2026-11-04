from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from app.routers.column_filter_params import filters_or_400
from app.dashboard.forecasting import build_forecast
from app.auth import can_access_bank
from app.dashboard import DEFAULT_VIEW, FILTER_KEYS, VIEWS, build_view, view_allowed, views_for
from app.dashboard import explore as explorer
from app.dashboard import records
from app.dashboard.filters import clean_filters
from app.database import db_cursor
from app.dependencies import require_orion_dashboard
from app.dw_auto import autoload_minutes
from app.dw_sync import load_status

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/views")
def list_views(user=Depends(require_orion_dashboard)):
    return {"views": views_for(user), "default": DEFAULT_VIEW, "filters": list(FILTER_KEYS)}


@router.get("/warehouse-status")
def warehouse_status(_user=Depends(require_orion_dashboard)):
    """When the warehouse was last loaded. The dashboards read the warehouse, so this is how current they are."""
    return {**load_status(), "autoload_minutes": autoload_minutes()}


@router.get("/records")
def list_record_sets(user=Depends(require_orion_dashboard)):
    """The record sets the signed-in user may open from a chart."""
    return {"datasets": records.datasets_for(user)}


@router.get("/records/{dataset}")
def get_records(
    dataset: str,
    request: Request,
    q: str = "",
    sort: Optional[str] = None,
    direction: Optional[str] = Query(default=None, alias="dir"),
    page: int = 1,
    size: int = 25,
    export: bool = False,
    measure: Optional[str] = None,
    f: str = "",
    user=Depends(require_orion_dashboard),
):
    """The rows behind a figure, with the same filters the charts use, and the conditions set on the table's own columns (``f``)."""
    if dataset not in records.DATASETS:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Unknown record set '{dataset}'")
    if not records.allowed(dataset, user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Opening these records needs access to operational data or billing.",
        )
    filters = clean_filters(dict(request.query_params))
    # Opened from a figure, the rows are the ones that count towards it: only won, only active, no cancelled bills.
    extra: tuple[str, ...] = ()
    include_cancelled = None
    if measure:
        if measure not in explorer.MEASURES:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No figure '{measure}'")
        extra, include_cancelled = explorer.record_context(measure, dataset)
    with db_cursor() as cur:
        return records.fetch(
            cur, dataset, filters, q=q, sort=sort, direction=direction, page=page, size=size, export=export,
            extra=extra, include_cancelled=include_cancelled, column_filters_=filters_or_400(f),
        )


@router.get("/explore/{measure}")
def explore_measure(measure: str, request: Request, _user=Depends(require_orion_dashboard)):
    """A key figure by year, month and every dimension that applies, for the drill-down opened from its tile."""
    if measure not in explorer.MEASURES:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No drill-down for '{measure}'")
    with db_cursor() as cur:
        return explorer.explore(cur, measure, clean_filters(dict(request.query_params)))


@router.get("/forecast")
def get_forecast(request: Request, _user=Depends(require_orion_dashboard)):
    """What the next month, quarter, half-year, year and three years are likely to look like, for the whole business or one client, domain or case."""
    return build_forecast(dict(request.query_params))


@router.get("")
def get_default_view(request: Request, _user=Depends(require_orion_dashboard)):
    return build_view(DEFAULT_VIEW, dict(request.query_params))


@router.get("/{view}")
def get_view(view: str, request: Request, user=Depends(require_orion_dashboard)):
    if view not in VIEWS:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Unknown dashboard '{view}'"
        )
    if not view_allowed(view, user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This dashboard needs Bank access.")
    return build_view(view, dict(request.query_params), bank_access=bool(can_access_bank(user)))
