"""The connection pool: what it promises, tested with fake connections (no database needed).

The half that uses the real database runs only with ORION_DB_TESTS=1 (it makes and removes rows in orion_ods.auth_attempt):

    $env:ORION_DB_TESTS = "1"; python -m pytest backend/tests/test_db_pool.py
"""

import gc
import os
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app import database  # noqa: E402
from app.db_pool import IDLE, UNKNOWN, ConnectionPool, PoolError, PoolTimeout, PooledConnection  # noqa: E402

INTRANS, INERROR = 2, 3
RUN = os.environ.get("ORION_DB_TESTS") == "1"


class FakeCursor:
    def __init__(self, conn):
        self.conn, self.closed = conn, False

    def execute(self, sql, *args):
        if not self.conn.alive:
            raise RuntimeError("server closed the connection unexpectedly")
        self.conn.queries.append(sql)
        self.conn.status = INTRANS

    def fetchone(self):
        return (1,)

    def close(self):
        self.closed = True


class FakeConn:
    def __init__(self):
        self.closed, self.autocommit, self.status, self.alive = 0, False, IDLE, True
        self.queries, self.rollbacks, self.commits = [], 0, 0
        self.encoding = "UTF8"

    def cursor(self, *args, **kwargs):
        return FakeCursor(self)

    def get_transaction_status(self):
        return self.status

    def rollback(self):
        self.rollbacks += 1
        self.status = IDLE

    def commit(self):
        self.commits += 1
        self.status = IDLE

    def close(self):
        self.closed = 1


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def make_pool(**kw):
    made = []

    def connect():
        made.append(FakeConn())
        return made[-1]

    kw.setdefault("clock", Clock())
    return ConnectionPool(connect, **kw), made


def underlying(conn: PooledConnection) -> FakeConn:
    return conn._slot.conn


class Lending(unittest.TestCase):
    def test_a_returned_connection_is_reused_not_reopened(self):
        pool, made = make_pool()
        first = pool.acquire()
        fake = underlying(first)
        first.close()
        second = pool.acquire()
        self.assertIs(underlying(second), fake)
        self.assertEqual(len(made), 1)
        self.assertEqual(pool.stats()["opened"], 1)

    def test_the_most_recently_used_connection_is_lent_first(self):
        pool, made = make_pool()
        a, b = pool.acquire(), pool.acquire()
        fake_b = underlying(b)
        a.close()
        b.close()  # b went back last
        self.assertIs(underlying(pool.acquire()), fake_b)

    def test_an_unfinished_transaction_is_rolled_back_before_the_next_borrower_has_it(self):
        pool, made = make_pool()
        conn = pool.acquire()
        fake = underlying(conn)
        fake.status = INTRANS  # a write nobody committed, with its row locks
        conn.close()
        self.assertEqual(fake.rollbacks, 1)
        self.assertEqual(underlying(pool.acquire()).status, IDLE)

    def test_a_connection_in_the_error_state_is_rolled_back_too(self):
        pool, made = make_pool()
        conn = pool.acquire()
        fake = underlying(conn)
        fake.status = INERROR
        conn.close()
        self.assertEqual(fake.rollbacks, 1)

    def test_a_clean_connection_costs_no_round_trip_to_return(self):
        pool, made = make_pool()
        conn = pool.acquire()
        fake = underlying(conn)
        conn.close()
        self.assertEqual(fake.rollbacks, 0)

    def test_autocommit_does_not_leak_to_the_next_borrower(self):
        pool, made = make_pool()
        conn = pool.acquire()
        fake = underlying(conn)
        fake.autocommit = True
        conn.close()
        self.assertFalse(underlying(pool.acquire()).autocommit)

    def test_a_connection_that_cannot_be_trusted_is_discarded_not_kept(self):
        for broken in ("closed", "unknown"):
            pool, made = make_pool()
            conn = pool.acquire()
            fake = underlying(conn)
            if broken == "closed":
                fake.closed = 2
            else:
                fake.status = UNKNOWN
            conn.close()
            self.assertEqual(pool.stats()["idle"], 0, broken)
            self.assertEqual(pool.stats()["open"], 0, broken)
            pool.acquire()
            self.assertEqual(len(made), 2, broken)

    def test_a_rollback_that_fails_discards_the_connection(self):
        pool, made = make_pool()
        conn = pool.acquire()
        fake = underlying(conn)
        fake.status = INTRANS
        fake.rollback = mock.Mock(side_effect=RuntimeError("gone"))
        conn.close()
        self.assertEqual(pool.stats()["idle"], 0)


