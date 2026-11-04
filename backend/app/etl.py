"""Runs the three ETL pipelines and keeps the history of every run.

    Orion ODS  -> Orion DW    (dw_sync)     orion_ods  -> orion_dw
    Tally Prime -> Tally ODS  (tally_ods)   localhost:9000 -> tally_ods
    Tally ODS  -> Tally DW    (tally_dw)    tally_ods  -> tally_dw

A run is started here, by a person (``trigger="manual"``) or by the automatic loader
(``"scheduled"``). It runs in a background thread, table by table, and writes as it goes to
``orion_ods.etl_run`` (the run) and ``orion_ods.etl_run_step`` (one row per table), so the ETL page
can show progress, and the history stays after the run. The loaders themselves (``dw_sync``,
``tally_ods``, ``tally_dw``) are unchanged: this module calls them one table at a time and records
what they report. See docs/features.md, "ETL pipelines".

Only one run of a pipeline can be going at a time, and the Tally warehouse waits for the Tally
working copy, since it reads it.
"""

from __future__ import annotations

import json
import logging
import platform
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

from app import auth
from app.config import db_settings, env
from app.database import db_cursor

logger = logging.getLogger(__name__)

FULL = "all"
TRIGGERS = ("manual", "scheduled")
ERROR_LIMIT = 1000
RECENT_RUNS = 24


class EtlError(ValueError):
    """The request cannot be run. The message is safe to show to the user."""


class EtlBusy(EtlError):
    """A run of this pipeline, or of one it waits for, is already going."""


@dataclass
class Opened:
    """What a pipeline learns when a run starts: where it reads from, and whatever its steps share."""

    source: dict[str, Any] | None = None
    fingerprint: str | None = None
    state: Any = None


@dataclass
class Pipeline:
    key: str
    label: str
    group: str
    description: str
    source_label: str
    target: str
    steps: Callable[[], list[tuple[str, str]]]
    resolve: Callable[[str], list[tuple[str, str]]]
    open: Callable[[str, str], Opened]
    run_step: Callable[[str, Opened], dict[str, Any]]
    target_table: Callable[[str], str | None]
    schedule: Callable[[], str]
    can_view: Callable[[dict], bool]
    can_run: Callable[[dict], bool]
    blocked_by: tuple[str, ...] = ()
    next_run: Callable[[], str | None] = lambda: None


# --------------------------------------------------------------------------- counting

GENERATED = "generated"


def _kind(spec: dict[str, Any], name: str) -> str:
    """The calendar is built by the loader, not read from a source, so it is not counted as rows read."""
    return GENERATED if name == "Date" else spec["kind"]



def normalise(stats: dict[str, Any] | None) -> dict[str, int]:
    """The four counts every pipeline reports, in the same words.

    A table copy reports inserted / updated / deleted / unchanged. A warehouse reports inserted /
    versioned / expired / unchanged: a changed row gets a new version (counted as updated) and a row
    removed from the source is marked expired (counted as deleted). ``rows_read`` is what the source
    had: the rows that were new, changed or the same.
    """
    raw = stats or {}

    def number(*names: str) -> int:
        for name in names:
            if raw.get(name) is not None:
                return int(raw[name])
        return 0

    inserted, updated = number("inserted"), number("updated", "versioned")
    deleted, unchanged = number("deleted", "expired"), number("unchanged")
    return {
        "rows_read": inserted + updated + unchanged,
        "rows_inserted": inserted,
        "rows_updated": updated,
        "rows_deleted": deleted,
        "rows_unchanged": unchanged,
    }


def _message(exc: BaseException) -> str:
    text = str(exc).strip() or type(exc).__name__
    if type(exc).__name__ not in ("TallyError", "EtlError") and not text.startswith(type(exc).__name__):
        text = f"{type(exc).__name__}: {text}"
    if "permission denied" in text.lower():
        text += " The database user cannot write there: apply .cursor/db/grants.sql as the postgres superuser, then run again."
    return text[:ERROR_LIMIT]


