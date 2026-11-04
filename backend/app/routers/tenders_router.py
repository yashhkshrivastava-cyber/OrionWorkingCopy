"""Tenders: GeM tender searches, the bids they found, and checking GeM now. Reading needs tenders access; changing a search,
checking now and shortlisting or dismissing a bid need tenders write."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app import tenders
from app.dependencies import require_tenders, require_tenders_write

router = APIRouter(prefix="/tenders", tags=["tenders"])


class SearchIn(BaseModel):
    name: str = Field(max_length=200)
    tender_types: list[str] = Field(default_factory=list, max_length=50)
    cities: list[str] = Field(default_factory=list, max_length=50)
    bid_kind: str = "service"
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    include_unpriced: bool = True
    is_active: bool = True
    portal: str = "gem"


class StatusIn(BaseModel):
    status: str


def _bad(exc: Exception) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


def _missing(exc: Exception) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


def _portal(value: str) -> str:
    try:
        return tenders.portal_of(value)
    except tenders.TenderError as exc:
        raise _bad(exc) from exc


@router.get("/status")
def get_status(portal: str = Query("gem"), _user=Depends(require_tenders)):
    return tenders.status(_portal(portal))


@router.get("/searches")
def get_searches(portal: str = Query("gem"), _user=Depends(require_tenders)):
    return tenders.list_searches(_portal(portal))


@router.post("/searches", status_code=status.HTTP_201_CREATED)
def post_search(body: SearchIn, user=Depends(require_tenders_write)):
    try:
        return tenders.create_search(body.model_dump(), user.get("id"))
    except tenders.TenderError as exc:
        raise _bad(exc) from exc


@router.put("/searches/{search_id}")
def put_search(search_id: int, body: SearchIn, _user=Depends(require_tenders_write)):
    try:
        return tenders.update_search(search_id, body.model_dump())
    except tenders.TenderError as exc:
        raise _bad(exc) from exc
    except LookupError as exc:
        raise _missing(exc) from exc


@router.delete("/searches/{search_id}")
def remove_search(search_id: int, _user=Depends(require_tenders_write)):
    try:
        tenders.delete_search(search_id)
    except LookupError as exc:
        raise _missing(exc) from exc
    return {"ok": True}


@router.get("/searches/{search_id}/bids")
def get_bids(
    search_id: int,
    match_status: str = Query("new", alias="status"),
    include_closed: bool = False,
    _user=Depends(require_tenders),
):
    try:
        tenders.get_search(search_id)
        return tenders.search_bids(search_id, match_status, include_closed)
    except tenders.TenderError as exc:
        raise _bad(exc) from exc
    except LookupError as exc:
        raise _missing(exc) from exc


@router.put("/searches/{search_id}/bids/{bid_id}/status")
def put_bid_status(search_id: int, bid_id: int, body: StatusIn, user=Depends(require_tenders_write)):
    try:
        return tenders.set_status(search_id, bid_id, body.status, user.get("id"))
    except tenders.TenderError as exc:
        raise _bad(exc) from exc
    except LookupError as exc:
        raise _missing(exc) from exc


@router.post("/check", status_code=status.HTTP_202_ACCEPTED)
def post_check(portal: str = Query("gem"), user=Depends(require_tenders_write)):
    """Check one portal now, in the background. GET /tenders/status?portal= says when it has finished."""
    try:
        tenders.start_check(_portal(portal), user.get("id"))
    except tenders.CheckBusy as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except tenders.TenderError as exc:
        raise _bad(exc) from exc
    return {"started": True}
