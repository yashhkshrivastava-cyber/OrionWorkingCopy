"""A pool of database connections, so a request does not pay to open one.

Every query used to open a brand-new PostgreSQL connection (TCP, password check, session set-up) and close it again. On this PC
that is about 100 ms, so a page that makes ten queries spent a second just connecting, and eight people at once made each other
four times slower. This keeps connections open and lends them out.

The rules, which are the whole point of the class:

* **A connection is clean when it is lent.** Whatever the last borrower left (an open transaction, an error state, autocommit)
  is rolled back before the next one gets it, so nobody ever sees another request's half-finished work or its row locks.
  (Nothing in Orion sets session state, so a rollback is the whole reset: see ``tests/test_db_pool.py``.)
* **A connection that may be dead is not lent.** It is thrown away, and replaced, if it is closed, past ``max_age`` (a leak or a
  server-side limit cannot build up over weeks) or has sat idle ``ping_after`` seconds and no longer answers ``SELECT 1`` (the
  database was restarted).
* **The pool never hands out more than ``max_size``.** When all are in use a caller waits, up to ``checkout_timeout`` seconds, and
  then gets ``PoolTimeout``: a busy server says so instead of opening a hundred connections and taking the database down.
* **Idle connections are not kept for ever**: beyond ``keep_warm`` they close after ``idle_ttl`` seconds.
* **A borrower that forgets to give a connection back does not leak it**: the wrapper returns it when it is garbage collected,
  and logs that it had to.

It knows nothing about psycopg2: it is given a ``connect`` function, and uses only ``cursor``, ``rollback``, ``close``,
``closed``, ``autocommit`` and ``get_transaction_status`` of what that returns, so it is tested with fake connections.
"""

import collections
import logging
import threading
import time
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

# psycopg2's connection.get_transaction_status() values.
IDLE, UNKNOWN = 0, 4


class PoolError(RuntimeError):
    """A connection was used after it was given back."""


class PoolTimeout(RuntimeError):
    """Every connection was in use for the whole of ``checkout_timeout``."""


class _Slot:
    __slots__ = ("conn", "created", "last_used")

    def __init__(self, conn: Any, now: float):
        self.conn, self.created, self.last_used = conn, now, now


class PooledConnection:
    """What a borrower holds. Looks like a psycopg2 connection to the code that uses it, except that ``close()`` gives it back."""

    def __init__(self, slot: _Slot, pool: "ConnectionPool"):
        self._slot: Optional[_Slot] = slot
        self._pool = pool

    def _live(self):
        if self._slot is None:
            raise PoolError("This connection was already given back to the pool; it cannot be used again.")
        return self._slot.conn

    def cursor(self, *args, **kwargs):
        return self._live().cursor(*args, **kwargs)

    def commit(self):
        return self._live().commit()

    def rollback(self):
        return self._live().rollback()

    @property
    def closed(self):
        return self._slot is None or self._slot.conn.closed

    def close(self):
        """Give it back (the pool rolls back anything left open). Safe to call twice."""
        slot, self._slot = self._slot, None
        if slot is not None:
            self._pool.release(slot)

    def __getattr__(self, name):  # anything else a caller asks of a psycopg2 connection
        if name.startswith("__") or name in ("_slot", "_pool"):  # (the last two: never recurse if __init__ did not finish)
            raise AttributeError(name)
        return getattr(self._live(), name)

    def __enter__(self):  # psycopg2's own meaning: commit on success, roll back on error, and do NOT close
        self._live()
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            self.commit()
        else:
            self.rollback()
        return False

    def __del__(self):
        slot = getattr(self, "_slot", None)
        if slot is not None:
            logger.warning("A database connection was dropped without being closed; returning it to the pool")
            self._slot = None
            try:
                self._pool.release(slot)
            except Exception:  # noqa: BLE001, S110 - never raise from a finaliser
                pass