def _table_counts(table: str | None) -> tuple[int | None, int | None]:
    """(all rows, current rows) of a target table. Current rows exist only on a warehouse table."""
    if not table:
        return None, None
    try:
        with db_cursor() as cur:
            cur.execute("SAVEPOINT counting")
            try:
                cur.execute(f"SELECT COUNT(*), COUNT(*) FILTER (WHERE is_current) FROM {table}")
                total, current = cur.fetchone()
                return int(total), int(current)
            except Exception:  # not a versioned table: it has no is_current
                cur.execute("ROLLBACK TO SAVEPOINT counting")
            cur.execute(f"SELECT COUNT(*) FROM {table}")
            return int(cur.fetchone()[0]), None
    except Exception:
        logger.warning("Could not count the rows of %s", table, exc_info=True)
        return None, None


# --------------------------------------------------------------------------- the pipelines


def _orion_dw() -> Pipeline:
    from app import dw_auto, dw_sync

    def schedule() -> str:
        minutes = dw_auto.autoload_minutes()
        if minutes:
            every = "hour" if minutes == 60 else f"{minutes} minutes"
            return f"Automatic: checks every {every} and loads when the data has changed"
        return "Manual only: automatic loading is off"

    def open_run(scope: str, trigger: str) -> Opened:
        if trigger == "manual":
            dw_sync.ensure_dw_schema()
        with db_cursor() as cur:
            fingerprint = dw_sync.source_fingerprint(cur)
        return Opened(
            source={"system": "Orion ODS", "schema": "orion_ods", "database": db_settings()["database"]},
            fingerprint=fingerprint,
        )

    return Pipeline(
        key="orion_dw",
        label="Orion warehouse",
        group="Orion",
        description="Keeps a versioned history of the operational records. A changed row gets a new version; a deleted one is marked expired.",
        source_label="Orion ODS",
        target="orion_dw",
        steps=lambda: [(name, _kind(dw_sync.TABLES[name], name)) for name in dw_sync.REFRESH_ORDER],
        resolve=lambda name: [(name, _kind(dw_sync.TABLES[name], name))],
        open=open_run,
        run_step=lambda name, _opened: dw_sync.TABLES[name]["load"](),
        target_table=lambda name: dw_sync.TABLES[name].get("dw"),
        schedule=schedule,
        can_view=auth.can_access_etl,
        can_run=auth.can_write_etl,
        next_run=dw_auto.next_check_iso,
    )


def _tally_dependencies(datasets: dict[str, dict], name: str) -> list[str]:
    """``name`` and what it needs loaded first, in the order to load them."""
    order: list[str] = []

    def visit(item: str) -> None:
        for dep in datasets[item].get("depends") or []:
            visit(dep)
        if item not in order:
            order.append(item)

    visit(name)
    return order


def _tally_ods() -> Pipeline:
    from app import tally_client, tally_ods

    def open_run(_scope: str, _trigger: str) -> Opened:
        tally_ods.ensure_tally_ods_schema()
        settings = tally_client.tally_settings()
        session = tally_ods.TallySession()  # raises TallyError when Tally is down or no company is open
        return Opened(
            source={
                "system": "Tally Prime",
                "host": settings["host"],
                "port": settings["port"],
                "companies": list(session.companies),
                "from_date": tally_client.default_from_date(),
                "to_date": tally_client.default_to_date(),
            },
            state=(session, {}),
        )

    def run_step(name: str, opened: Opened) -> dict[str, Any]:
        session, loaded = opened.state
        return tally_ods._load_one(name, session, loaded)

    return Pipeline(
        key="tally_ods",
        label="Tally working copy",
        group="Tally",
        description="Reads the open company from Tally Prime over its XML server and keeps the latest copy of its masters and vouchers.",
        source_label="Tally Prime",
        target="tally_ods",
        steps=lambda: [(name, tally_ods.DATASETS[name]["kind"]) for name in tally_ods.REFRESH_ORDER],
        resolve=lambda name: [(item, tally_ods.DATASETS[item]["kind"]) for item in _tally_dependencies(tally_ods.DATASETS, name)],
        open=open_run,
        run_step=run_step,
        target_table=lambda name: tally_ods.DATASETS[name].get("table"),
        schedule=lambda: "Manual only: Tally Prime must be open on the PC that runs this",
        can_view=auth.can_access_etl,
        can_run=auth.can_write_etl,
    )


