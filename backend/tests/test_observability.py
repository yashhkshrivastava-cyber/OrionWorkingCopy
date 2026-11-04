"""Seeing what the server is doing: request ids, the log, the access line, errors, and the health answers.

None of this needs a database (the System page's own test, against the real one, is in test_sessions_and_throttle.py and runs
with ORION_AUTH_DB_TESTS=1). Run from the repo root:  python -m pytest backend/tests
"""

import inspect
import io
import logging
import re
import sys
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from fastapi import FastAPI, HTTPException, WebSocket
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app import auth, health, observability as obs, signup  # noqa: E402
from app.main import app  # noqa: E402
from app.routers import health_router  # noqa: E402
from app.security_headers import SecurityHeadersMiddleware  # noqa: E402


class RequestIds(unittest.TestCase):
    def test_a_sane_incoming_id_is_kept(self):
        self.assertEqual(obs.request_id_from("abc-123_DEF.456"), "abc-123_DEF.456")
        self.assertEqual(obs.request_id_from("  my-request-0001 "), "my-request-0001")

    def test_anything_else_is_replaced_so_a_log_line_cannot_be_forged(self):
        for bad in (None, "", "short", "x" * 65, "has spaces in it", "line\nbreak-0001", "semi;colon-0001", "tab\tbed-00001", "ünïcode-12345"):
            made = obs.request_id_from(bad)
            self.assertRegex(made, r"^[0-9a-f]{16}$", repr(bad))

    def test_each_made_id_is_new(self):
        self.assertNotEqual(obs.request_id_from(None), obs.request_id_from(None))


class Formatting(unittest.TestCase):
    def capture(self):
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(logging.Formatter(obs.LOG_FORMAT))
        handler.addFilter(obs.ContextFilter())
        log = logging.getLogger("orion.test.format")
        log.setLevel(logging.INFO)
        log.propagate = False
        log.addHandler(handler)
        self.addCleanup(log.removeHandler, handler)
        return log, stream

    def test_a_line_outside_a_request_still_formats(self):
        log, stream = self.capture()
        log.info("hello")
        self.assertRegex(stream.getvalue(), r"INFO +\[- u-\] orion\.test\.format: hello")

    def test_a_line_inside_a_request_carries_its_id_and_user(self):
        log, stream = self.capture()
        token, actor = obs.REQUEST_ID.set("req-0000000001"), obs.ACTOR.set({"id": "-"})
        try:
            obs.bind_user(7)
            log.info("in a request")
        finally:
            obs.REQUEST_ID.reset(token)
            obs.ACTOR.reset(actor)
        self.assertIn("[req-0000000001 u7]", stream.getvalue())

    def test_binding_a_user_outside_a_request_does_nothing(self):
        obs.bind_user(9)
        self.assertEqual(obs.current_user_id(), "-")


class RecentProblems(unittest.TestCase):
    def handler(self, capacity=5):
        handler = obs.RecentProblems(capacity)
        log = logging.getLogger("orion.test.problems")
        log.setLevel(logging.DEBUG)
        log.propagate = False
        log.addHandler(handler)
        self.addCleanup(log.removeHandler, handler)
        return handler, log

    def test_only_warnings_and_errors_are_kept_newest_first(self):
        handler, log = self.handler()
        log.info("ignored")
        log.warning("first")
        log.error("second")
        self.assertEqual([r["message"] for r in reversed(list(handler.records))], ["second", "first"])
        self.assertEqual({r["level"] for r in handler.records}, {"WARNING", "ERROR"})

    def test_an_exception_is_summarised_not_dumped(self):
        handler, log = self.handler()
        try:
            raise ValueError("bad value")
        except ValueError:
            log.exception("it broke")
        message = handler.records[0]["message"]
        self.assertIn("it broke", message)
        self.assertIn("ValueError: bad value", message)
        self.assertNotIn("Traceback", message)

    def test_it_forgets_the_oldest_and_cuts_long_messages(self):
        handler, log = self.handler(capacity=3)
        for number in range(6):
            log.warning("m%d", number)
        self.assertEqual([r["message"] for r in handler.records], ["m3", "m4", "m5"])
        log.warning("x" * 1000)
        self.assertLessEqual(len(handler.records[-1]["message"]), 400)


