"""The column filters of a request (``?f=``), checked, for the routers that list the data tables."""

from fastapi import HTTPException, status

from app.column_filters import FilterError, parse


def filters_or_400(raw: str) -> list[dict]:
    try:
        return parse(raw)
    except FilterError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


def values_or_400(call):
    """Runs the call that lists a column's values, answering a bad filter or column as a 400."""
    try:
        return call()
    except FilterError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