class Wrapper(unittest.TestCase):
    def test_closing_twice_is_harmless_and_using_it_after_is_an_error(self):
        pool, made = make_pool()
        conn = pool.acquire()
        conn.close()
        conn.close()
        self.assertEqual(pool.stats()["idle"], 1)
        for use in (conn.cursor, conn.commit, conn.rollback):
            with self.assertRaises(PoolError):
                use()
        self.assertTrue(conn.closed)

    def test_it_looks_like_a_connection_to_the_code_that_uses_it(self):
        pool, made = make_pool()
        conn = pool.acquire()
        self.assertEqual(conn.encoding, "UTF8")  # anything else is passed through
        cur = conn.cursor()
        cur.execute("SELECT 2")
        conn.commit()
        self.assertEqual(underlying(conn).commits, 1)
        self.assertFalse(conn.closed)

    def test_as_a_context_manager_it_commits_or_rolls_back_and_does_not_close(self):
        pool, made = make_pool()
        with pool.acquire() as conn:
            fake = underlying(conn)
        self.assertEqual(fake.commits, 1)
        self.assertFalse(conn.closed)
        conn.close()
        broken = pool.acquire()
        with self.assertRaises(ValueError):
            with broken:
                raise ValueError("x")
        self.assertEqual(underlying(broken).rollbacks, 1)

    def test_a_half_built_wrapper_cannot_recurse_forever(self):
        bare = PooledConnection.__new__(PooledConnection)
        with self.assertRaises(AttributeError):
            _ = bare.anything
        bare.__del__()  # a finaliser on it must not raise either

    def test_a_connection_that_is_forgotten_is_returned_and_the_pool_says_so(self):
        pool, made = make_pool()
        with self.assertLogs("app.db_pool", level="WARNING") as caught:
            pool.acquire()  # dropped on the floor
            gc.collect()
        self.assertIn("dropped without being closed", caught.output[0])
        self.assertEqual(pool.stats()["in_use"], 0)
        self.assertEqual(pool.stats()["idle"], 1)


class Limits(unittest.TestCase):
    def test_it_never_opens_more_than_the_maximum(self):
        pool, made = make_pool(max_size=2, checkout_timeout=0.05, clock=time.monotonic)  # a timeout needs real time to pass
        a, b = pool.acquire(), pool.acquire()
        with self.assertRaises(PoolTimeout):
            pool.acquire()
        self.assertEqual(len(made), 2)
        self.assertEqual(pool.stats()["timeouts"], 1)
        a.close()
        self.assertIsNotNone(pool.acquire())  # and it recovers
        b.close()

    def test_a_waiting_caller_gets_the_next_connection_that_comes_back(self):
        pool, made = make_pool(max_size=1, checkout_timeout=5, clock=time.monotonic)
        held = pool.acquire()
        fake = underlying(held)
        got = []
        thread = threading.Thread(target=lambda: got.append(pool.acquire()))
        thread.start()
        time.sleep(0.1)
        self.assertEqual(got, [], "it must wait, not open a second connection")
        held.close()
        thread.join(2)
        self.assertIs(underlying(got[0]), fake)
        stats = pool.stats()
        self.assertEqual(stats["waits"], 1)
        self.assertGreater(stats["wait_seconds"], 0.05)
        self.assertEqual(len(made), 1)

    def test_a_connection_that_cannot_be_opened_does_not_use_up_the_pool(self):
        calls = {"n": 0}

        def connect():
            calls["n"] += 1
            if calls["n"] <= 2:
                raise ConnectionError("the database is starting")
            return FakeConn()

        pool = ConnectionPool(connect, max_size=1, checkout_timeout=0.05, clock=time.monotonic)
        for _ in range(2):
            with self.assertRaises(ConnectionError):
                pool.acquire()
        self.assertEqual(pool.stats()["open"], 0)
        self.assertEqual(pool.stats()["in_use"], 0)
        self.assertIsNotNone(pool.acquire())  # with a maximum of one, capacity was not lost to the failures

    def test_warm_opens_some_ahead_of_time(self):
        pool, made = make_pool(max_size=5)
        self.assertEqual(pool.warm(3), 3)
        self.assertEqual((pool.stats()["idle"], pool.stats()["in_use"], len(made)), (3, 0, 3))
        self.assertEqual(pool.warm(99), 5)  # never past the maximum


