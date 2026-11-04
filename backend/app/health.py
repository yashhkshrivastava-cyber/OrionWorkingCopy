"""Is the server well? Three answers, from the cheapest to the most detailed.

* ``/api/health``: the process is up. Unchanged: the desktop launchers poll it and the docs say it returns {"status":"ok"}.
* ``/api/health/ready``: the process can reach its database. Public (it says only up or down), and answered from a result at
  most a few seconds old so that polling it cannot make the database work.
* ``/api/health/details``: for administrators, the System page. The database's speed, when each warehouse load and the backup
  last worked, request counters, the slowest recent requests and the last warnings and errors, plus a plain list of what needs
  attention. It reads what the jobs already wrote to their tables (``etl_run``, ``backup_run``); no job reports to it.
"""

import logging
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from app import backup, database, dw_auto, migrate, observability, tenders
from app.database import db_cursor

logger = logging.getLogger(__name__)

READY_CACHE_SECONDS = 5
ERRORS_WINDOW = timedelta(hours=1)

_ready_lock = threading.Lock()
_ready_cache: dict[str, Any] = {"at": 0.0, "ok": True, "ms": None, "schema": None}


def check_database() -> dict:
    """One real round trip: {'ok': bool, 'ms': int | None, 'error': str | None}."""
    started = time.perf_counter()
    try:
        with db_cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
    except Exception as exc:  # noqa: BLE001
        logger.error("The database did not answer the health check: %s", type(exc).__name__)
        return {"ok": False, "ms": None, "error": type(exc).__name__}
    return {"ok": True, "ms": int((time.perf_counter() - started) * 1000), "error": None}


def schema_problems() -> Optional[list[str]]:
    """What is wrong with the schema (a step that failed, a file never applied or edited since), or None when it cannot be read."""
    try:
        return migrate.problems()
    except Exception:  # noqa: BLE001 - not being able to look is not the same as something being wrong
        logger.debug("Could not read the schema record", exc_info=True)
        return None


def ready() -> tuple[bool, dict]:
    """(can serve, body). Cached for a few seconds. Not ready when the database is down or the schema is not what the code expects:
    the body then says which, and a deploy's smoke test refuses it. The body of a healthy answer is unchanged."""
    now = time.monotonic()
    with _ready_lock:
        if now - _ready_cache["at"] > READY_CACHE_SECONDS:
            result = check_database()
            problems = schema_problems() if result["ok"] else None
            _ready_cache.update(at=now, ok=result["ok"], ms=result["ms"], schema=problems)
        ok, problems = _ready_cache["ok"], _ready_cache["schema"]
    if not ok:
        return False, {"status": "degraded", "database": "down"}
    if problems:
        return False, {"status": "degraded", "database": "ok", "schema": "problem"}
    return True, {"status": "ok", "database": "ok"}


def _iso(value) -> Optional[str]:
    return value.astimezone(timezone.utc).isoformat() if isinstance(value, datetime) else None