class Settings(unittest.TestCase):
    def test_the_slow_limit(self):
        self.assertEqual(obs.slow_threshold_ms({}), obs.DEFAULT_SLOW_MS)
        self.assertEqual(obs.slow_threshold_ms({"ORION_SLOW_REQUEST_MS": "500"}), 500)
        self.assertEqual(obs.slow_threshold_ms({"ORION_SLOW_REQUEST_MS": "nonsense"}), obs.DEFAULT_SLOW_MS)
        self.assertEqual(obs.slow_threshold_ms({"ORION_SLOW_REQUEST_MS": "1"}), 50)  # never so low that everything is "slow"

    def test_the_level_and_switches(self):
        self.assertEqual(obs.log_level({}), logging.INFO)
        self.assertEqual(obs.log_level({"ORION_LOG_LEVEL": "debug"}), logging.DEBUG)
        self.assertEqual(obs.log_level({"ORION_LOG_LEVEL": "loud"}), logging.INFO)
        self.assertTrue(obs.log_file_enabled({}))
        self.assertFalse(obs.log_file_enabled({"ORION_LOG_FILE": "0"}))
        self.assertTrue(obs.access_log_enabled({}))
        self.assertFalse(obs.access_log_enabled({"ORION_ACCESS_LOG": "off"}))

    def test_the_log_folder_is_under_data_which_git_ignores(self):
        folder = obs.log_dir({})
        self.assertEqual(folder, ROOT / "data" / "logs")
        self.assertIn("/data/", (ROOT / ".gitignore").read_text(encoding="utf-8"))
        self.assertEqual(obs.log_dir({"ORION_LOG_DIR": "D:/elsewhere"}), Path("D:/elsewhere"))


class Configuring(unittest.TestCase):
    """Sets up the real handlers in a temporary folder, then takes every one of them away again."""

    def setUp(self):
        self.root = logging.getLogger()
        self.before = (list(self.root.handlers), self.root.level, threading.excepthook)
        self.uvicorn_before = {name: list(logging.getLogger(name).handlers) for name in ("uvicorn", "uvicorn.error")}
        self.access_before = logging.getLogger("uvicorn.access").disabled

    def tearDown(self):
        self.root.handlers[:] = self.before[0]
        self.root.setLevel(self.before[1])
        threading.excepthook = self.before[2]
        for name, handlers in self.uvicorn_before.items():
            logging.getLogger(name).handlers[:] = handlers
        logging.getLogger("uvicorn.access").disabled = self.access_before
        for handler in list(self.root.handlers):
            if getattr(handler, "_orion", False):
                self.root.removeHandler(handler)

    def test_it_writes_a_file_once_however_often_it_is_called(self):
        for handler in list(self.root.handlers):
            if getattr(handler, "_orion", False):
                self.root.removeHandler(handler)
        with tempfile.TemporaryDirectory() as folder:
            env = {"ORION_LOG_DIR": folder, "ORION_LOG_LEVEL": "INFO"}
            obs.configure_logging(env)
            obs.configure_logging(env)  # a reload must not double every line
            files = [h for h in self.root.handlers if isinstance(h, logging.handlers.RotatingFileHandler)]
            self.assertEqual(len(files), 1)
            self.assertEqual((files[0].maxBytes, files[0].backupCount), (obs.LOG_FILE_BYTES, obs.LOG_FILE_KEEP))
            logging.getLogger("orion.test.file").warning("written to the file")
            for handler in self.root.handlers:
                handler.flush()
            text = (Path(folder) / obs.LOG_FILE_NAME).read_text(encoding="utf-8")
            self.assertIn("written to the file", text)
            self.assertRegex(text, r"WARNING +\[- u-\]")
            for handler in files:
                handler.close()
                self.root.removeHandler(handler)

    def test_quiet_libraries_and_the_servers_own_access_log(self):
        for handler in list(self.root.handlers):
            if getattr(handler, "_orion", False):
                self.root.removeHandler(handler)
        obs.configure_logging({"ORION_LOG_FILE": "0"})
        self.assertGreaterEqual(logging.getLogger("httpx").level, logging.WARNING)
        self.assertGreaterEqual(logging.getLogger("botocore").level, logging.WARNING)
        self.assertTrue(logging.getLogger("uvicorn.access").disabled, "our access line replaces uvicorn's, or every request is logged twice")

    def test_a_thread_that_dies_is_logged_not_lost(self):
        for handler in list(self.root.handlers):
            if getattr(handler, "_orion", False):
                self.root.removeHandler(handler)
        obs.configure_logging({"ORION_LOG_FILE": "0"})
        with self.assertLogs("orion.threads", level="ERROR") as caught:
            worker = threading.Thread(target=lambda: 1 / 0, name="orion-test-worker")
            worker.start()
            worker.join()
        self.assertIn("orion-test-worker", caught.output[0])
        self.assertIn("ZeroDivisionError", caught.output[0])