class Staleness(unittest.TestCase):
    def test_a_connection_past_its_age_is_replaced(self):
        clock = Clock()
        pool, made = make_pool(max_age=100, clock=clock)
        old = pool.acquire()
        fake = underlying(old)
        old.close()
        clock.now += 101
        fresh = pool.acquire()
        self.assertIsNot(underlying(fresh), fake)
        self.assertEqual(fake.closed, 1)
        self.assertEqual(len(made), 2)

    def test_one_that_has_been_quiet_is_checked_before_it_is_lent_and_is_fine(self):
        clock = Clock()
        pool, made = make_pool(ping_after=30, clock=clock)
        conn = pool.acquire()
        fake = underlying(conn)
        conn.close()
        clock.now += 31
        self.assertIs(underlying(pool.acquire()), fake)
        self.assertEqual(fake.queries, ["SELECT 1"])
        self.assertEqual(fake.status, IDLE, "the check must not leave a transaction open")

    def test_one_that_was_just_used_is_not_checked(self):
        clock = Clock()
        pool, made = make_pool(ping_after=30, clock=clock)
        conn = pool.acquire()
        fake = underlying(conn)
        conn.close()
        clock.now += 5
        pool.acquire()
        self.assertEqual(fake.queries, [])

    def test_a_connection_the_server_dropped_is_replaced_without_the_caller_noticing(self):
        """The database was restarted while the connection sat idle."""
        clock = Clock()
        pool, made = make_pool(ping_after=30, clock=clock)
        conn = pool.acquire()
        dead = underlying(conn)
        conn.close()
        dead.alive = False
        clock.now += 60
        fresh = pool.acquire()
        self.assertIsNot(underlying(fresh), dead)
        self.assertEqual(len(made), 2)
        self.assertEqual(dead.closed, 1)
        self.assertEqual(pool.stats()["discarded"], 1)
        self.assertEqual(pool.stats()["open"], 1)

    def test_a_whole_idle_pool_of_dead_connections_heals_in_one_call(self):
        clock = Clock()
        pool, made = make_pool(ping_after=30, keep_warm=5, clock=clock)
        held = [pool.acquire() for _ in range(4)]
        fakes = [underlying(c) for c in held]
        for c in held:
            c.close()
        for fake in fakes:
            fake.alive = False
        clock.now += 60
        fresh = pool.acquire()
        self.assertTrue(fresh._slot.conn.alive)
        self.assertEqual(pool.stats()["open"], 1)

    def test_long_idle_connections_beyond_the_warm_few_are_closed(self):
        clock = Clock()
        pool, made = make_pool(max_size=10, keep_warm=2, idle_ttl=100, ping_after=10**9, clock=clock)
        held = [pool.acquire() for _ in range(5)]
        for c in held:
            c.close()
        self.assertEqual(pool.stats()["idle"], 5)
        clock.now += 200
        pool.acquire()  # reaps on the way
        stats = pool.stats()
        self.assertEqual(stats["open"], 2)  # 5 idle, 3 reaped down to the 2 kept warm, one of which is now lent
        self.assertEqual(sum(1 for f in made if f.closed), 3)


class Shutdown(unittest.TestCase):
    def test_closing_the_pool_closes_what_is_idle_and_refuses_new_borrowers(self):
        pool, made = make_pool()
        a, b = pool.acquire(), pool.acquire()
        a.close()
        pool.close()
        self.assertEqual(made[0].closed + made[1].closed, 1)
        with self.assertRaises(PoolError):
            pool.acquire()
        b.close()  # one still out when it closed: returned later, and then closed, not kept
        self.assertTrue(all(f.closed for f in made))


