"""Applying the database's schema, and remembering that it was applied.

Before this, the schema was a list of SQL files re-run on every start. Nothing recorded what had run, a file that failed only
logged "Could not apply" while the API started anyway, and a deploy never looked. A half-applied schema change then showed up as a
feature failing, not as a failed deploy.

Now every schema step is a row of ``orion_ods.schema_migrations``: the checksum of the file as it was last applied, whether that
worked, when and how long, and the error if not. The rules:

* **A file is applied when it is new or its text changed, and skipped when it has not.** (Editing an existing file to add a column
  is allowed and re-applies it: every statement is written to be safe to re-run.) ``python -m app.migrate --force`` re-applies all.
* **A failure is recorded and fails the run.** ``python -m app.migrate`` exits 1, and ``deploy.ps1`` runs it BEFORE it stops the
  running server, so a bad migration stops the deploy with production untouched. At startup, production refuses to start; a
  development machine logs it and carries on, and ``/api/health/ready`` and the System page say the schema is not right.
* **The order is the order of ``entities.SQL_MIGRATIONS``**, then the three warehouse schemas (which also manage their own
  privileges and run every time). A file that is on disk but not in that list is caught by a test.
* A step runs as the application's database role; if that is refused for ownership, as the database owner when
  ``ORION_POSTGRES_SUPER_PASSWORD`` is set. With neither it fails, loudly, instead of being skipped.

``--status`` prints what is recorded.
"""

import hashlib
import logging
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from app.config import ROOT
from app.database import db_cursor

logger = logging.getLogger(__name__)

SQL_DIR = ROOT / ".cursor" / "db"
TRACKING_FILE = SQL_DIR / "migrate_schema_migrations.sql"
TABLE = "orion_ods.schema_migrations"
ERROR_LIMIT = 800


class MigrationFailed(RuntimeError):
    """One or more schema steps failed. The message lists them."""


@dataclass
class Result:
    name: str
    status: str  # applied | unchanged | failed
    seconds: float = 0.0
    error: Optional[str] = None