def mini_app() -> FastAPI:
    """The same three layers in the same order as main.py, around a few routes."""
    mini = FastAPI()
    mini.add_middleware(obs.ErrorBoundaryMiddleware)
    mini.add_middleware(SecurityHeadersMiddleware)
    mini.add_middleware(obs.RequestContextMiddleware)

    @mini.get("/api/ok")
    def ok():
        return {"ok": True}

    @mini.get("/api/who")
    def who():
        obs.bind_user(42)  # a plain `def` route runs in a worker thread, as the sign-in check does
        return {"ok": True}

    @mini.get("/api/slow")
    def slow():
        time.sleep(0.12)
        return {"ok": True}

    @mini.get("/api/boom")
    def boom():
        raise RuntimeError("secret internal detail: password=hunter2")

    @mini.get("/api/missing-thing")
    def missing():
        raise HTTPException(status_code=404, detail="no such thing")

    @mini.get("/api/health")
    def alive():
        return {"status": "ok"}

    @mini.websocket("/ws")
    async def socket(websocket: WebSocket):
        await websocket.accept()
        await websocket.send_json({"id": obs.REQUEST_ID.get()})
        await websocket.close()

    return mini


class Middleware(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(mini_app(), raise_server_exceptions=False)

    def test_every_answer_carries_a_request_id(self):
        response = self.client.get("/api/ok")
        self.assertRegex(response.headers["x-request-id"], r"^[0-9a-f]{16}$")

    def test_the_browsers_id_is_echoed_and_a_bad_one_replaced(self):
        self.assertEqual(self.client.get("/api/ok", headers={"X-Request-ID": "browser-ref-0001"}).headers["x-request-id"], "browser-ref-0001")
        replaced = self.client.get("/api/ok", headers={"X-Request-ID": "not ok at all"}).headers["x-request-id"]
        self.assertNotEqual(replaced, "not ok at all")

    def test_the_access_line_has_the_path_and_never_the_query_string(self):
        with self.assertLogs("orion.access", level="INFO") as caught:
            self.client.get("/api/ok?token=RESET-TOKEN-123&password=hunter2")
        line = caught.output[0]
        self.assertIn("GET /api/ok -> 200", line)
        self.assertNotIn("RESET-TOKEN-123", line)
        self.assertNotIn("hunter2", line)
        self.assertNotIn("?", line)

    def test_who_made_the_request_reaches_the_access_line_from_a_worker_thread(self):
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(logging.Formatter(obs.LOG_FORMAT))
        handler.addFilter(obs.ContextFilter())
        log = logging.getLogger("orion.access")
        log.addHandler(handler)
        self.addCleanup(log.removeHandler, handler)
        log.setLevel(logging.INFO)
        self.client.get("/api/who", headers={"X-Request-ID": "trace-me-000001"})
        self.assertRegex(stream.getvalue(), r"\[trace-me-000001 u42\] orion\.access: GET /api/who -> 200")

    def test_health_checks_do_not_fill_the_log(self):
        with self.assertNoLogs("orion.access", level="INFO"):
            self.client.get("/api/health")

    def test_a_slow_request_is_a_warning_and_is_remembered(self):
        before = obs.STATS.snapshot()["slow"]
        with mock.patch.dict("os.environ", {"ORION_SLOW_REQUEST_MS": "50"}):
            with self.assertLogs("orion.access", level="WARNING") as caught:
                response = self.client.get("/api/slow")
        self.assertIn("(slow)", caught.output[0])
        snapshot = obs.STATS.snapshot()
        self.assertEqual(snapshot["slow"], before + 1)
        self.assertEqual(snapshot["recent_slow"][-1]["request_id"], response.headers["x-request-id"])
        self.assertEqual(snapshot["recent_slow"][-1]["path"], "/api/slow")

    def test_an_unhandled_error_gets_a_reference_and_leaks_nothing(self):
        with self.assertLogs("orion.errors", level="ERROR") as caught:
            response = self.client.get("/api/boom")
        reference = response.headers["x-request-id"]
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()["request_id"], reference)
        self.assertIn(reference, response.json()["detail"])
        self.assertNotIn("hunter2", response.text)  # what went wrong goes to the log, not to the browser
        self.assertNotIn("RuntimeError", response.text)
        self.assertIn("RuntimeError", "\n".join(caught.output))  # with its traceback
        self.assertIn("password=hunter2", "\n".join(caught.output))  # (the log is the developer's place for it)

    def test_the_error_answer_still_has_the_security_headers(self):
        response = self.client.get("/api/boom")
        self.assertEqual(response.headers["x-content-type-options"], "nosniff")
        self.assertIn("content-security-policy", response.headers)

    def test_an_ordinary_refusal_is_not_an_error(self):
        with self.assertNoLogs("orion.errors", level="ERROR"):
            response = self.client.get("/api/missing-thing")
        self.assertEqual((response.status_code, response.json()["detail"]), (404, "no such thing"))

    def test_a_server_error_is_counted(self):
        before = obs.STATS.snapshot()["errors_5xx"]
        self.client.get("/api/boom")
        self.assertEqual(obs.STATS.snapshot()["errors_5xx"], before + 1)

    def test_the_chat_socket_gets_an_id_and_passes_through(self):
        with self.client.websocket_connect("/ws") as socket:
            self.assertRegex(socket.receive_json()["id"], r"^[0-9a-f]{16}$")

    def test_the_ids_do_not_leak_between_requests(self):
        first = self.client.get("/api/ok").headers["x-request-id"]
        second = self.client.get("/api/ok").headers["x-request-id"]
        self.assertNotEqual(first, second)
        self.assertEqual(obs.REQUEST_ID.get(), "-")