class UnderLoad(unittest.TestCase):
    def test_many_threads_never_exceed_the_maximum_and_nothing_is_lost(self):
        pool, made = make_pool(max_size=3, checkout_timeout=30, clock=time.monotonic)
        lock = threading.Lock()
        state = {"now": 0, "peak": 0, "errors": []}

        def worker():
            for _ in range(40):
                try:
                    conn = pool.acquire()
                except Exception as exc:  # noqa: BLE001
                    state["errors"].append(exc)
                    return
                with lock:
                    state["now"] += 1
                    state["peak"] = max(state["peak"], state["now"])
                underlying(conn).status = INTRANS  # a unit of work that is never committed
                time.sleep(0.0005)
                with lock:
                    state["now"] -= 1
                conn.close()

        threads = [threading.Thread(target=worker) for _ in range(12)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(60)
        self.assertEqual(state["errors"], [])
        self.assertLessEqual(state["peak"], 3)
        stats = pool.stats()
        self.assertLessEqual(len(made), 3)
        self.assertEqual((stats["in_use"], stats["idle"], stats["open"]), (0, len(made), len(made)))
        self.assertGreater(stats["waits"], 0, "twelve workers on three connections must have waited")
        self.assertEqual(stats["timeouts"], 0)


class TheDatabaseLayer(unittest.TestCase):
    """db_cursor and get_connection on top of the pool, with a fake pool."""

    def setUp(self):
        self.pool, self.made = make_pool(max_size=3, clock=time.monotonic)
        patch = mock.patch.object(database, "_pool", self.pool)
        patch.start()
        self.addCleanup(patch.stop)
        patch = mock.patch.object(database, "_pool_pid", os.getpid())
        patch.start()
        self.addCleanup(patch.stop)

    def test_commit_true_commits_and_gives_the_connection_back(self):
        with database.db_cursor(commit=True) as cur:
            cur.execute("INSERT")
        fake = self.made[0]
        self.assertEqual((fake.commits, self.pool.stats()["in_use"]), (1, 0))

    def test_without_commit_nothing_is_committed_and_it_is_rolled_back_on_return(self):
        with database.db_cursor() as cur:
            cur.execute("SELECT")
        fake = self.made[0]
        self.assertEqual((fake.commits, fake.rollbacks), (0, 1))

    def test_an_error_rolls_back_re_raises_and_still_gives_the_connection_back(self):
        with self.assertRaises(ValueError):
            with database.db_cursor(commit=True) as cur:
                cur.execute("INSERT")
                raise ValueError("boom")
        fake = self.made[0]
        self.assertEqual((fake.commits, self.pool.stats()["in_use"]), (0, 0))
        self.assertGreaterEqual(fake.rollbacks, 1)

    def test_the_cursor_is_closed(self):
        with database.db_cursor() as cur:
            pass
        self.assertTrue(cur.closed)

    def test_the_raw_connection_sites_still_work_the_way_they_always_did(self):
        """billing, dw_sync, tally_*: conn = get_connection(); cur = conn.cursor(); ... conn.commit(); finally: cur.close(); conn.close()"""
        conn = database.get_connection()
        cur = conn.cursor()
        try:
            cur.execute("INSERT")
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()
            conn.close()
        self.assertEqual(self.pool.stats()["in_use"], 0)
        self.assertEqual(self.made[0].commits, 1)

    def test_an_error_inside_one_use_does_not_poison_the_next(self):
        with self.assertRaises(RuntimeError):
            with database.db_cursor(commit=True) as cur:
                self.made[0].status = INERROR
                raise RuntimeError("a failed statement")
        with database.db_cursor() as cur:
            cur.execute("SELECT 1")
        self.assertEqual(self.made[0].queries, ["SELECT 1"])  # the same connection, usable again
        self.assertEqual(self.made[0].status, IDLE)  # and clean again once given back
        self.assertEqual(len(self.made), 1)


class Configuration(unittest.TestCase):
    def test_the_pool_is_made_on_first_use_not_at_import(self):
        with mock.patch.object(database, "_pool", None):
            self.assertIsNone(database._pool)

    def test_its_size_comes_from_the_environment_with_sane_limits(self):
        self.assertEqual(database.pool_size({}), 20)
        self.assertEqual(database.pool_size({"ORION_DB_POOL_MAX": "8"}), 8)
        self.assertEqual(database.pool_size({"ORION_DB_POOL_MAX": "0"}), 1)
        self.assertEqual(database.pool_size({"ORION_DB_POOL_MAX": "lots"}), 20)
        self.assertEqual(database.pool_size({"ORION_DB_POOL_MAX": "10000"}), 100)  # never more than the server's own limit

    def test_a_forked_process_does_not_share_its_parents_connections(self):
        first = mock.Mock(name="first")
        with mock.patch.object(database, "_pool", first), mock.patch.object(database, "_pool_pid", os.getpid() + 1):
            with mock.patch.object(database, "ConnectionPool") as made:
                made.return_value = mock.Mock(name="second")
                self.assertIsNot(database.pool(), first)
                made.assert_called_once()

    def test_stats_are_available_for_the_system_page(self):
        with mock.patch.object(database, "_pool", None):
            self.assertIsNone(database.pool_stats())  # nothing opened yet is not an error

    def test_the_system_page_says_when_requests_gave_up_waiting_for_a_connection(self):
        from datetime import datetime, timezone

        from app import health

        now = datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)
        calm = {"ok": True, "ms": 2, "error": None, "pool": {"max": 20, "timeouts": 0}}
        self.assertEqual(health.attention(calm, None, [], [], now), [])
        pressed = {**calm, "pool": {"max": 20, "timeouts": 3}}
        note = health.attention(pressed, None, [], [], now)[0]
        self.assertIn("3 requests gave up waiting", note)
        self.assertIn("ORION_DB_POOL_MAX", note)
        self.assertEqual(health.attention({"ok": True, "ms": 2, "error": None, "pool": None}, None, [], [], now), [])  # before first use

    def test_a_busy_server_answers_503_not_500(self):
        from fastapi.testclient import TestClient

        from app.main import app

        @app.get("/api/__pool_busy_test")
        def busy():
            raise PoolTimeout("All 20 database connections were busy for 15 seconds.")

        try:
            response = TestClient(app, raise_server_exceptions=False).get("/api/__pool_busy_test")
        finally:
            app.router.routes[:] = [r for r in app.router.routes if getattr(r, "path", "") != "/api/__pool_busy_test"]
        self.assertEqual(response.status_code, 503)
        self.assertIn("busy", response.json()["detail"].lower())
        self.assertIn("Retry-After", response.headers)