class ConnectionPool:
    def __init__(
        self,
        connect: Callable[[], Any],
        *,
        max_size: int = 20,
        checkout_timeout: float = 15.0,
        max_age: float = 1800.0,
        idle_ttl: float = 300.0,
        ping_after: float = 30.0,
        keep_warm: int = 2,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._connect = connect
        self.max_size, self.checkout_timeout = max(1, max_size), checkout_timeout
        self.max_age, self.idle_ttl, self.ping_after, self.keep_warm = max_age, idle_ttl, ping_after, keep_warm
        self._clock = clock
        self._cond = threading.Condition()
        self._idle: collections.deque[_Slot] = collections.deque()  # the most recently used is on the right
        self._total = 0  # open, or being opened
        self._in_use = 0
        self._closed = False
        self.waits = 0
        self.wait_seconds = 0.0
        self.timeouts = 0
        self.opened = 0
        self.discarded = 0

    # ------------------------------------------------------------------------------------------------------ borrowing

    def acquire(self) -> PooledConnection:
        started = self._clock()
        deadline = started + self.checkout_timeout
        waited = False
        while True:
            reaped: list[_Slot] = []
            try:  # the finally closes what was reaped on EVERY way out of an iteration, including waiting and trying again
                with self._cond:
                    if self._closed:
                        raise PoolError("The connection pool is closed.")
                    self._reap(reaped)
                    slot = self._idle.pop() if self._idle else None  # the warmest one
                    create = False
                    if slot is None:
                        if self._total < self.max_size:
                            self._total += 1
                            create = True
                        else:
                            remaining = deadline - self._clock()
                            if remaining <= 0:
                                self.timeouts += 1
                                raise PoolTimeout(
                                    f"All {self.max_size} database connections were busy for {self.checkout_timeout:.0f} seconds."
                                )
                            waited = True
                            self._cond.wait(remaining)
                            continue
                    self._in_use += 1
                try:
                    if create:
                        slot = _Slot(self._connect(), self._clock())
                        with self._cond:
                            self.opened += 1
                    elif not self._fit(slot):
                        self._forget(slot)
                        continue
                except BaseException:
                    with self._cond:
                        self._total -= 1
                        self._in_use -= 1
                        self._cond.notify()
                    raise
                if waited:
                    took = self._clock() - started
                    with self._cond:
                        self.waits += 1
                        self.wait_seconds += took
                    if took >= 1.0:
                        logger.warning("Waited %.1f s for a database connection (all %d in use)", took, self.max_size)
                return PooledConnection(slot, self)
            finally:
                for old in reaped:  # outside the lock: closing can be slow
                    self._close(old.conn)

    def release(self, slot: _Slot) -> None:
        keep = self._reset(slot.conn)
        now = self._clock()
        with self._cond:
            self._in_use -= 1
            if keep and not self._closed and now - slot.created <= self.max_age:
                slot.last_used = now
                self._idle.append(slot)
            else:
                self._total -= 1
                self.discarded += 1
                keep = False
            self._cond.notify()
        if not keep:
            self._close(slot.conn)

    # ------------------------------------------------------------------------------------------------------ housekeeping

    def _reset(self, conn: Any) -> bool:
        """Make a returned connection clean. False means it is not worth keeping."""
        try:
            if conn.closed:
                return False
            if conn.get_transaction_status() == UNKNOWN:
                return False
            if conn.get_transaction_status() != IDLE:
                conn.rollback()  # an unfinished transaction, or one in the error state, and its row locks
            if getattr(conn, "autocommit", False):
                conn.autocommit = False
            return True
        except Exception:  # noqa: BLE001
            return False

    def _fit(self, slot: _Slot) -> bool:
        """Whether an idle connection can be lent now: open, not too old, and still answering if it has been quiet."""
        now = self._clock()
        try:
            if slot.conn.closed or now - slot.created > self.max_age:
                return False
            if now - slot.last_used > self.ping_after:
                cur = slot.conn.cursor()
                try:
                    cur.execute("SELECT 1")
                    cur.fetchone()
                finally:
                    cur.close()
                slot.conn.rollback()
            return True
        except Exception:  # noqa: BLE001 - the server went away, or closed it for being idle
            return False

    def _forget(self, slot: _Slot) -> None:
        with self._cond:
            self._total -= 1
            self._in_use -= 1
            self.discarded += 1
            self._cond.notify()
        self._close(slot.conn)

    def _reap(self, into: list) -> None:
        """Called with the lock held: take the longest-idle connections beyond the warm few that have been idle too long."""
        now = self._clock()
        while len(self._idle) > self.keep_warm and now - self._idle[0].last_used > self.idle_ttl:
            into.append(self._idle.popleft())
            self._total -= 1
            self.discarded += 1

    @staticmethod
    def _close(conn: Any) -> None:
        try:
            conn.close()
        except Exception:  # noqa: BLE001, S110 - a connection that will not close is already gone
            pass

    # ------------------------------------------------------------------------------------------------------ the rest

    def warm(self, count: int) -> int:
        """Open up to ``count`` connections now, so the first requests after a start do not pay for them. Returns how many."""
        held = []
        try:
            for _ in range(min(count, self.max_size)):
                held.append(self.acquire())
        finally:
            for item in held:
                item.close()
        return len(held)

    def stats(self) -> dict:
        with self._cond:
            return {
                "max": self.max_size,
                "open": self._total,
                "in_use": self._in_use,
                "idle": len(self._idle),
                "waits": self.waits,
                "wait_seconds": round(self.wait_seconds, 2),
                "timeouts": self.timeouts,
                "opened": self.opened,
                "discarded": self.discarded,
            }

    def close(self) -> None:
        with self._cond:
            self._closed = True
            idle, self._idle = list(self._idle), collections.deque()
            self._total -= len(idle)
            self._cond.notify_all()
        for slot in idle:
            self._close(slot.conn)
