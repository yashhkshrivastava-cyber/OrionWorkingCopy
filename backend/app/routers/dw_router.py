import math
import re
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query

from app.database import db_cursor
from app.db_utils import fetch_column_values, fetch_preview_ex
from app.routers.column_filter_params import filters_or_400, values_or_400
from app.dependencies import require_dw
from app.dw_auto import autoload_minutes
from app.auth import can_write_ods
from app.dw_sync import DW_TABLES, dw_preview, load_status, table_list
from app.excel_import import EXPORT_LIMITS, INLINE_PREVIEW_LIMITS, excel_file_response, parse_preview_limit

router = APIRouter(prefix="/dw", tags=["dw"])


def _serialize_row(cols, row):
    result = {}
    for i, col in enumerate(cols):
        val = row[i]
        if hasattr(val, "isoformat"):
            val = val.isoformat()
        elif isinstance(val, (float, Decimal)) and not math.isfinite(val):
            val = None  # a NaN that was stored cannot be written as JSON; shown empty it can still be found and corrected
        result[col] = val
    return result


def _limit(raw: str, allowed: set[int | None]) -> int | None:
    try:
        return parse_preview_limit(raw, allowed)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _preview_sql(sql: str, limit: int | None) -> str:
    stripped = re.sub(r"\s+LIMIT\s+\d+\s*$", "", sql.strip(), flags=re.IGNORECASE)
    if limit is None:
        return stripped
    return f"{stripped} LIMIT {int(limit)}"


def _split_order(sql: str) -> tuple[str, str]:
    match = re.search(r"\sORDER\s+BY\s+.+$", sql.strip(), flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return sql, ""
    return sql[: match.start()].strip(), match.group(0).strip()


def _table(name: str) -> dict:
    meta = DW_TABLES.get(name)
    if not meta:
        raise HTTPException(status_code=404, detail="Unknown warehouse table")
    return meta


@router.get("/tables")
def list_tables(_user=Depends(require_dw)):
    return {"tables": table_list()}


@router.get("/dimensions")
def list_dimensions(_user=Depends(require_dw)):
    return {"dimensions": [item["name"] for item in table_list()]}


@router.get("/status")
def status(_user=Depends(require_dw)):
    return {**load_status(), "autoload_minutes": autoload_minutes()}


@router.get("/{name}/preview")
def preview_table(
    name: str,
    limit: str = Query("3"),
    q: str = Query(""),
    sort: str = Query(""),
    dir: str = Query("desc"),
    f: str = Query(""),
    user=Depends(require_dw),
):
    meta = _table(name)
    size = _limit(limit, INLINE_PREVIEW_LIMITS)
    source = _preview_sql(dw_preview(meta, can_write_ods(user)), None)
    base, order = _split_order(source)
    user_sort = sort or None
    found = fetch_preview_ex(
        name,
        size,
        search=q,
        sort=user_sort,
        direction=dir,
        source_sql=base if user_sort else source,
        default_sort=None,
        fallback_order=order if user_sort else None,
        filters=filters_or_400(f),
    )
    cols, rows, matched = found.columns, found.rows, found.matched
    return {
        "columns": cols,
        "rows": [_serialize_row(cols, r) for r in rows],
        "total": matched if not q.strip() else _dw_total(source),
        "matched": matched,
        "kinds": found.kinds,
        "limit": size,
        "q": q,
        "sort": sort,
        "dir": dir,
    }


@router.get("/{name}/values")
def column_values(
    name: str,
    column: str = Query(...),
    q: str = Query(""),
    contains: str = Query(""),
    f: str = Query(""),
    user=Depends(require_dw),
):
    """The values a column holds (with how many rows each is on), to pick from in the column's filter."""
    meta = _table(name)
    base, _order = _split_order(_preview_sql(dw_preview(meta, can_write_ods(user)), None))
    return values_or_400(lambda: fetch_column_values(name, column, search=q, source_sql=base, filters=filters_or_400(f), contains=contains))


@router.get("/{name}/export")
def export_table(
    name: str,
    limit: str = Query("100"),
    q: str = Query(""),
    sort: str = Query(""),
    dir: str = Query("desc"),
    f: str = Query(""),
    user=Depends(require_dw),
):
    meta = _table(name)
    size = _limit(limit, EXPORT_LIMITS)
    source = _preview_sql(dw_preview(meta, can_write_ods(user)), None)
    base, order = _split_order(source)
    user_sort = sort or None
    found = fetch_preview_ex(
        name,
        size,
        search=q,
        sort=user_sort,
        direction=dir,
        source_sql=base if user_sort else source,
        default_sort=None,
        fallback_order=order if user_sort else None,
        filters=filters_or_400(f),
    )
    cols, rows, _matched = found.columns, found.rows, found.matched
    return excel_file_response(name, size, cols, rows)


def _dw_total(source: str) -> int:
    with db_cursor() as cur:
        cur.execute(f"SELECT COUNT(*) FROM ({source}) preview")
        return int(cur.fetchone()[0])