def _tally_dw() -> Pipeline:
    from app import tally_dw

    def open_run(_scope: str, _trigger: str) -> Opened:
        tally_dw.ensure_tally_dw_schema()
        return Opened(source={"system": "Tally working copy", "schema": "tally_ods"})

    return Pipeline(
        key="tally_dw",
        label="Tally warehouse",
        group="Tally",
        description="Builds the Tally warehouse from the Tally working copy, keeping a version of each row that changed.",
        source_label="Tally working copy",
        target="tally_dw",
        steps=lambda: [(name, _kind(tally_dw.TABLES[name], name)) for name in tally_dw.REFRESH_ORDER],
        resolve=lambda name: [(name, _kind(tally_dw.TABLES[name], name))],
        open=open_run,
        run_step=lambda name, _opened: tally_dw.TABLES[name]["load"](),
        target_table=lambda name: tally_dw.TABLES[name].get("dw"),
        schedule=lambda: "Manual only: run it after the Tally working copy has loaded",
        can_view=auth.can_access_etl,
        can_run=auth.can_write_etl,
        blocked_by=("tally_ods",),
    )


_pipelines: dict[str, Pipeline] | None = None


def pipelines() -> dict[str, Pipeline]:
    """Every pipeline, in the order the ETL page shows them. Built on first use."""
    global _pipelines
    if _pipelines is None:
        _pipelines = {p.key: p for p in (_orion_dw(), _tally_ods(), _tally_dw())}
    return _pipelines


def get_pipeline(key: str) -> Pipeline:
    found = pipelines().get(key)
    if not found:
        raise EtlError("That pipeline does not exist.")
    return found


# --------------------------------------------------------------------------- running

_locks: dict[str, threading.Lock] = {}
_guard = threading.Lock()


def _lock_for(key: str) -> threading.Lock:
    with _guard:
        return _locks.setdefault(key, threading.Lock())


def _running(key: str) -> bool:
    return _lock_for(key).locked()


def start_run(
    key: str,
    scope: str = FULL,
    trigger: str = "manual",
    user_id: int | None = None,
    wait: bool = False,
) -> int:
    """Start a run and return its id. It runs in a background thread unless ``wait`` is set.

    ``scope`` is ``"all"`` or the name of one table. Raises EtlError for a bad request and EtlBusy if
    this pipeline, or one it waits for, is already running.
    """
    pipeline = get_pipeline(key)
    if trigger not in TRIGGERS:
        raise EtlError("Unknown trigger.")
    steps = pipeline.steps() if scope == FULL else None
    if steps is None:
        names = [name for name, _unused in pipeline.steps()]
        if scope not in names:
            raise EtlError(f"{scope!r} is not a table of {pipeline.label}.")
        steps = pipeline.resolve(scope)
    for other in pipeline.blocked_by:
        if _running(other):
            raise EtlBusy(f"{get_pipeline(other).label} is loading. {pipeline.label} reads it, so wait for it to finish.")
    lock = _lock_for(key)
    if not lock.acquire(blocking=False):
        raise EtlBusy(f"{pipeline.label} is already running.")
    try:
        run_id = _create_run(pipeline, scope, trigger, user_id, steps)
    except Exception:
        lock.release()
        raise
    worker = threading.Thread(
        target=_execute, args=(run_id, pipeline, scope, trigger, steps, lock), name=f"orion-etl-{key}", daemon=True
    )
    worker.start()
    if wait:
        worker.join()
    return run_id


def _create_run(pipeline: Pipeline, scope: str, trigger: str, user_id: int | None, steps: list[tuple[str, str]]) -> int:
    with db_cursor(commit=True) as cur:
        cur.execute(
            """
            INSERT INTO orion_ods.etl_run (pipeline, scope, trigger, started_by, steps_total, target, runner_host, app_env)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id
            """,
            (pipeline.key, scope, trigger, user_id, len(steps), pipeline.target, platform.node(),
             env("ORION_ENV", "development")),
        )
        run_id = cur.fetchone()[0]
        for seq, (name, kind) in enumerate(steps, start=1):
            cur.execute(
                "INSERT INTO orion_ods.etl_run_step (run_id, seq, name, kind, target_table) VALUES (%s, %s, %s, %s, %s)",
                (run_id, seq, name, kind, pipeline.target_table(name)),
            )
    return run_id


