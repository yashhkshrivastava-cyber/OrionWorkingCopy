"""The SQL editor: browse the database, run queries and scripts, keep the ones worth keeping, make views.

For administrators only, and audited: every run (what, by whom, in which mode, how it ended) is kept in ``orion_ods.sql_query_log`` and cannot be
changed from here. ``sql_guard`` decides what a statement may be before anything reaches the database; this module runs what it allowed, in a
transaction of its own (read-only unless the person turned on "Allow changes"), with a time limit and a row limit, and gives back the results.

``ORION_SQL_EDITOR`` is ``off``, ``readonly`` or ``full``; without it, a development computer is ``full`` and production is ``readonly``, so changes
from the editor on the office PC are switched on deliberately, in that machine's ``.env``.

No password, token or private message is readable here (``sql_guard.PRIVATE_TABLES``), and the tables Orion's own code owns can be read but not
changed (``OWNED_TABLES``): they change only through the application.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import os
import re
import threading
import time
import uuid
from datetime import date, datetime, time as clock, timedelta
from decimal import Decimal
from typing import Any

import psycopg2

from app import sql_guard
from app.database import db_cursor, raw_connection
from app.startup_checks import is_production

logger = logging.getLogger(__name__)

DEFAULT_LIMIT = 1000
MAX_LIMIT = 10_000
DEFAULT_TIMEOUT = 30
MAX_TIMEOUT = 120
EXPORT_LIMIT = 100_000
MAX_CELLS = 500_000
MAX_CELL_TEXT = 4000
MAX_LOGGED_SQL = 50_000
CATALOG_SCHEMAS = (sql_guard.REPORTS, *sql_guard.APP_SCHEMAS, "public")
_slots = threading.BoundedSemaphore(4)
_running: dict[str, tuple[int, int]] = {}  # run id -> (user id, the database session running it)
_cancelled: set[str] = set()
_lock = threading.Lock()


class RunError(ValueError):
    """The request cannot be carried out. The message is safe to show to the user."""


def mode(environ: dict[str, str] | None = None) -> str:
    """"off", "readonly" or "full". Production is read-only unless its .env says otherwise."""
    source = os.environ if environ is None else environ
    wanted = (source.get("ORION_SQL_EDITOR") or "auto").strip().lower()
    if wanted in ("off", "readonly", "full"):
        return wanted
    return "readonly" if is_production(source) else "full"


def can_use(user: dict | None) -> bool:
    return bool(user and user.get("role") == "admin" and mode() != "off")


# --------------------------------------------------------------------------------------------------------------------
# What is in the database


def status() -> dict[str, Any]:
    with db_cursor() as cur:
        cur.execute("SELECT current_database(), current_user, current_setting('server_version')")
        database, role, version = cur.fetchone()
    return {
        "mode": mode(), "can_change": mode() == "full", "database": database, "role": role, "version": version,
        "default_limit": DEFAULT_LIMIT, "max_limit": MAX_LIMIT, "default_timeout": DEFAULT_TIMEOUT, "max_timeout": MAX_TIMEOUT,
        "reports_schema": sql_guard.REPORTS, "max_statements": sql_guard.MAX_STATEMENTS,
    }


def _private(name: str) -> bool:
    return bool(sql_guard.PRIVATE_TABLES.match(name))


def catalog() -> dict[str, Any]:
    """Every schema, with its tables, views and materialized views, and their columns, keys and sizes; for the tree and for autocomplete."""
    schemas = list(CATALOG_SCHEMAS)
    with db_cursor() as cur:
        cur.execute(
            """SELECT n.nspname, c.relname, c.relkind::text, c.reltuples::bigint, pg_total_relation_size(c.oid), obj_description(c.oid, 'pg_class'), c.oid
                 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = ANY(%s) AND c.relkind IN ('r', 'p', 'v', 'm', 'f') AND NOT c.relispartition
                ORDER BY n.nspname, c.relname""",
            (schemas,),
        )
        objects = cur.fetchall()
        cur.execute(
            """SELECT c.oid, a.attname, format_type(a.atttypid, a.atttypmod), a.attnotnull, pg_get_expr(d.adbin, d.adrelid)
                 FROM pg_attribute a
                 JOIN pg_class c ON c.oid = a.attrelid JOIN pg_namespace n ON n.oid = c.relnamespace
                 LEFT JOIN pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum
                WHERE n.nspname = ANY(%s) AND c.relkind IN ('r', 'p', 'v', 'm', 'f') AND a.attnum > 0 AND NOT a.attisdropped
                ORDER BY c.oid, a.attnum""",
            (schemas,),
        )
        columns: dict[int, list[dict[str, Any]]] = {}
        for oid, name, type_name, not_null, default in cur.fetchall():
            columns.setdefault(oid, []).append({"name": name, "type": type_name, "nullable": not not_null, "default": default, "pk": False, "fk": None})
        cur.execute(
            """SELECT con.conrelid, con.contype::text, ARRAY(SELECT a.attname FROM pg_attribute a WHERE a.attrelid = con.conrelid AND a.attnum = ANY(con.conkey)),
                      fn.nspname, fc.relname, ARRAY(SELECT a.attname FROM pg_attribute a WHERE a.attrelid = con.confrelid AND a.attnum = ANY(con.confkey))
                 FROM pg_constraint con
                 JOIN pg_class c ON c.oid = con.conrelid JOIN pg_namespace n ON n.oid = c.relnamespace
                 LEFT JOIN pg_class fc ON fc.oid = con.confrelid LEFT JOIN pg_namespace fn ON fn.oid = fc.relnamespace
                WHERE n.nspname = ANY(%s) AND con.contype IN ('p', 'f')""",
            (schemas,),
        )
        for oid, kind, names, f_schema, f_table, f_names in cur.fetchall():
            for column in columns.get(oid, []):
                if column["name"] in names:
                    if kind == "p":
                        column["pk"] = True
                    elif kind == "f":
                        column["fk"] = f"{f_schema}.{f_table}({', '.join(f_names)})"
        cur.execute(
            """SELECT n.nspname, p.proname, pg_get_function_arguments(p.oid), format_type(p.prorettype, NULL)
                 FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
                WHERE n.nspname = ANY(%s) AND p.prokind = 'f' ORDER BY n.nspname, p.proname""",
            (schemas,),
        )
        functions = [{"schema": s, "name": n, "args": a, "returns": r} for s, n, a, r in cur.fetchall()]
    kinds = {"r": "table", "p": "table", "v": "view", "m": "materialized view", "f": "foreign table"}
    out: dict[str, list[dict[str, Any]]] = {schema: [] for schema in schemas}
    for schema, name, kind, rows, size, comment, oid in objects:
        private = _private(name)
        out[schema].append({
            "name": name, "kind": kinds.get(kind, kind), "rows": rows if rows >= 0 else None, "size": int(size), "comment": comment, "private": private,
            "columns": [] if private else columns.get(oid, []),
        })
    return {"schemas": [{"name": schema, "objects": out[schema]} for schema in schemas], "functions": functions}


def object_detail(schema: str, name: str) -> dict[str, Any]:
    """One table or view: its columns, keys, indexes, triggers, size and statistics, and a CREATE statement for it."""
    if schema not in CATALOG_SCHEMAS:
        raise RunError("That schema is not one the SQL editor shows.")
    if _private(name):
        raise RunError(f"{name} holds passwords, sessions, tokens or private messages and is not shown here.")
    with db_cursor() as cur:
        cur.execute(
            """SELECT c.oid, c.relkind::text, c.reltuples::bigint, pg_total_relation_size(c.oid), pg_relation_size(c.oid), obj_description(c.oid, 'pg_class'),
                      pg_get_userbyid(c.relowner)
                 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = %s AND c.relname = %s AND c.relkind IN ('r', 'p', 'v', 'm', 'f')""",
            (schema, name),
        )
        found = cur.fetchone()
        if not found:
            raise RunError("That table or view does not exist (it may have been dropped).")
        oid, relkind, rows, total, table_size, comment, owner = found
        cur.execute(
            """SELECT a.attname, format_type(a.atttypid, a.atttypmod), a.attnotnull, pg_get_expr(d.adbin, d.adrelid), col_description(a.attrelid, a.attnum), a.attidentity::text
                 FROM pg_attribute a LEFT JOIN pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum
                WHERE a.attrelid = %s AND a.attnum > 0 AND NOT a.attisdropped ORDER BY a.attnum""",
            (oid,),
        )
        columns = [{"name": n, "type": t, "nullable": not nn, "default": d, "comment": c, "identity": bool(i)} for n, t, nn, d, c, i in cur.fetchall()]
        cur.execute("SELECT conname, contype::text, pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid = %s ORDER BY contype, conname", (oid,))
        constraints = [{"name": n, "kind": {"p": "primary key", "f": "foreign key", "u": "unique", "c": "check", "x": "exclusion"}.get(k, k), "definition": d} for n, k, d in cur.fetchall()]
        cur.execute(
            """SELECT con.conname, n.nspname, c.relname, pg_get_constraintdef(con.oid)
                 FROM pg_constraint con JOIN pg_class c ON c.oid = con.conrelid JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE con.confrelid = %s AND con.contype = 'f' ORDER BY n.nspname, c.relname""",
            (oid,),
        )
        referenced_by = [{"name": n, "table": f"{s}.{t}", "definition": d} for n, s, t, d in cur.fetchall() if not _private(t)]
        cur.execute("SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = %s AND tablename = %s ORDER BY indexname", (schema, name))
        indexes = [{"name": n, "definition": d} for n, d in cur.fetchall()]
        cur.execute("SELECT tgname, pg_get_triggerdef(oid) FROM pg_trigger WHERE tgrelid = %s AND NOT tgisinternal ORDER BY tgname", (oid,))
        triggers = [{"name": n, "definition": d} for n, d in cur.fetchall()]
        view_sql = None
        if relkind in ("v", "m"):
            cur.execute("SELECT pg_get_viewdef(%s, true)", (oid,))
            view_sql = (cur.fetchone()[0] or "").strip()
        stats: dict[str, Any] = {}
        if relkind in ("r", "p"):
            cur.execute(
                """SELECT n_live_tup, n_dead_tup, n_tup_ins, n_tup_upd, n_tup_del, last_vacuum, last_autovacuum, last_analyze, last_autoanalyze
                     FROM pg_stat_user_tables WHERE relid = %s""",
                (oid,),
            )
            row = cur.fetchone()
            if row:
                keys = ("live_rows", "dead_rows", "inserts", "updates", "deletes", "last_vacuum", "last_autovacuum", "last_analyze", "last_autoanalyze")
                stats = {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in zip(keys, row)}
    kind = {"r": "table", "p": "table", "v": "view", "m": "materialized view", "f": "foreign table"}[relkind]
    return {
        "schema": schema, "name": name, "kind": kind, "owner": owner, "comment": comment, "estimated_rows": rows if rows >= 0 else None,
        "total_bytes": int(total), "table_bytes": int(table_size), "columns": columns, "constraints": constraints, "referenced_by": referenced_by,
        "indexes": indexes, "triggers": triggers, "stats": stats, "view_sql": view_sql, "ddl": _ddl(schema, name, kind, columns, constraints, indexes, view_sql),
    }


def _quote(name: str) -> str:
    return name if re.fullmatch(r"[a-z_][a-z0-9_]*", name) else '"' + name.replace('"', '""') + '"'


def _ddl(schema: str, name: str, kind: str, columns: list[dict[str, Any]], constraints: list[dict[str, Any]], indexes: list[dict[str, Any]], view_sql: str | None) -> str:
    target = f"{_quote(schema)}.{_quote(name)}"
    if kind == "view":
        return f"CREATE OR REPLACE VIEW {target} AS\n{view_sql};"
    if kind == "materialized view":
        return f"CREATE MATERIALIZED VIEW {target} AS\n{view_sql};"
    lines = []
    for column in columns:
        text = f"    {_quote(column['name'])} {column['type']}"
        if column["identity"]:
            text += " GENERATED BY DEFAULT AS IDENTITY"
        elif column["default"]:
            text += f" DEFAULT {column['default']}"
        if not column["nullable"]:
            text += " NOT NULL"
        lines.append(text)
    lines += [f"    CONSTRAINT {_quote(c['name'])} {c['definition']}" for c in constraints]
    created = f"CREATE TABLE {target} (\n" + ",\n".join(lines) + "\n);"
    return "\n".join([created, *[f"{i['definition']};" for i in indexes if not any(i['name'] == c['name'] for c in constraints)]])


# --------------------------------------------------------------------------------------------------------------------
# Running


def _cell(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        return value if value == value and value not in (float("inf"), float("-inf")) else str(value)
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date, clock)):
        return value.isoformat()
    if isinstance(value, timedelta):
        return str(value)
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        data = bytes(value)
        return "\\x" + data[:64].hex() + ("…" if len(data) > 64 else "")
    if isinstance(value, (dict, list)):
        text = json.dumps(value, default=str)
        return text if len(text) <= MAX_CELL_TEXT else text[:MAX_CELL_TEXT] + "…"
    text = str(value)
    return text if len(text) <= MAX_CELL_TEXT else text[:MAX_CELL_TEXT] + "…"


def _type_names(cur, oids: list[int], cache: dict[int, str]) -> None:
    missing = [oid for oid in set(oids) if oid not in cache]
    if not missing:
        return
    cur.execute("SELECT oid::int, format_type(oid, NULL) FROM pg_type WHERE oid = ANY(%s)", (missing,))
    cache.update(dict(cur.fetchall()))


def _error_info(exc: psycopg2.Error, statement: sql_guard.Statement) -> dict[str, Any]:
    diag = getattr(exc, "diag", None)
    message = (getattr(diag, "message_primary", None) or str(exc).strip().split("\n")[0]).strip()
    position = None
    if diag is not None and diag.statement_position:
        try:
            offset = int(diag.statement_position)
            before = statement.text[: max(0, offset - 1)]
            position = {"line": statement.line + before.count("\n"), "column": offset - (before.rfind("\n") + 1)}
        except (TypeError, ValueError):
            position = None
    return {"message": message, "hint": getattr(diag, "message_hint", None), "detail": getattr(diag, "message_detail", None), "code": getattr(exc, "pgcode", None), "position": position}


def _log(user: dict, sql: str, *, write: bool, status_: str, statements: int, returned: int, affected: int, rolled_back: bool, duration_ms: int, error: str | None) -> None:
    try:
        with db_cursor(commit=True) as cur:
            cur.execute(
                """INSERT INTO orion_ods.sql_query_log (user_id, username, sql_text, mode, status, statements, rows_returned, rows_affected, rolled_back, duration_ms, error)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (user.get("id"), user.get("username"), sql[:MAX_LOGGED_SQL], "write" if write else "read", status_, statements, returned, affected, rolled_back, duration_ms, (error or "")[:1000] or None),
            )
    except Exception:  # noqa: BLE001 - the audit row failing must be loud in the log, but a query already run is not undone by it
        logger.exception("Could not write the SQL editor's audit row")