class RealApp(unittest.TestCase):
    def test_the_layers_are_in_the_order_that_makes_errors_look_right(self):
        names = [m.cls.__name__ for m in app.user_middleware]  # outermost first
        self.assertEqual(names[0], "RequestContextMiddleware")
        self.assertLess(names.index("CORSMiddleware"), names.index("SecurityHeadersMiddleware"))
        self.assertLess(names.index("SecurityHeadersMiddleware"), names.index("ErrorBoundaryMiddleware"))

    def test_the_old_health_answer_is_unchanged(self):
        response = TestClient(app).get("/api/health")  # the desktop launchers poll this
        self.assertEqual(response.json(), {"status": "ok"})
        self.assertIn("x-request-id", response.headers)

    def test_ready_says_up_or_down_and_asks_the_database_only_now_and_then(self):
        with mock.patch.object(health, "check_database", return_value={"ok": True, "ms": 2, "error": None}) as check:
            health._ready_cache["at"] = 0.0
            client = TestClient(app)
            first, second = client.get("/api/health/ready"), client.get("/api/health/ready")
        self.assertEqual((first.status_code, first.json()), (200, {"status": "ok", "database": "ok"}))
        self.assertEqual(second.status_code, 200)
        self.assertEqual(check.call_count, 1, "polling the readiness check must not make the database work each time")

    def test_ready_is_503_when_the_database_does_not_answer(self):
        with mock.patch.object(health, "check_database", return_value={"ok": False, "ms": None, "error": "OperationalError"}):
            health._ready_cache["at"] = 0.0
            response = TestClient(app).get("/api/health/ready")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"status": "degraded", "database": "down"})
        health._ready_cache["at"] = 0.0  # do not leave a "down" cached for the next test

    def test_the_details_are_for_administrators_only(self):
        route = next(r for r in health_router.router.routes if r.path.endswith("/details"))
        self.assertIn("require_admin", {dep.call.__name__ for dep in route.dependant.dependencies})
        self.assertEqual(TestClient(app).get("/api/health/details").status_code, 401)