class NothingBypassesThePool(unittest.TestCase):
    """A direct connection is slow (about 100 ms) and unbounded. The few that exist are deliberate, and listed."""

    ALLOWED = {
        "database.py": 1,  # raw_connection(): what the pool itself opens, and the way out for session state
        "auth.py": 1,  # _run_as_superuser: a different role, for the few changes the application's role may not make
        "dw_sync.py": 1,  # _run_sql: runs a schema script as the superuser when given its settings
        "tally_dw.py": 1,  # the same, for the Tally warehouse
        "tally_ods.py": 1,  # the same, for the Tally working copy
    }

    def test_only_the_listed_places_open_connections_themselves(self):
        found = {}
        for path in (ROOT / "backend" / "app").rglob("*.py"):
            count = path.read_text(encoding="utf-8").count("psycopg2.connect(")
            if count:
                found[path.name] = count
        self.assertEqual(found, self.ALLOWED, "a new psycopg2.connect must go through the pool, or be added here on purpose")

    def test_every_other_module_borrows_and_gives_back(self):
        for path in (ROOT / "backend" / "app").rglob("*.py"):
            if path.name in ("database.py", "db_pool.py"):
                continue
            text = path.read_text(encoding="utf-8")
            borrowed, returned = text.count("get_connection()"), text.count("conn.close()")
            if borrowed:
                self.assertGreaterEqual(returned, borrowed, f"{path.name}: a connection borrowed with get_connection() must be closed (given back)")