def _execute(run_id: int, pipeline: Pipeline, scope: str, trigger: str, steps: list[tuple[str, str]], lock: threading.Lock) -> None:
    started = time.perf_counter()
    error: str | None = None
    try:
        try:
            opened = pipeline.open(scope, trigger)
        except Exception as exc:
            logger.exception("%s could not start", pipeline.label)
            error = _message(exc)
            opened = None
        if opened is not None:
            _record_source(run_id, opened)
            for seq, (name, _unused) in enumerate(steps, start=1):
                error = _run_step(run_id, pipeline, opened, seq, name)
                if error:
                    break
        _finish(run_id, started, error)
    except Exception as exc:  # recording the run must never leave it looking as if it is still going
        logger.exception("ETL run %s could not be recorded", run_id)
        try:
            _finish(run_id, started, error or _message(exc))
        except Exception:
            logger.exception("ETL run %s could not be closed", run_id)
    finally:
        lock.release()


def _record_source(run_id: int, opened: Opened) -> None:
    with db_cursor(commit=True) as cur:
        cur.execute(
            "UPDATE orion_ods.etl_run SET source = %s::jsonb, source_fingerprint = %s WHERE id = %s",
            (json.dumps(opened.source) if opened.source is not None else None, opened.fingerprint, run_id),
        )


def _run_step(run_id: int, pipeline: Pipeline, opened: Opened, seq: int, name: str) -> str | None:
    """Run one table. Returns the error text if it failed, else None."""
    table = pipeline.target_table(name)
    before, _ = _table_counts(table)
    with db_cursor(commit=True) as cur:
        cur.execute(
            """
            UPDATE orion_ods.etl_run_step
               SET status = 'running', started_timestamp = CURRENT_TIMESTAMP, target_rows_before = %s
             WHERE run_id = %s AND seq = %s
            """,
            (before, run_id, seq),
        )
    clock = time.perf_counter()
    try:
        stats = pipeline.run_step(name, opened) or {}
    except Exception as exc:
        logger.exception("%s: %s failed", pipeline.label, name)
        text = _message(exc)
        with db_cursor(commit=True) as cur:
            cur.execute(
                """
                UPDATE orion_ods.etl_run_step
                   SET status = 'failed', finished_timestamp = CURRENT_TIMESTAMP, duration_ms = %s, error = %s
                 WHERE run_id = %s AND seq = %s
                """,
                (round((time.perf_counter() - clock) * 1000), text, run_id, seq),
            )
        return f"{name}: {text}"
    after, current = _table_counts(table)
    counts = normalise(stats)
    detail = {**stats, **({"current_rows": current} if current is not None else {})}
    with db_cursor(commit=True) as cur:
        cur.execute(
            """
            UPDATE orion_ods.etl_run_step
               SET status = 'succeeded', finished_timestamp = CURRENT_TIMESTAMP, duration_ms = %s,
                   rows_read = %s, rows_inserted = %s, rows_updated = %s, rows_deleted = %s, rows_unchanged = %s,
                   target_rows_after = %s, stats = %s::jsonb
             WHERE run_id = %s AND seq = %s
            """,
            (
                round((time.perf_counter() - clock) * 1000), counts["rows_read"], counts["rows_inserted"],
                counts["rows_updated"], counts["rows_deleted"], counts["rows_unchanged"], after,
                json.dumps(detail, default=str), run_id, seq,
            ),
        )
    return None


def _finish(run_id: int, started: float, error: str | None) -> None:
    """Close the run: steps that never ran are skipped, and the totals are the sum of the steps."""
    with db_cursor(commit=True) as cur:
        cur.execute(
            "UPDATE orion_ods.etl_run_step SET status = 'skipped' WHERE run_id = %s AND status IN ('pending', 'running')",
            (run_id,),
        )
        cur.execute(
            """
            UPDATE orion_ods.etl_run r
               SET status = %s, finished_timestamp = CURRENT_TIMESTAMP, duration_ms = %s, error = %s,
                   steps_succeeded = s.ok, steps_failed = s.failed, steps_skipped = s.skipped,
                   rows_read = s.read, rows_inserted = s.inserted, rows_updated = s.updated,
                   rows_deleted = s.deleted, rows_unchanged = s.unchanged
              FROM (
                    SELECT COUNT(*) FILTER (WHERE status = 'succeeded') AS ok,
                           COUNT(*) FILTER (WHERE status = 'failed') AS failed,
                           COUNT(*) FILTER (WHERE status = 'skipped') AS skipped,
                           COALESCE(SUM(rows_read) FILTER (WHERE kind IS DISTINCT FROM 'generated'), 0) AS read,
                           COALESCE(SUM(rows_inserted) FILTER (WHERE kind IS DISTINCT FROM 'generated'), 0) AS inserted,
                           COALESCE(SUM(rows_updated) FILTER (WHERE kind IS DISTINCT FROM 'generated'), 0) AS updated,
                           COALESCE(SUM(rows_deleted) FILTER (WHERE kind IS DISTINCT FROM 'generated'), 0) AS deleted,
                           COALESCE(SUM(rows_unchanged) FILTER (WHERE kind IS DISTINCT FROM 'generated'), 0) AS unchanged
                      FROM orion_ods.etl_run_step WHERE run_id = %s
                   ) s
             WHERE r.id = %s
            """,
            ("failed" if error else "succeeded", round((time.perf_counter() - started) * 1000), error, run_id, run_id),
        )