class Attention(unittest.TestCase):
    now = datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)
    database = {"ok": True, "ms": 3, "error": None}

    def notes(self, **kw):
        args = {"database": self.database, "backups": None, "loads": [], "problems": [], "now": self.now, **kw}
        return health.attention(args["database"], args["backups"], args["loads"], args["problems"], args["now"])

    def test_nothing_wrong_says_nothing(self):
        self.assertEqual(self.notes(), [])

    def test_a_silent_database(self):
        self.assertIn("database did not answer", self.notes(database={"ok": False, "ms": None, "error": "X"})[0])

    def test_an_overdue_or_blocked_backup(self):
        stale = {"state": "ready", "stale": True, "last_success": {"finished_timestamp": (self.now - timedelta(days=3)).isoformat()}}
        self.assertIn("3 days ago", self.notes(backups=stale)[0])
        blocked = {"state": "blocked", "problems": ["the key is missing"], "stale": False}
        self.assertIn("the key is missing", self.notes(backups=blocked)[0])
        self.assertEqual(self.notes(backups={"state": "off", "stale": False}), [])  # off on purpose is not a problem
        self.assertEqual(self.notes(backups={"state": "ready", "stale": False}), [])

    def test_a_load_that_failed_since_it_last_worked(self):
        failing = {"pipeline": "orion_dw", "failing": True, "last_failure": (self.now - timedelta(hours=2)).isoformat(), "last_error": "disk full"}
        text = self.notes(loads=[failing])[0]
        self.assertIn("orion_dw", text)
        self.assertIn("2 hours ago", text)
        self.assertIn("disk full", text)
        self.assertEqual(self.notes(loads=[{**failing, "failing": False}]), [])

    def test_a_failing_tender_check_is_named_only_while_searches_are_active(self):
        failed = {"failing": True, "last_run": {"finished_timestamp": (self.now - timedelta(hours=2)).isoformat(), "error": "Could not reach GeM."}}
        notes = health.attention(self.database, None, [], [], self.now, None, {"gem": failed, "mptenders": {"failing": False}})
        self.assertEqual(len(notes), 1)
        self.assertIn("GeM tender check failed 2 hours ago: Could not reach GeM.", notes[0])
        self.assertEqual(health.attention(self.database, None, [], [], self.now, None, {"gem": {**failed, "failing": False}}), [])
        notes = health.attention(self.database, None, [], [], self.now, None, {"mptenders": failed})
        self.assertIn("The MP Tenders tender check failed", notes[0])

    def test_errors_in_the_last_hour_count_but_old_ones_and_warnings_do_not(self):
        recent = {"level": "ERROR", "time": (self.now - timedelta(minutes=10)).isoformat()}
        old = {"level": "ERROR", "time": (self.now - timedelta(hours=5)).isoformat()}
        warning = {"level": "WARNING", "time": (self.now - timedelta(minutes=1)).isoformat()}
        self.assertIn("1 error in the log", self.notes(problems=[recent, old, warning])[0])
        self.assertEqual(self.notes(problems=[old, warning]), [])