def checksum(text: str) -> str:
    """Hash of the text with line endings normalised: the same file is the same on Windows, macOS and in Git."""
    return hashlib.sha256(text.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")).hexdigest()


# ------------------------------------------------------------------------------------------------------ running a step


def _owner_refused(exc: Exception) -> bool:
    text = str(exc).lower()
    return "permission denied" in text or "must be owner" in text


def apply_sql(sql: str) -> None:
    """Run one file as the application's role; if the database refuses on ownership, as the database owner. Raises on failure."""
    from app.dw_sync import _run_sql, _superuser_settings

    try:
        with db_cursor(commit=True) as cur:
            cur.execute(sql)
        return
    except Exception as exc:
        if not _owner_refused(exc):
            raise
        first = exc
    settings = _superuser_settings()
    if not settings:
        raise RuntimeError(f"{str(first).strip().splitlines()[0]} (the database owner is needed: set ORION_POSTGRES_SUPER_PASSWORD)") from first
    _run_sql(sql, settings)


def _short(exc: Exception) -> str:
    return (str(exc).strip() or type(exc).__name__)[:ERROR_LIMIT]


# --------------------------------------------------------------------------------------------------------- the record


def _recorded() -> dict[str, tuple[str, str]]:
    with db_cursor() as cur:
        cur.execute(f"SELECT name, checksum, status FROM {TABLE}")
        return {name: (digest, status) for name, digest, status in cur.fetchall()}


def _record(name: str, digest: str, ok: bool, started: float, error: Optional[str]) -> None:
    ms = int((time.perf_counter() - started) * 1000)
    with db_cursor(commit=True) as cur:
        cur.execute(
            f"""
            INSERT INTO {TABLE} (name, checksum, status, applied_timestamp, last_attempt_timestamp, duration_ms, attempts, error)
            VALUES (%s, %s, %s, CASE WHEN %s THEN CURRENT_TIMESTAMP END, CURRENT_TIMESTAMP, %s, 1, %s)
            ON CONFLICT (name) DO UPDATE SET
                checksum = EXCLUDED.checksum,
                status = EXCLUDED.status,
                applied_timestamp = CASE WHEN EXCLUDED.status = 'applied' THEN CURRENT_TIMESTAMP ELSE {TABLE}.applied_timestamp END,
                last_attempt_timestamp = CURRENT_TIMESTAMP,
                duration_ms = EXCLUDED.duration_ms,
                attempts = CASE WHEN {TABLE}.checksum = EXCLUDED.checksum AND {TABLE}.status = 'failed' THEN {TABLE}.attempts + 1 ELSE 1 END,
                error = EXCLUDED.error
            """,
            (name, digest, "applied" if ok else "failed", ok, ms, error),
        )


# ------------------------------------------------------------------------------------------------------------ the run


def sql_steps() -> list[Path]:
    from app import entities

    return list(entities.SQL_MIGRATIONS)


def warehouse_steps() -> list[tuple[str, Path, Callable[[], None]]]:
    """The three warehouse schemas: they also set up their own privileges, so they run every time."""
    from app import dw_sync, tally_dw, tally_ods

    return [
        ("dw_schema.sql", dw_sync.SCHEMA_FILE, dw_sync.ensure_dw_schema),
        ("tally_ods_schema.sql", tally_ods.SCHEMA_FILE, tally_ods.ensure_tally_ods_schema),
        ("tally_dw_schema.sql", tally_dw.SCHEMA_FILE, tally_dw.ensure_tally_dw_schema),
    ]


def run(force: bool = False, warehouse: bool = True) -> list[Result]:
    """Apply every schema step that needs it, record each result, and return them all (a failure does not stop the others)."""
    results: list[Result] = []
    tracking_text = TRACKING_FILE.read_text(encoding="utf-8")
    try:
        apply_sql(tracking_text)  # always: it is what makes the rest trackable
    except Exception as exc:
        logger.error("Could not create the schema_migrations table: %s", _short(exc))
        return [Result(TRACKING_FILE.name, "failed", error=_short(exc))]
    known = _recorded()
    for path in sql_steps():
        text = path.read_text(encoding="utf-8")
        digest = checksum(text)
        before = known.get(path.name)
        if not force and before == (digest, "applied"):
            results.append(Result(path.name, "unchanged"))
            continue
        started = time.perf_counter()
        try:
            apply_sql(text)
        except Exception as exc:
            logger.error("Could not apply %s: %s", path.name, _short(exc))
            _record(path.name, digest, False, started, _short(exc))
            results.append(Result(path.name, "failed", time.perf_counter() - started, _short(exc)))
        else:
            _record(path.name, digest, True, started, None)
            results.append(Result(path.name, "applied", time.perf_counter() - started))
            logger.info("Applied %s", path.name)
    for name, path, apply in warehouse_steps() if warehouse else []:
        started = time.perf_counter()
        digest = checksum(path.read_text(encoding="utf-8"))
        try:
            apply()
        except Exception as exc:
            logger.error("Could not apply %s: %s", name, _short(exc))
            _record(name, digest, False, started, _short(exc))
            results.append(Result(name, "failed", time.perf_counter() - started, _short(exc)))
        else:
            _record(name, digest, True, started, None)
            results.append(Result(name, "applied", time.perf_counter() - started))
    return results


def failures(results: list[Result]) -> list[Result]:
    return [item for item in results if item.status == "failed"]


def describe(results: list[Result]) -> str:
    return "\n".join(f"  - {item.name}: {item.error}" for item in failures(results))


def apply_at_startup(production: bool) -> list[Result]:
    """Called when the API starts. In production a failed step refuses the start; elsewhere it is logged and the API carries on."""
    results = run()
    bad = failures(results)
    if bad and production:
        raise MigrationFailed("Orion will not start: the database schema could not be brought up to date.\n" + describe(results))
    return results


# ------------------------------------------------------------------------------------------------------- what is recorded


def status_rows() -> list[dict]:
    with db_cursor() as cur:
        cur.execute(
            f"""SELECT name, status, checksum, applied_timestamp, last_attempt_timestamp, duration_ms, attempts, error
                  FROM {TABLE} ORDER BY name"""
        )
        names = [col.name for col in cur.description]
        return [dict(zip(names, row)) for row in cur.fetchall()]


def problems() -> list[str]:
    """What is wrong with the schema right now, in words: a step that failed, or a file edited or added since it was applied."""
    recorded = {row["name"]: row for row in status_rows()}
    # Only steps THIS code knows about count. After a rolled-back deploy the table still holds the failed step of the version that
    # was rolled back; the old code does not know that file and must not be called unhealthy because of it.
    known = {path.name for path in sql_steps()} | {name for name, _path, _apply in warehouse_steps()}
    found: list[str] = []
    for name, row in recorded.items():
        if row["status"] == "failed" and name in known:
            found.append(f"{name} failed: {(row['error'] or '').splitlines()[0] if row['error'] else 'no detail'}")
    for path in sql_steps():
        row = recorded.get(path.name)
        if row is None:
            found.append(f"{path.name} has not been applied")
        elif row["status"] == "applied" and row["checksum"] != checksum(path.read_text(encoding="utf-8")):
            found.append(f"{path.name} has changed since it was applied")
    return found


# ---------------------------------------------------------------------------------------------------------- command line


def main(argv: Optional[list[str]] = None) -> int:
    """``python -m app.migrate`` (from backend/): apply what is needed, exit 1 on any failure. ``--status`` prints what is recorded,
    ``--force`` re-applies every file."""
    args = list(sys.argv[1:] if argv is None else argv)
    if "--status" in args:
        try:
            rows = status_rows()
        except Exception as exc:
            print(f"Could not read the schema record: {_short(exc)}")
            return 1
        for row in rows:
            when = row["applied_timestamp"].strftime("%Y-%m-%d %H:%M") if row["applied_timestamp"] else "never"
            print(f"{row['status']:8s} {row['name']:46s} last applied {when}" + (f"  ERROR: {row['error']}" if row["error"] else ""))
        issues = problems()
        for issue in issues:
            print("PROBLEM:", issue)
        print(f"{len(rows)} steps recorded; {len(issues)} problem(s).")
        return 1 if issues else 0
    results = run(force="--force" in args)
    for item in results:
        mark = {"applied": "applied  ", "unchanged": "unchanged", "failed": "FAILED   "}[item.status]
        print(f"{mark} {item.name}" + (f"  ({item.seconds:.1f}s)" if item.status == "applied" else "") + (f"\n          {item.error}" if item.error else ""))
    bad = failures(results)
    if bad:
        print(f"\n{len(bad)} schema step(s) failed. Nothing was stopped; fix them and run this again.")
        return 1
    print(f"\nSchema is up to date ({sum(1 for r in results if r.status == 'applied')} applied, {sum(1 for r in results if r.status == 'unchanged')} unchanged).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