def close_interrupted_runs() -> None:
    """A run still marked running when the API starts was cut off by a restart."""
    try:
        with db_cursor(commit=True) as cur:
            cur.execute(
                "UPDATE orion_ods.etl_run_step SET status = 'skipped' WHERE status IN ('pending', 'running')"
            )
            cur.execute(
                """
                UPDATE orion_ods.etl_run
                   SET status = 'failed', finished_timestamp = CURRENT_TIMESTAMP, error = 'Interrupted by a restart',
                       duration_ms = (EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - started_timestamp)) * 1000)::bigint
                 WHERE status = 'running'
                """
            )
    except Exception:
        logger.exception("Could not close interrupted ETL runs")


# --------------------------------------------------------------------------- reading

RUN_COLUMNS = """
    r.id, r.pipeline, r.scope, r.trigger, r.status, r.started_timestamp, r.finished_timestamp,
    COALESCE(r.duration_ms, (EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - r.started_timestamp)) * 1000)::bigint) AS duration_ms,
    r.steps_total, r.steps_succeeded, r.steps_failed, r.steps_skipped,
    r.rows_read, r.rows_inserted, r.rows_updated, r.rows_deleted, r.rows_unchanged,
    r.source, r.target, r.source_fingerprint, r.runner_host, r.app_env, r.error,
    r.started_by, u.display_name AS started_by_name
"""
RUN_FROM = "orion_ods.etl_run r LEFT JOIN orion_ods.app_user u ON u.id = r.started_by"


def _plain(value: Any) -> Any:
    return value.isoformat() if hasattr(value, "isoformat") else value


def _rows(cur) -> list[dict[str, Any]]:
    names = [col.name for col in cur.description]
    return [{name: _plain(value) for name, value in zip(names, row)} for row in cur.fetchall()]


def list_runs(
    keys: list[str],
    pipeline: str | None = None,
    status: str | None = None,
    trigger: str | None = None,
    limit: int = 25,
    offset: int = 0,
) -> dict[str, Any]:
    """Runs of the pipelines in ``keys``, newest first, with the total that match."""
    wanted = [key for key in keys if pipeline in (None, "", key)]
    where, params = ["r.pipeline = ANY(%s)"], [wanted]
    if status:
        where.append("r.status = %s")
        params.append(status)
    if trigger:
        where.append("r.trigger = %s")
        params.append(trigger)
    clause = " AND ".join(where)
    with db_cursor() as cur:
        cur.execute(f"SELECT COUNT(*) FROM orion_ods.etl_run r WHERE {clause}", params)
        total = cur.fetchone()[0]
        cur.execute(
            f"SELECT {RUN_COLUMNS} FROM {RUN_FROM} WHERE {clause} ORDER BY r.started_timestamp DESC, r.id DESC LIMIT %s OFFSET %s",
            [*params, max(1, min(limit, 200)), max(0, offset)],
        )
        return {"runs": _rows(cur), "total": total}


def get_run(run_id: int) -> dict[str, Any] | None:
    """One run with every step, or None."""
    with db_cursor() as cur:
        cur.execute(f"SELECT {RUN_COLUMNS} FROM {RUN_FROM} WHERE r.id = %s", (run_id,))
        found = _rows(cur)
        if not found:
            return None
        run = found[0]
        cur.execute(
            """
            SELECT seq, name, kind, target_table, status, started_timestamp, finished_timestamp,
                   COALESCE(duration_ms, CASE WHEN status = 'running'
                       THEN (EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - started_timestamp)) * 1000)::bigint END) AS duration_ms,
                   rows_read, rows_inserted, rows_updated, rows_deleted, rows_unchanged,
                   target_rows_before, target_rows_after, stats, error
              FROM orion_ods.etl_run_step WHERE run_id = %s ORDER BY seq
            """,
            (run_id,),
        )
        run["steps"] = _rows(cur)
    return run