class Details(unittest.TestCase):
    def test_the_page_gets_everything_it_shows_without_secrets(self):
        loads = [{"pipeline": "orion_dw", "last_success": "2026-10-19T10:00:00+00:00", "last_failure": None, "last_error": None, "running": False, "failing": False}]
        status = {"state": "ready", "problems": [], "running": False, "last_success": {"finished_timestamp": "2026-10-19T03:00:00+00:00"},
                  "next_run": None, "stale": False, "interval_hours": 24, "bucket": "ProdPostgres", "role": "prod", "recent": [{"error": "x"}]}
        one = {"running": False, "active_searches": 1, "every_hours": 6, "next_check": None, "last_run": None, "failing": False}
        tender_check = {"gem": one, "mptenders": one}
        with mock.patch.object(health, "check_database", return_value={"ok": True, "ms": 3, "error": None}), \
             mock.patch.object(health, "pipelines", return_value=loads), mock.patch.object(health.backup, "status", return_value=status),              mock.patch.object(health.tenders, "status_all", return_value=tender_check):
            found = health.details()
        self.assertEqual(found["status"], "ok")
        self.assertEqual(found["tenders"], tender_check)
        self.assertEqual(found["loads"], loads)
        self.assertEqual(found["backup"]["state"], "ready")
        for left_out in ("bucket", "role", "recent"):
            self.assertNotIn(left_out, found["backup"], f"{left_out} is not for the System page")
        for key in ("requests", "problems", "log", "autoload", "environment", "checked"):
            self.assertIn(key, found)

    def test_a_dead_database_still_answers_instead_of_failing(self):
        with mock.patch.object(health, "check_database", return_value={"ok": False, "ms": None, "error": "OperationalError"}):
            found = health.details()
        self.assertEqual(found["status"], "attention")
        self.assertEqual((found["loads"], found["backup"]), ([], None))


class NothingIsSwallowed(unittest.TestCase):
    def test_the_handlers_that_used_to_hide_a_failure_now_say_so(self):
        for function in (auth._username_taken, auth._run_as_superuser, signup.ensure_signup_table, signup.count_pending_signups):
            self.assertIn("logger.", inspect.getsource(function), function.__name__)

    def test_not_owning_a_table_that_exists_is_not_an_alarm(self):
        """The System page says "needs attention" for any logged error, so a normal condition must not be one: this very
        message was an error on every start of the development server until it was caught by looking at the page."""
        from psycopg2 import errors as pg_errors

        failure = pg_errors.InsufficientPrivilege("must be owner of table signup_request")
        with mock.patch.object(signup, "db_cursor", side_effect=failure):
            with self.assertNoLogs("app.signup", level="INFO"):
                signup.ensure_signup_table()
        with mock.patch.object(signup, "db_cursor", side_effect=RuntimeError("the disk is on fire")):
            with self.assertLogs("app.signup", level="ERROR"):
                signup.ensure_signup_table()

    def test_the_backend_prints_nothing_to_nowhere(self):
        # observability.py: a log file that could not be opened, before logging exists. startup_checks.py: the command-line check
        # that deploy.ps1 runs, whose output IS the point. migrate.py and deploy_tools.py: the same, command-line tools.
        allowed = {"observability.py", "startup_checks.py", "migrate.py", "deploy_tools.py"}
        offenders = []
        for path in (ROOT / "backend" / "app").rglob("*.py"):
            if path.name in allowed:
                continue
            if re.search(r"(?m)^\s*print\(", path.read_text(encoding="utf-8")):
                offenders.append(str(path.relative_to(ROOT)))
        self.assertEqual(offenders, [], "use logging: a print has no time, level or request id and is not in the log file")


if __name__ == "__main__":
    unittest.main()