@unittest.skipUnless(RUN, "set ORION_DB_TESTS=1 to run these against the development database")
class AgainstTheRealDatabase(unittest.TestCase):
    PREFIX = "zz_pool_"

    def setUp(self):
        self.pool = ConnectionPool(lambda: database.raw_connection(), max_size=5, checkout_timeout=20, ping_after=0.0)
        self.addCleanup(self.pool.close)
        self.addCleanup(self.cleanup)

    def cleanup(self):
        with database.raw_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM orion_ods.auth_attempt WHERE username LIKE %s", (self.PREFIX + "%",))

    def backends(self):
        with database.raw_connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM pg_stat_activity WHERE usename = current_user AND datname = current_database()")
            return cur.fetchone()[0]

    def test_a_thousand_queries_use_a_handful_of_connections(self):
        before = self.backends()
        for _ in range(300):
            conn = self.pool.acquire()
            cur = conn.cursor()
            cur.execute("SELECT 1")
            cur.close()
            conn.close()
        self.assertEqual(self.pool.stats()["opened"], 1, "one connection should have served every one of them")
        self.assertLessEqual(self.backends() - before, 1)

    def test_an_unfinished_write_is_not_seen_by_the_next_borrower(self):
        conn = self.pool.acquire()
        cur = conn.cursor()
        cur.execute("INSERT INTO orion_ods.auth_attempt (kind, username, ip) VALUES ('login', %s, 'pool-test')", (self.PREFIX + "a",))
        cur.close()
        conn.close()  # never committed
        other = self.pool.acquire()
        cur = other.cursor()
        cur.execute("SELECT count(*) FROM orion_ods.auth_attempt WHERE username = %s", (self.PREFIX + "a",))
        self.assertEqual(cur.fetchone()[0], 0)
        cur.close()
        other.close()

    def test_row_locks_are_released_when_a_connection_comes_back(self):
        with database.raw_connection() as setup, setup.cursor() as cur:
            cur.execute("INSERT INTO orion_ods.auth_attempt (kind, username, ip) VALUES ('login', %s, 'pool-test') RETURNING id", (self.PREFIX + "lock",))
            row_id = cur.fetchone()[0]
        conn = self.pool.acquire()
        cur = conn.cursor()
        cur.execute("SELECT id FROM orion_ods.auth_attempt WHERE id = %s FOR UPDATE", (row_id,))
        cur.close()
        conn.close()  # holding the lock, then given back
        with database.raw_connection() as probe, probe.cursor() as cur:
            cur.execute("SELECT id FROM orion_ods.auth_attempt WHERE id = %s FOR UPDATE NOWAIT", (row_id,))  # would raise if still locked
            self.assertEqual(cur.fetchone()[0], row_id)

    def test_a_connection_killed_on_the_server_is_replaced_not_lent(self):
        conn = self.pool.acquire()
        cur = conn.cursor()
        cur.execute("SELECT pg_backend_pid()")
        pid = cur.fetchone()[0]
        cur.close()
        conn.close()
        with database.raw_connection() as admin, admin.cursor() as cur:
            cur.execute("SELECT pg_terminate_backend(%s)", (pid,))
        time.sleep(0.2)
        fresh = self.pool.acquire()  # ping_after=0: it asks before lending
        cur = fresh.cursor()
        cur.execute("SELECT pg_backend_pid()")
        self.assertNotEqual(cur.fetchone()[0], pid)
        cur.close()
        fresh.close()
        self.assertEqual(self.pool.stats()["discarded"], 1)

    def test_thirty_threads_share_five_connections(self):
        errors = []

        def work():
            try:
                for _ in range(10):
                    conn = self.pool.acquire()
                    cur = conn.cursor()
                    cur.execute("SELECT pg_sleep(0.002)")
                    cur.close()
                    conn.close()
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=work) for _ in range(30)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(60)
        self.assertEqual(errors, [])
        stats = self.pool.stats()
        self.assertLessEqual(stats["open"], 5)
        self.assertEqual((stats["in_use"], stats["timeouts"]), (0, 0))

    def test_the_applications_own_layer_works_end_to_end(self):
        with database.db_cursor(commit=True) as cur:
            cur.execute("INSERT INTO orion_ods.auth_attempt (kind, username, ip) VALUES ('login', %s, 'pool-test')", (self.PREFIX + "app",))
        with database.db_cursor() as cur:
            cur.execute("SELECT count(*) FROM orion_ods.auth_attempt WHERE username = %s", (self.PREFIX + "app",))
            self.assertEqual(cur.fetchone()[0], 1)
        stats = database.pool_stats()
        self.assertIsNotNone(stats)
        self.assertEqual(stats["in_use"], 0)


if __name__ == "__main__":
    unittest.main()