def pipeline_overview(user: dict) -> list[dict[str, Any]]:
    """Each pipeline the user can see: what it is, how it last ran, and whether they can run it."""
    visible = [p for p in pipelines().values() if p.can_view(user)]
    if not visible:
        return []
    keys = [p.key for p in visible]
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT pipeline,
                   COUNT(*) FILTER (WHERE started_timestamp > CURRENT_TIMESTAMP - INTERVAL '30 days'),
                   COUNT(*) FILTER (WHERE status = 'succeeded' AND started_timestamp > CURRENT_TIMESTAMP - INTERVAL '30 days'),
                   AVG(duration_ms) FILTER (WHERE status = 'succeeded' AND scope = 'all'
                                              AND started_timestamp > CURRENT_TIMESTAMP - INTERVAL '30 days')
              FROM orion_ods.etl_run WHERE pipeline = ANY(%s) GROUP BY pipeline
            """,
            (keys,),
        )
        stats = {row[0]: row[1:] for row in cur.fetchall()}
        latest: dict[str, dict[str, Any]] = {}
        success: dict[str, dict[str, Any]] = {}
        recent: dict[str, list[dict[str, Any]]] = {}
        footprint: dict[str, dict[str, Any]] = {}
        for key in keys:
            cur.execute(
                """
                SELECT id, status, scope, trigger, duration_ms, started_timestamp, rows_inserted, rows_updated, rows_deleted
                  FROM orion_ods.etl_run WHERE pipeline = %s ORDER BY started_timestamp DESC, id DESC LIMIT %s
                """,
                (key, RECENT_RUNS),
            )
            recent[key] = list(reversed(_rows(cur)))
            cur.execute(
                f"SELECT {RUN_COLUMNS} FROM {RUN_FROM} WHERE r.pipeline = %s ORDER BY r.started_timestamp DESC, r.id DESC LIMIT 1",
                (key,),
            )
            row = _rows(cur)
            if row:
                latest[key] = row[0]
            cur.execute(
                f"""SELECT {RUN_COLUMNS} FROM {RUN_FROM}
                     WHERE r.pipeline = %s AND r.status = 'succeeded' AND r.scope = 'all'
                     ORDER BY r.started_timestamp DESC, r.id DESC LIMIT 1""",
                (key,),
            )
            row = _rows(cur)
            if row:
                success[key] = row[0]
                cur.execute(
                    """
                    SELECT COUNT(*) FILTER (WHERE kind IS DISTINCT FROM 'generated'),
                           COALESCE(SUM(target_rows_after) FILTER (WHERE kind IS DISTINCT FROM 'generated'), 0)
                      FROM orion_ods.etl_run_step WHERE run_id = %s AND status = 'succeeded'
                    """,
                    (row[0]["id"],),
                )
                tables, rows = cur.fetchone()
                footprint[key] = {"tables": tables, "rows": int(rows)}
    out = []
    for p in visible:
        runs_30d, ok_30d, avg_ms = stats.get(p.key, (0, 0, None))
        last = latest.get(p.key)
        out.append(
            {
                "key": p.key,
                "label": p.label,
                "group": p.group,
                "description": p.description,
                "source": p.source_label,
                "target": p.target,
                "schedule": p.schedule(),
                "steps": [{"name": name, "kind": kind} for name, kind in p.steps()],
                "can_run": bool(p.can_run(user)),
                "waits_for": [get_pipeline(other).label for other in p.blocked_by],
                "running": _running(p.key),
                "last_run": last,
                "last_full_success": success.get(p.key),
                "footprint": footprint.get(p.key),
                "recent_runs": recent.get(p.key, []),
                "next_run": p.next_run(),
                "runs_30d": runs_30d,
                "success_rate_30d": round(ok_30d / runs_30d, 3) if runs_30d else None,
                "avg_duration_ms_30d": round(float(avg_ms)) if avg_ms is not None else None,
            }
        )
    return out
