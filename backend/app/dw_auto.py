"""Loads the Orion warehouse by itself, so its history follows the ODS without anyone pressing Refresh.

A background thread wakes every ``ORION_DW_AUTOLOAD_MINUTES`` (default 60; 0 turns it off). If the
ODS looks different from when the last successful full load started (see
``dw_sync.source_fingerprint``) it runs a full load, and otherwise does nothing. Anything that
changes within one interval is seen as its final state, so an edit that is made and then changed
again before the next load leaves one version, not two. A person can still run the pipeline at once from
the ETL page. Loads go through ``etl.start_run``, which records them.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta, timezone

from app.config import env
from app.database import db_cursor
from app import dw_sync, etl

logger = logging.getLogger(__name__)

DEFAULT_MINUTES = 60
FIRST_CHECK_DELAY_SECONDS = 120

_next_check: datetime | None = None


def next_check_iso() -> str | None:
    """When the loader will next look, or None when it is off. Only known in the process that runs it."""
    return _next_check.isoformat() if _next_check else None


def _wait(stop: threading.Event, seconds: float) -> bool:
    """Sleep until the next check (or until told to stop, which returns True) and remember when that is."""
    global _next_check
    _next_check = datetime.now(timezone.utc) + timedelta(seconds=seconds)
    try:
        return stop.wait(seconds)
    finally:
        _next_check = None


def autoload_minutes() -> int:
    raw = env("ORION_DW_AUTOLOAD_MINUTES", str(DEFAULT_MINUTES)).strip()
    try:
        return max(int(raw), 0)
    except ValueError:
        logger.warning("ORION_DW_AUTOLOAD_MINUTES=%r is not a whole number; using %s", raw, DEFAULT_MINUTES)
        return DEFAULT_MINUTES


def load_if_changed() -> str:
    """One check. Returns "unchanged", "loaded", "busy" or "failed"."""
    try:
        with db_cursor() as cur:
            fingerprint = dw_sync.source_fingerprint(cur)
            cur.execute(
                """
                SELECT source_fingerprint FROM orion_ods.etl_run
                 WHERE pipeline = 'orion_dw' AND scope = %s AND status = 'succeeded'
                 ORDER BY finished_timestamp DESC, id DESC LIMIT 1
                """,
                (etl.FULL,),
            )
            last = cur.fetchone()
        if last and last[0] == fingerprint:
            return "unchanged"
        run_id = etl.start_run("orion_dw", trigger="scheduled", wait=True)
        run = etl.get_run(run_id)
        if run and run["status"] == "succeeded":
            logger.info("Warehouse loaded automatically (run %s)", run_id)
            return "loaded"
        logger.error("Automatic warehouse load failed (run %s): %s", run_id, run and run["error"])
        return "failed"
    except etl.EtlBusy:
        return "busy"
    except Exception:
        logger.exception("Automatic warehouse load failed")
        return "failed"


def start(stop: threading.Event) -> threading.Thread | None:
    """Start the loader. ``stop`` ends it; the thread never blocks shutdown."""
    minutes = autoload_minutes()
    if minutes == 0:
        logger.info("Automatic warehouse loading is off (ORION_DW_AUTOLOAD_MINUTES=0)")
        return None
    def loop() -> None:
        if _wait(stop, FIRST_CHECK_DELAY_SECONDS):
            return
        while True:
            load_if_changed()
            if _wait(stop, minutes * 60):
                return

    thread = threading.Thread(target=loop, name="orion-dw-autoload", daemon=True)
    thread.start()
    logger.info("Automatic warehouse loading every %s minutes", minutes)
    return thread