def pipelines() -> list[dict]:
    """For each warehouse pipeline: its last good load, its last failure, and whether one is running now."""
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT pipeline,
                   MAX(finished_timestamp) FILTER (WHERE status = 'succeeded'),
                   MAX(finished_timestamp) FILTER (WHERE status = 'failed'),
                   COUNT(*) FILTER (WHERE status = 'running')
              FROM orion_ods.etl_run GROUP BY pipeline ORDER BY pipeline
            """
        )
        rows = cur.fetchall()
        cur.execute(
            """
            SELECT DISTINCT ON (pipeline) pipeline, error
              FROM orion_ods.etl_run WHERE status = 'failed' ORDER BY pipeline, finished_timestamp DESC NULLS LAST, id DESC
            """
        )
        errors = {pipeline: error for pipeline, error in cur.fetchall()}
    return [
        {
            "pipeline": pipeline,
            "last_success": _iso(good),
            "last_failure": _iso(bad),
            "last_error": (errors.get(pipeline) or "")[:200] or None,
            "running": int(running or 0) > 0,
            "failing": bool(bad and (not good or bad > good)),
        }
        for pipeline, good, bad, running in rows
    ]


def _ago(iso: Optional[str], now: datetime) -> str:
    if not iso:
        return "never"
    seconds = int((now - datetime.fromisoformat(iso)).total_seconds())
    if seconds < 90:
        return "just now"
    if seconds < 5400:
        return f"{round(seconds / 60)} minutes ago"
    if seconds < 172800:
        return f"{round(seconds / 3600)} hours ago"
    return f"{round(seconds / 86400)} days ago"


def attention(
    database: dict, backups: Optional[dict], loads: list[dict], problems: list[dict], now: datetime, schema: Optional[list[str]] = None,
    tender_checks: Optional[dict] = None,
) -> list[str]:
    """What an administrator should look at, in plain words. Empty means nothing needs doing."""
    found: list[str] = []
    if not database["ok"]:
        found.append("The database did not answer.")
    for issue in schema or []:
        found.append(f"Database schema: {issue}. Run python -m app.migrate to see and retry it.")
    pool = database.get("pool") or {}
    if pool.get("timeouts"):
        found.append(
            f"{pool['timeouts']} request{'s' if pool['timeouts'] != 1 else ''} gave up waiting for a database connection since the server "
            f"started (all {pool['max']} were busy). Raise ORION_DB_POOL_MAX, or find what is holding them."
        )
    if backups:
        if backups.get("state") == "blocked":
            found.append("Backups are on but cannot run: " + " ".join(backups.get("problems") or []))
        elif backups.get("stale"):
            last = (backups.get("last_success") or {}).get("finished_timestamp")
            found.append(f"The last good backup was {_ago(last, now)}; one is overdue.")
    for load in loads:
        if load["failing"]:
            found.append(f"The {load['pipeline']} load failed {_ago(load['last_failure'], now)}" + (f": {load['last_error']}" if load["last_error"] else "."))
    for portal, check in (tender_checks or {}).items():
        if check and check.get("failing"):
            last = check.get("last_run") or {}
            name = tenders.PORTAL_NAMES.get(portal, portal)
            found.append(f"The {name} tender check failed {_ago(last.get('finished_timestamp'), now)}" + (f": {last['error']}" if last.get("error") else "."))
    cutoff = (now - ERRORS_WINDOW).isoformat()
    recent_errors = [p for p in problems if p["level"] in ("ERROR", "CRITICAL") and p["time"] >= cutoff]
    if recent_errors:
        found.append(f"{len(recent_errors)} error{'s' if len(recent_errors) != 1 else ''} in the log in the last hour; the newest is under Recent problems.")
    return found


def details(now: Optional[datetime] = None) -> dict:
    now = now or datetime.now(timezone.utc)
    database_state = check_database()
    database_state["pool"] = database.pool_stats()
    loads: list[dict] = []
    backups: Optional[dict] = None
    tender_checks: Optional[dict] = None
    if database_state["ok"]:
        try:
            loads = pipelines()
        except Exception:  # noqa: BLE001
            logger.exception("Could not read the load history for the System page")
        try:
            backups = backup.status()
        except Exception:  # noqa: BLE001
            logger.exception("Could not read the backup status for the System page")
        try:
            tender_checks = tenders.status_all()
        except Exception:  # noqa: BLE001
            logger.exception("Could not read the tender check status for the System page")
    problems = observability.recent_problems(50)
    schema = {"steps": 0, "applied": 0, "last_applied": None, "problems": []}
    if database_state["ok"]:
        try:
            rows = migrate.status_rows()
            schema = {
                "steps": len(rows),
                "applied": sum(1 for row in rows if row["status"] == "applied"),
                "last_applied": _iso(max((row["applied_timestamp"] for row in rows if row["applied_timestamp"]), default=None)),
                "problems": migrate.problems(),
            }
        except Exception:  # noqa: BLE001
            logger.exception("Could not read the schema record for the System page")
    notes = attention(database_state, backups, loads, problems, now, schema["problems"], tender_checks)
    minutes = dw_auto.autoload_minutes()
    return {
        "status": "attention" if notes else "ok",
        "attention": notes,
        "environment": (os.environ.get("ORION_ENV") or "development").strip().lower() or "development",
        "checked": now.isoformat(),
        "database": database_state,
        "loads": loads,
        "schema": schema,
        "autoload": {"minutes": minutes, "next_check": dw_auto.next_check_iso()},
        "backup": None
        if backups is None
        else {k: backups.get(k) for k in ("state", "problems", "running", "last_success", "next_run", "stale", "interval_hours")},
        "tenders": tender_checks,
        "requests": observability.STATS.snapshot(),
        "problems": problems[:30],
        "log": {
            "level": logging.getLevelName(logging.getLogger().level),
            "file": str(observability.log_dir() / observability.LOG_FILE_NAME) if observability.log_file_enabled() else None,
        },
    }
