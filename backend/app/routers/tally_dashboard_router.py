from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from app import tally_explore
from app.routers.column_filter_params import filters_or_400
from app.database import db_cursor
from app.dependencies import require_tally_dashboard
from app.tally_dashboard import _clean_filters, build_tally_dashboard
from app.tally_forecast import build_tally_forecast
from app.tally_insights import validate_filters

router = APIRouter(prefix="/tally-dashboard", tags=["tally-dashboard"])

# Choices only the books drill-down uses: a ledger and an account group.
EXTRA_KEYS = ("ledger", "group")


def _filters(request: Request) -> tuple[dict[str, str], dict[str, str]]:
    raw = dict(request.query_params)
    clean, _problems = validate_filters(_clean_filters(raw))
    return clean, {k: str(raw[k]).strip() for k in EXTRA_KEYS if raw.get(k)}


@router.get("")
def get_tally_dashboard(request: Request, _user=Depends(require_tally_dashboard)):
    return build_tally_dashboard(dict(request.query_params))


@router.get("/forecast")
def get_tally_forecast(request: Request, _user=Depends(require_tally_dashboard)):
    """The forecast of what Tally says is billed, for the whole company or one client, document type, income line or cost centre."""
    return build_tally_forecast(dict(request.query_params))


@router.get("/explore/{measure}")
def explore_measure(measure: str, request: Request, _user=Depends(require_tally_dashboard)):
    """A key figure by year, month and every dimension that applies, for the drill-down opened from its tile."""
    if measure not in tally_explore.MEASURES:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No drill-down for '{measure}'")
    filters, extra = _filters(request)
    with db_cursor() as cur:
        return tally_explore.explore(cur, measure, filters, extra)


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
    _user=Depends(require_tally_dashboard),
):
    """The billed documents or ledgers behind a Tally figure, filtered the way the dashboard is."""
    if dataset != "vouchers" and dataset not in tally_explore.SNAPSHOT_DATASET:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Unknown record set '{dataset}'")
    filters, extra = _filters(request)
    # Opened from a figure, the documents are the ones that count towards it: credit notes only, documents with an EPF line.
    conditions: tuple[str, ...] = ()
    if measure:
        if measure not in tally_explore.MEASURES:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No figure '{measure}'")
        conditions = tally_explore.record_context(measure)
    with db_cursor() as cur:
        return tally_explore.records(
            cur, dataset, filters, extra, q=q, sort=sort, direction=direction, page=page, size=size, export=export,
            conditions=conditions, column_filters_=filters_or_400(f),
        )
