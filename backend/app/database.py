"""The application's connections to PostgreSQL.

``db_cursor()`` and ``get_connection()`` borrow a connection from a pool (``db_pool.py``) instead of opening one: opening is
about 100 ms here, and a page makes many queries. Both behave exactly as before for the code that uses them:

* ``with db_cursor(commit=True) as cur:`` commits on success and rolls back on an error; without ``commit`` nothing is saved;
* ``conn = get_connection()`` ... ``conn.commit()`` / ``conn.rollback()`` ... ``conn.close()``: ``close()`` gives the connection
  back (and anything left open is rolled back), which is what the billing and warehouse code, which hold a connection across
  several steps, already did.

Use ``raw_connection()`` only for something that must not be shared with the pool.
``ORION_DB_POOL_MAX`` (20) and ``ORION_DB_POOL_TIMEOUT`` (15 seconds) tune it. Dev and prod each have a pool, in one PostgreSQL
that allows 100 connections, so keep the maximum well under 50.
"""

import atexit
import logging
import os
import threading
from contextlib import contextmanager
from typing import Optional

import psycopg2

from app.config import db_settings
from app.db_pool import ConnectionPool, PoolTimeout  # noqa: F401 - PoolTimeout is re-exported for the API's 503 handler

logger = logging.getLogger(__name__)

DEFAULT_POOL_MAX = 20
HARD_POOL_MAX = 100  # PostgreSQL's own default limit: a pool above it could only ever fail
DEFAULT_TIMEOUT = 15.0

_pool: Optional[ConnectionPool] = None
_pool_pid: Optional[int] = None
_pool_lock = threading.Lock()
_orphans: list = []  # see pool()


def pool_size(environ=None) -> int:
    raw = (environ if environ is not None else os.environ).get("ORION_DB_POOL_MAX", "")
    try:
        return min(HARD_POOL_MAX, max(1, int(raw)))
    except ValueError:
        return DEFAULT_POOL_MAX


def pool_timeout(environ=None) -> float:
    raw = (environ if environ is not None else os.environ).get("ORION_DB_POOL_TIMEOUT", "")
    try:
        return max(1.0, float(raw))
    except ValueError:
        return DEFAULT_TIMEOUT


def raw_connection():
    """A new connection that is not part of the pool: the caller owns it and must close it."""
    return psycopg2.connect(**db_settings())


def pool() -> ConnectionPool:
    """The pool, made on first use (so importing this module, or a parent process that never queries, opens nothing)."""
    global _pool, _pool_pid
    with _pool_lock:
        if _pool is None or _pool_pid != os.getpid():
            if _pool is not None:
                # A forked child must not close its parent's connections: they share the sockets, and closing one tells the
                # server to end the parent's session. Keep a reference so they are never garbage collected here.
                _orphans.append(_pool)
            _pool = ConnectionPool(raw_connection, max_size=pool_size(), checkout_timeout=pool_timeout())
            _pool_pid = os.getpid()
        return _pool


def get_connection():
    """Borrow a connection. Call ``close()`` on it when done: that gives it back."""
    return pool().acquire()


@contextmanager
def db_cursor(commit=False):
    conn = get_connection()
    try:
        cur = conn.cursor()
        try:
            yield cur
            if commit:
                conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:  # noqa: BLE001 - the original error is the one worth raising; the pool drops a connection it cannot reset
                logger.warning("A rollback failed; the connection will not be reused")
            raise
        finally:
            cur.close()
    finally:
        conn.close()


def pool_stats() -> Optional[dict]:
    """Counters for the System page, or None when nothing has used the database yet."""
    return _pool.stats() if _pool is not None and _pool_pid == os.getpid() else None


def warm_pool(count: int = 2) -> None:
    """Open a couple of connections at start-up so the first requests do not pay for them. Never fails the start."""
    try:
        opened = pool().warm(count)
        logger.info("Database pool ready: %d connections open, at most %d", opened, pool_size())
    except Exception:
        logger.warning("Could not open database connections at start-up; they will be opened when needed", exc_info=True)


def close_pool() -> None:
    global _pool
    with _pool_lock:
        if _pool is not None and _pool_pid == os.getpid():
            _pool.close()
        _pool = None


atexit.register(close_pool)
