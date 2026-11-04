import re
from dataclasses import dataclass
from typing import Any

from app import column_filters
from app.database import db_cursor
from app.query import escape_like, normalize_dir, normalize_search, normalize_sort, quote_ident, search_sql


# "No version was given", as distinct from a stored timestamp that is NULL.
_UNSET = object()


def insert(table, columns, values, user_id=None, returning=None, cur=None):
    """Insert one record, remembering which user created it. With ``returning`` (a column), gives that column's value.
    With ``cur`` it is written in the caller's transaction, which the caller commits."""
    columns = [*columns, "created_by", "last_updated_by"]
    values = [*values, user_id, user_id]
    cols = ", ".join(columns)
    placeholders = ", ".join(["%s"] * len(values))
    query = f"INSERT INTO {table} ({cols}) VALUES ({placeholders})"
    if returning:
        query += f" RETURNING {_sql_ident(returning)}"
    if cur is not None:
        cur.execute(query, values)
        return cur.fetchone()[0] if returning else None
    with db_cursor(commit=True) as own:
        own.execute(query, values)
        return own.fetchone()[0] if returning else None


def _sql_ident(name: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
        raise ValueError(f"Invalid identifier: {name}")
    return name


def _sql_table(name: str) -> str:
    parts = name.split(".")
    if not parts or not all(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", part) for part in parts):
        raise ValueError(f"Invalid table: {name}")
    return ".".join(parts)


def _key_missing(row: dict, key_cols: list[str]) -> bool:
    return any(row.get(col) is None or row.get(col) == "" for col in key_cols)


class MergeError(ValueError):
    """A row of an upload cannot be merged. The message is safe to show; ``row`` is its row in the sheet."""

    def __init__(self, message: str, row: int | None = None):
        super().__init__(message)
        self.row = row


_NUMERIC = {"numeric", "integer", "bigint", "smallint", "double precision", "real"}


def _column_types(cur, table: str) -> dict[str, str]:
    schema, name = table.split(".")
    cur.execute(
        "SELECT column_name, data_type FROM information_schema.columns WHERE table_schema = %s AND table_name = %s",
        (schema, name),
    )
    return {col: kind for col, kind in cur.fetchall()}


def _same(col: str, kind: str | None) -> str:
    """SQL that says a column holds the value given. Numbers and dates are compared as numbers and dates: as text,
    1200 and 1200.00 are different, and a stored 1200.00 would never match an uploaded 1200."""
    if kind in _NUMERIC:
        return f"{col} = %s::numeric"
    if kind == "date":
        return f"{col} = %s::date"
    if kind == "boolean":
        return f"{col} = %s::boolean"
    return f"lower(btrim({col}::text)) = lower(btrim(%s::text))"


def upsert_many(table, rows, key_cols, pk_column, match_filter=None, user_id=None, fallback_cols=None, finalize=None, after_insert=None):
    """Insert, or update when the row is about a record that already exists.

    A row says which record it is about in one of two ways. If it carries ``__code`` (the record's own code) that record is
    updated, and an unknown code is an error. Otherwise it is matched on ``key_cols``, or on ``fallback_cols`` when the key is
    blank; no match inserts. A key that matches MORE THAN ONE record is an error, never a guess. Any error stops the whole
    upload and nothing is saved.

    Blank incoming values do not wipe columns already stored. ``__row`` is the row's number in the sheet, for messages.
    ``match_filter`` is extra SQL an existing row must satisfy to count as a match, for rows that an upload must never
    overwrite. ``finalize(stored, changes)`` may adjust what an update writes, given the stored record.
    ``user_id`` is recorded as the creator of new rows and the last editor of updated ones.
    A row may carry ``__extra`` (values that are not columns of the table): for a NEW row ``after_insert(cur, code, extra, excel_row)`` is called in the
    same transaction with the new row's key, and for a row that updates an existing record they are refused, never ignored.
    """
    inserted = 0
    updated = 0
    if not rows:
        return inserted, updated
    table_sql = _sql_table(table)
    pk_sql = _sql_ident(pk_column)
    with db_cursor(commit=True) as cur:
        kinds = _column_types(cur, table)

        def find(cols, values):
            where = " AND ".join(_same(_sql_ident(col), kinds.get(col)) for col in cols)
            if match_filter:
                where += f" AND ({match_filter})"
            cur.execute(f"SELECT {pk_sql} FROM {table_sql} WHERE {where} ORDER BY {pk_sql}", values)
            return [found[0] for found in cur.fetchall()]

        for source in rows:
            row = dict(source)
            excel_row = row.pop("__row", None)
            code = row.pop("__code", None)
            extra = row.pop("__extra", None)
            match_cols: list[str] = []
            if code:
                found_codes = find([pk_column], [code])
                if not found_codes:
                    raise MergeError(
                        f"{pk_column} {code} was not found, so there is no record to update. Remove the code to add it as a new record.",
                        excel_row,
                    )
                found = found_codes[0]
            else:
                match_cols = list(key_cols) if key_cols and not _key_missing(row, key_cols) else (
                    list(fallback_cols) if fallback_cols and not _key_missing(row, fallback_cols) else [])
                found = None
                if match_cols:
                    found_codes = find(match_cols, [row.get(col) for col in match_cols])
                    if len(found_codes) > 1:
                        shown = ", ".join(f"{col} {row.get(col)}" for col in match_cols)
                        more = "..." if len(found_codes) > 6 else ""
                        raise MergeError(
                            f"{len(found_codes)} records match ({shown}): {', '.join(map(str, found_codes[:6]))}{more}. "
                            f"Add a {pk_column} column with the code of the one you mean.",
                            excel_row,
                        )
                    found = found_codes[0] if found_codes else None
            if found is None:
                fresh = {**row, "created_by": user_id, "last_updated_by": user_id}
                columns = list(fresh.keys())
                cols = ", ".join(_sql_ident(col) for col in columns)
                placeholders = ", ".join(["%s"] * len(columns))
                cur.execute(f"INSERT INTO {table_sql} ({cols}) VALUES ({placeholders}) RETURNING {pk_sql}", list(fresh.values()))
                if extra and after_insert:
                    after_insert(cur, cur.fetchone()[0], extra, excel_row)
                inserted += 1
                continue
            if extra:
                raise MergeError(
                    "Paid On, Paid From and Payment Reference apply only to a new expense. This row is about an expense that already exists: "
                    "record its payments in Bank > Payables.",
                    excel_row,
                )
            # A row matched on its key keeps the key as it is; a row that names its record may change anything
            changes = {col: value for col, value in row.items() if col != pk_column and value is not None and col not in match_cols}
            if finalize:
                cur.execute(f"SELECT * FROM {table_sql} WHERE {pk_sql} = %s", (found,))
                stored = dict(zip([d[0] for d in cur.description], cur.fetchone()))
                changes = finalize(stored, changes)
            if changes:
                set_sql = ", ".join(f"{_sql_ident(col)} = %s" for col in changes)
                cur.execute(
                    f"UPDATE {table_sql} SET {set_sql}, last_updated_timestamp = CURRENT_TIMESTAMP, "
                    f"last_updated_by = %s WHERE {pk_sql} = %s",
                    [*changes.values(), user_id, found],
                )
            updated += 1
    return inserted, updated


def update(table, columns, values, record_id, pk_column="id", user_id=None, expected_updated=_UNSET):
    """Update one record, remembering which user changed it last.

    When ``expected_updated`` is given it is the ``last_updated_timestamp`` the caller read the record with, and the row is
    changed only if it still has that value: the check and the write are one statement, so two people saving the same
    record cannot both win. Returns whether a row was changed (False means someone changed or deleted it first).
    """
    set_clause = ", ".join([f"{col} = %s" for col in columns])
    set_clause += ", last_updated_timestamp = CURRENT_TIMESTAMP, last_updated_by = %s"
    query = f"UPDATE {table} SET {set_clause} WHERE {pk_column} = %s"
    params = values + [user_id, record_id]
    if expected_updated is not _UNSET:
        query += " AND last_updated_timestamp IS NOT DISTINCT FROM %s::timestamptz"
        params.append(expected_updated)
    with db_cursor(commit=True) as cur:
        cur.execute(query, params)
        return cur.rowcount > 0


def delete_record(table, record_id, pk_column="id", user_id=None):
    """Delete one record and write down who did, in the same transaction.

    The row leaves nothing behind, so orion_ods.record_deleted is what the warehouse reads
    to say who removed it.
    """
    with db_cursor(commit=True) as cur:
        cur.execute(f"DELETE FROM {table} WHERE {pk_column} = %s", (record_id,))
        if cur.rowcount:
            cur.execute(
                "INSERT INTO orion_ods.record_deleted (table_name, record_code, deleted_by) VALUES (%s, %s, %s)",
                (table, str(record_id), user_id),
            )


def fetch_dropdown(table, display_col, pk_column="id", from_sql=None):
    source = (from_sql or table).strip()
    query = f"""
        SELECT BTRIM({pk_column}::text),
               COALESCE(NULLIF(BTRIM(({display_col})::text), ''), BTRIM({pk_column}::text)) AS label
        FROM {source}
        ORDER BY 2
    """
    with db_cursor() as cur:
        cur.execute(query)
        return cur.fetchall()


def fetch_display_label(table, display_col, pk_column, pk_value, from_sql=None):
    """Name (or other display column) for one related row. Used to hydrate update forms."""
    if pk_value is None or pk_value == "":
        return None
    source = (from_sql or table).strip()
    query = f"""
        SELECT COALESCE(NULLIF(BTRIM(({display_col})::text), ''), BTRIM({pk_column}::text))
        FROM {source}
        WHERE BTRIM({pk_column}::text) = BTRIM(%s::text)
        LIMIT 1
    """
    with db_cursor() as cur:
        cur.execute(query, (str(pk_value),))
        row = cur.fetchone()
    return row[0] if row and row[0] else None


def fetch_by_id(table, record_id, pk_column="id"):
    with db_cursor() as cur:
        cur.execute(f"SELECT * FROM {table} WHERE {pk_column} = %s", (record_id,))
        row = cur.fetchone()
        if not row:
            return None
        cols = [desc[0] for desc in cur.description]
        return dict(zip(cols, row))


def count_rows(table) -> int:
    with db_cursor() as cur:
        cur.execute(f"SELECT COUNT(*) FROM {table}")
        return int(cur.fetchone()[0])


def _columns_for(source: str, *, subquery: bool = False) -> list[str]:
    sql = f"SELECT * FROM ({source}) preview LIMIT 0" if subquery else f"SELECT * FROM {source} LIMIT 0"
    with db_cursor() as cur:
        cur.execute(sql)
        return [desc[0] for desc in cur.description]


def source_without(table: str, hidden: list[str]) -> str:
    """A SELECT of every column of ``table`` except ``hidden``, to pass to ``fetch_preview(source_sql=...)``.

    The hidden columns are then absent from what is shown, searched and sorted, not just from the output.
    """
    columns = [col for col in _columns_for(_sql_table(table)) if col not in hidden]
    return f"SELECT {', '.join(quote_ident(col) for col in columns)} FROM {_sql_table(table)}"


def _columns_and_kinds(source: str, *, subquery: bool = False) -> tuple[list[str], dict[str, str]]:
    """The columns of a table or preview SQL, and what each holds (text, number, date or bool), from one empty read."""
    sql = f"SELECT * FROM ({source}) preview LIMIT 0" if subquery else f"SELECT * FROM {source} LIMIT 0"
    with db_cursor() as cur:
        cur.execute(sql)
        described = [(desc[0], column_filters.kind_of_type_code(desc[1])) for desc in cur.description]
    return [name for name, _kind in described], dict(described)


@dataclass
class Preview:
    columns: list[str]
    rows: list[Any]
    matched: int
    kinds: dict[str, str]


def fetch_preview_ex(
    table: str,
    n: int | None = 10,
    *,
    search: str | None = None,
    sort: str | None = None,
    direction: str | None = None,
    source_sql: str | None = None,
    default_sort: str | None = "created_timestamp",
    fallback_order: str | None = None,
    filters: list[dict[str, Any]] | None = None,
) -> Preview:
    """Rows from a table or preview SQL, searched, filtered by column and sorted across the full source, with what each column holds."""
    source = source_sql or table
    subquery = bool(source_sql)
    columns, kinds = _columns_and_kinds(source, subquery=subquery)
    query_text = normalize_search(search)
    sort_col = normalize_sort(sort, columns)
    if not sort_col and default_sort in columns:
        sort_col = default_sort
        if direction is None:
            direction = "desc"
    order_dir = normalize_dir(direction)
    where_sql, where_params = search_sql(columns, query_text)
    if filters:
        filter_sql, filter_params = column_filters.build(filters, {col: (quote_ident(col), kinds[col]) for col in columns})
        if filter_sql:
            where_sql = f"{where_sql} AND {filter_sql}" if where_sql else filter_sql
            where_params = [*where_params, *filter_params]
    from_sql = f"({source}) preview" if subquery else source
    filters_sql = f" WHERE {where_sql}" if where_sql else ""
    if sort_col:
        order_sql = f" ORDER BY {quote_ident(sort_col)} {order_dir} NULLS LAST"
    elif fallback_order:
        extra = re.sub(r"\b[A-Za-z_][A-Za-z0-9_]*\.", "", fallback_order.strip())
        inner_order = extra if extra.upper().startswith("ORDER") else f"ORDER BY {extra}"
        if subquery:
            from_sql = f"({source.rstrip()} {inner_order}) preview"
            order_sql = ""
        else:
            order_sql = f" {inner_order}"
    else:
        order_sql = ""
    params = list(where_params)
    limit_sql = ""
    if n is not None:
        limit_sql = " LIMIT %s"
        params.append(int(n))
    with db_cursor() as cur:
        cur.execute(f"SELECT COUNT(*) FROM {from_sql}{filters_sql}", where_params)
        matched = int(cur.fetchone()[0])
        cur.execute(f"SELECT * FROM {from_sql}{filters_sql}{order_sql}{limit_sql}", params)
        data = cur.fetchall()
        cols = [desc[0] for desc in cur.description]
    return Preview(cols, data, matched, kinds)


def fetch_preview(table: str, n: int | None = 10, **kwargs):
    """``fetch_preview_ex`` as (columns, rows, matched), for the callers that need nothing more."""
    found = fetch_preview_ex(table, n, **kwargs)
    return found.columns, found.rows, found.matched


MAX_PICK = 100


def fetch_column_values(
    table: str,
    column: str,
    *,
    search: str | None = None,
    source_sql: str | None = None,
    filters: list[dict[str, Any]] | None = None,
    contains: str | None = None,
    limit: int = MAX_PICK,
) -> dict[str, Any]:
    """The values a column holds, most common first, with how many rows each is on, to pick from in a column filter.

    The rows counted are those the search and the *other* columns' filters leave (this column's own filter is ignored, so the list shows
    what else could be picked). ``contains`` narrows the list to values with that text in them. ``value`` None is the rows with nothing in it.
    """
    source = source_sql or table
    subquery = bool(source_sql)
    columns, kinds = _columns_and_kinds(source, subquery=subquery)
    if column not in columns:
        raise column_filters.FilterError("There is no such column.")
    clauses: list[str] = []
    params: list[Any] = []
    where_sql, where_params = search_sql(columns, normalize_search(search))
    if where_sql:
        clauses.append(where_sql)
        params += where_params
    if filters:
        filter_sql, filter_params = column_filters.build(filters, {col: (quote_ident(col), kinds[col]) for col in columns}, skip=column)
        if filter_sql:
            clauses.append(filter_sql)
            params += filter_params
    needle = normalize_search(contains)
    shown = f"({quote_ident(column)})::text"
    if needle:
        clauses.append(f"{shown} ILIKE %s ESCAPE '\\'")
        params.append(f"%{escape_like(needle)}%")
    from_sql = f"({source}) preview" if subquery else source
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    cap = max(1, min(int(limit), 500))
    with db_cursor() as cur:
        cur.execute(
            f"SELECT {shown} AS value, COUNT(*) AS n FROM {from_sql}{where} GROUP BY 1 ORDER BY 2 DESC, 1 NULLS LAST LIMIT %s",
            [*params, cap + 1],
        )
        found = cur.fetchall()
    values = [{"value": value if value != "" else None, "count": int(count)} for value, count in found[:cap]]
    return {"values": values, "truncated": len(found) > cap, "kind": kinds[column]}