def run(user: dict, sql: str, *, write: bool = False, rollback: bool = True, limit: int = DEFAULT_LIMIT, timeout: int = DEFAULT_TIMEOUT,
        run_id: str | None = None, confirm: bool = False) -> dict[str, Any]:
    """Run a script and answer with a result for each statement. Nothing is run if any statement is refused; the changes of a script that
    fails halfway are rolled back, whole. With ``write`` the script may change things (in a transaction that is committed, or, with ``rollback``, not)."""
    current = mode()
    if current == "off":
        raise RunError("The SQL editor is switched off on this server.")
    if write and current != "full":
        raise RunError("Changes from the SQL editor are switched off on this server. They are switched on with ORION_SQL_EDITOR=full in its .env.")
    limit = max(1, min(int(limit or DEFAULT_LIMIT), MAX_LIMIT))
    timeout = max(1, min(int(timeout or DEFAULT_TIMEOUT), MAX_TIMEOUT))
    started = time.monotonic()
    try:
        plan = sql_guard.vet_script(sql, may_change=write)
    except sql_guard.Blocked as exc:
        _log(user, sql, write=write, status_="blocked", statements=0, returned=0, affected=0, rolled_back=False, duration_ms=0, error=str(exc))
        return {"ok": False, "blocked": True, "error": {"message": str(exc), "hint": None, "detail": None, "code": None, "position": None}, "results": [], "run_id": run_id}
    confirmations = [reason for _stmt, verdict in plan for reason in verdict.confirm]
    if confirmations and not confirm:
        return {"ok": False, "needs_confirmation": confirmations, "results": [], "run_id": run_id}
    changes = write and any(verdict.kind != "read" for _stmt, verdict in plan)
    run_id = run_id or uuid.uuid4().hex
    if not _slots.acquire(blocking=False):
        raise RunError("Several queries are already running. Wait for one to finish, or cancel it.")
    conn = raw_connection()
    results: list[dict[str, Any]] = []
    returned = affected = 0
    failure: dict[str, Any] | None = None
    outcome = "ok"
    rolled_back = False
    try:
        conn.autocommit = False
        cur = conn.cursor()
        with _lock:
            _running[run_id] = (user.get("id") or 0, conn.get_backend_pid())
        cur.execute("SET TRANSACTION READ WRITE" if changes else "SET TRANSACTION READ ONLY")
        cur.execute("SELECT set_config('statement_timeout', %s, true), set_config('lock_timeout', '5000', true)", (str(timeout * 1000),))
        types: dict[int, str] = {}
        cells = 0
        for index, (statement, verdict) in enumerate(plan, start=1):
            began = time.monotonic()
            try:
                cur.execute(f"SET LOCAL search_path = {verdict.search_path}")
                cur.execute(statement.text)
                if cur.description:
                    description = cur.description
                    fetched = cur.fetchmany(limit + 1)
                    over = len(fetched) > limit
                    rows = [[_cell(v) for v in row] for row in fetched[:limit]]
                    cells += len(rows) * len(description)
                    if cells > MAX_CELLS:
                        keep = max(1, len(rows) - (cells - MAX_CELLS) // max(1, len(description)))
                        rows, over = rows[:keep], True
                    _type_names(cur, [d[1] for d in description], types)
                    returned += len(rows)
                    results.append({
                        "index": index, "kind": "rows", "statement": statement.text[:300], "columns": [{"name": d[0], "type": types.get(d[1], "")} for d in description],
                        "rows": rows, "truncated": over, "row_count": len(rows), "command": cur.statusmessage, "duration_ms": int((time.monotonic() - began) * 1000),
                    })
                else:
                    affected += max(0, cur.rowcount)
                    results.append({
                        "index": index, "kind": "command", "statement": statement.text[:300], "command": cur.statusmessage, "row_count": max(0, cur.rowcount),
                        "duration_ms": int((time.monotonic() - began) * 1000),
                    })
            except psycopg2.Error as exc:
                with _lock:
                    was_cancelled = run_id in _cancelled
                if was_cancelled:
                    outcome, failure = "cancelled", {"message": "You cancelled this run.", "hint": None, "detail": None, "code": "57014", "position": None}
                elif getattr(exc, "pgcode", None) == "57014":
                    outcome, failure = "error", {"message": f"It was stopped after {timeout} seconds, the time limit. Narrow the query, or raise the limit.", "hint": None, "detail": None, "code": "57014", "position": None}
                else:
                    outcome, failure = "error", _error_info(exc, statement)
                failure["statement"] = index
                break
        if failure is None and changes and not rollback:
            conn.commit()
        else:
            conn.rollback()
            rolled_back = changes
    except psycopg2.Error as exc:
        outcome, failure = "error", {"message": str(exc).strip().split("\n")[0], "hint": None, "detail": None, "code": getattr(exc, "pgcode", None), "position": None}
        rolled_back = changes
    finally:
        with _lock:
            _running.pop(run_id, None)
            _cancelled.discard(run_id)
        try:
            conn.close()
        finally:
            _slots.release()
    duration = int((time.monotonic() - started) * 1000)
    _log(user, sql, write=write, status_=outcome, statements=len(results), returned=returned, affected=affected, rolled_back=rolled_back, duration_ms=duration,
         error=failure["message"] if failure else None)
    return {"ok": failure is None, "error": failure, "results": results, "duration_ms": duration, "rolled_back": rolled_back, "changed": changes and not rolled_back and failure is None,
            "run_id": run_id, "mode": "write" if changes else "read"}


def cancel(user: dict, run_id: str) -> bool:
    """Ask the database to stop a run that is still going. A person may stop only their own."""
    with _lock:
        found = _running.get(run_id)
        if found is None or (found[0] != (user.get("id") or 0)):
            return False
        _cancelled.add(run_id)
        pid = found[1]
    with db_cursor() as cur:
        cur.execute("SELECT pg_cancel_backend(%s)", (pid,))
    return True


def export_csv(user: dict, sql: str, limit: int = EXPORT_LIMIT) -> tuple[str, str]:
    """One read-only statement's rows as CSV text, up to ``limit`` (a hundred thousand). Returns (file name, text)."""
    plan = sql_guard.vet_script(sql, may_change=False)
    if len(plan) != 1:
        raise RunError("Export one statement at a time.")
    limit = max(1, min(int(limit), EXPORT_LIMIT))
    conn = raw_connection()
    started = time.monotonic()
    count = 0
    try:
        conn.autocommit = False
        cur = conn.cursor()
        cur.execute("SET TRANSACTION READ ONLY")
        cur.execute("SELECT set_config('statement_timeout', %s, true)", (str(MAX_TIMEOUT * 1000),))
        cur.execute(f"SET LOCAL search_path = {plan[0][1].search_path}")
        cur.execute(plan[0][0].text)
        if not cur.description:
            raise RunError("That statement returns no rows to export.")
        out = io.StringIO()
        writer = csv.writer(out)
        writer.writerow([d[0] for d in cur.description])
        for row in cur.fetchmany(limit):
            writer.writerow(["" if v is None else _cell(v) for v in row])
            count += 1
        conn.rollback()
    except psycopg2.Error as exc:
        raise RunError(str(getattr(getattr(exc, "diag", None), "message_primary", None) or exc).strip().split("\n")[0]) from exc
    finally:
        conn.close()
    _log(user, sql, write=False, status_="ok", statements=1, returned=count, affected=0, rolled_back=False, duration_ms=int((time.monotonic() - started) * 1000), error=None)
    return f"query-{datetime.now().strftime('%Y%m%d-%H%M%S')}.csv", out.getvalue()


# --------------------------------------------------------------------------------------------------------------------
# Saved queries and history


def _clean_text(value: Any, label: str, limit: int, *, required: bool = False) -> str | None:
    text = " ".join(str(value or "").split())
    if required and not text:
        raise RunError(f"Give the query a {label}.")
    if len(text) > limit:
        raise RunError(f"The {label} is too long (at most {limit} characters).")
    return text or None


def saved_queries(user: dict) -> list[dict[str, Any]]:
    with db_cursor() as cur:
        cur.execute(
            """SELECT q.query_id, q.title, q.folder, q.description, q.sql_text, q.shared, q.owner_id, u.display_name, q.updated_timestamp
                 FROM orion_ods.sql_saved_query q LEFT JOIN orion_ods.app_user u ON u.id = q.owner_id
                WHERE q.owner_id = %s OR q.shared ORDER BY lower(coalesce(q.folder, '')), lower(q.title)""",
            (user["id"],),
        )
        return [
            {"id": i, "title": t, "folder": f, "description": d, "sql": s, "shared": sh, "mine": owner == user["id"], "owner": name, "updated": ts.isoformat()}
            for i, t, f, d, s, sh, owner, name, ts in cur.fetchall()
        ]


def save_query(user: dict, query_id: int | None, title: Any, sql: Any, folder: Any = None, description: Any = None, shared: bool = False) -> dict[str, Any]:
    title_text = _clean_text(title, "title", 120, required=True)
    body = str(sql or "")
    if not body.strip():
        raise RunError("There is nothing to save: the query is empty.")
    if len(body) > sql_guard.MAX_SQL:
        raise RunError("That query is too long to save.")
    folder_text, note = _clean_text(folder, "folder", 60), _clean_text(description, "description", 500)
    with db_cursor(commit=True) as cur:
        if query_id is None:
            cur.execute(
                """INSERT INTO orion_ods.sql_saved_query (owner_id, title, folder, description, sql_text, shared) VALUES (%s, %s, %s, %s, %s, %s) RETURNING query_id""",
                (user["id"], title_text, folder_text, note, body, bool(shared)),
            )
            query_id = cur.fetchone()[0]
        else:
            cur.execute(
                """UPDATE orion_ods.sql_saved_query SET title = %s, folder = %s, description = %s, sql_text = %s, shared = %s, updated_timestamp = CURRENT_TIMESTAMP
                    WHERE query_id = %s AND owner_id = %s""",
                (title_text, folder_text, note, body, bool(shared), query_id, user["id"]),
            )
            if cur.rowcount == 0:
                raise RunError("That saved query is not yours to change. Save a copy of it instead.")
    return {"id": query_id}


def delete_query(user: dict, query_id: int) -> bool:
    with db_cursor(commit=True) as cur:
        cur.execute("DELETE FROM orion_ods.sql_saved_query WHERE query_id = %s AND owner_id = %s", (query_id, user["id"]))
        return cur.rowcount > 0


def history(user: dict, *, everyone: bool = False, q: str = "", limit: int = 100) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit), 500))
    clauses, params = [], []
    if not everyone:
        clauses.append("user_id = %s")
        params.append(user["id"])
    if q.strip():
        clauses.append("sql_text ILIKE %s")
        params.append(f"%{q.strip()[:100]}%")
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with db_cursor() as cur:
        cur.execute(
            f"""SELECT log_id, username, sql_text, mode, status, statements, rows_returned, rows_affected, rolled_back, duration_ms, error, run_timestamp
                  FROM orion_ods.sql_query_log {where} ORDER BY log_id DESC LIMIT %s""",
            [*params, limit],
        )
        keys = ("id", "username", "sql", "mode", "status", "statements", "rows_returned", "rows_affected", "rolled_back", "duration_ms", "error", "at")
        return [{k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in zip(keys, row)} for row in cur.fetchall()]
