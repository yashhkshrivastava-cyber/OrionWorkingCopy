"""Seeing what the server is doing: one log format, a reference on every request, and what has gone wrong lately.

Before this the log had no format, no file, no way to connect a line to a request, and an unhandled error answered with a
bare "Internal Server Error" that told the person and the developer nothing. Now:

* every request gets a **request id** (the browser's ``X-Request-ID`` if it sent a sane one, else a fresh one). It is on every
  log line made while serving it, comes back in the ``X-Request-ID`` response header, and is what an error message quotes, so
  "something went wrong, reference a1b2c3" finds the exact lines, including the traceback;
* one **access line** per request: method, path, status, how long, who (a user number, never a name). Never the query string
  (a password-reset link carries its token there), never a body, never a cookie;
* a request slower than ``ORION_SLOW_REQUEST_MS`` (2000) is logged as a warning and kept for the System page;
* an **unhandled error** is logged once with its traceback and answered with a JSON message and the request id (and still
  carries the CORS and security headers, so the browser shows the message instead of a network error);
* logs go to the console and to a rotating file, ``data/logs/orion.log`` (10 MB x 10), so a restart does not lose them;
* the last warnings and errors, slow requests and counters are kept in memory for the admin System page (``health.py``).

Nothing here reads the database. ``ORION_LOG_LEVEL`` (INFO), ``ORION_LOG_DIR``, ``ORION_LOG_FILE=0`` (no file) and
``ORION_ACCESS_LOG=0`` (no access lines) tune it.
"""

import collections
import contextvars
import json
import logging
import logging.handlers
import os
import re
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from starlette.datastructures import MutableHeaders

from app.config import ROOT

LOG_FORMAT = "%(asctime)s %(levelname)-7s [%(request_id)s u%(user_id)s] %(name)s: %(message)s"
LOG_FILE_NAME = "orion.log"
LOG_FILE_BYTES = 10 * 1024 * 1024
LOG_FILE_KEEP = 10
DEFAULT_SLOW_MS = 2000

# Libraries that log every call at INFO; their lines would drown ours and name the hosts we talk to.
QUIET_LIBRARIES = ("httpx", "httpcore", "httpx2", "httpcore2", "botocore", "boto3", "urllib3", "PIL", "asyncio", "multipart", "watchfiles")

REQUEST_ID: contextvars.ContextVar[str] = contextvars.ContextVar("orion_request_id", default="-")
# A holder, not the number itself: the sign-in check runs in a worker thread with a COPY of the context, so only a shared
# object lets the access line see who the request turned out to be.
ACTOR: contextvars.ContextVar[Optional[dict]] = contextvars.ContextVar("orion_actor", default=None)

_ID_OK = re.compile(r"^[A-Za-z0-9._-]{8,64}$")
_PLAIN_PATHS = ("/api/health", "/assets/", "/favicon", "/theme-boot.js", "/images/")  # logged at DEBUG: they say nothing

access_log = logging.getLogger("orion.access")
logger = logging.getLogger(__name__)


# ------------------------------------------------------------------------------------------------------------ the context


def request_id_from(incoming: Optional[str]) -> str:
    """The browser's own id when it is a plain token of sensible length (never anything that could forge a log line), else new."""
    if incoming and _ID_OK.fullmatch(incoming.strip()):
        return incoming.strip()
    return uuid.uuid4().hex[:16]


def bind_user(user_id) -> None:
    """Say who this request is, once the sign-in check has found out. A no-op outside a request."""
    holder = ACTOR.get()
    if holder is not None:
        holder["id"] = str(user_id)


def current_user_id() -> str:
    holder = ACTOR.get()
    return holder["id"] if holder else "-"


class ContextFilter(logging.Filter):
    """Puts the request id and user on every record, so the format never fails and a log line can be traced to its request."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = REQUEST_ID.get()
        record.user_id = current_user_id()
        return True


# --------------------------------------------------------------------------------------------------------- what went wrong


class RecentProblems(logging.Handler):
    """The last warnings and errors, kept in memory for the System page. Lost on restart (the file has the history)."""

    def __init__(self, capacity: int = 100):
        super().__init__(level=logging.WARNING)
        self.records: collections.deque = collections.deque(maxlen=capacity)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = record.getMessage()
            if record.exc_info and record.exc_info[1] is not None:
                message += f"  [{type(record.exc_info[1]).__name__}: {record.exc_info[1]}]"
            self.records.append(
                {
                    "time": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
                    "level": record.levelname,
                    "logger": record.name,
                    "request_id": REQUEST_ID.get(),
                    "message": message[:400],
                }
            )
        except Exception:  # noqa: BLE001 - logging must never be what breaks the app
            self.handleError(record)


class RequestStats:
    """Counters since the process started, and the slowest recent requests."""

    def __init__(self):
        self.lock = threading.Lock()
        self.started = time.time()
        self.total = 0
        self.errors = 0  # 5xx answers
        self.slow = 0
        self.recent_slow: collections.deque = collections.deque(maxlen=30)

    def record(self, method: str, path: str, status: int, ms: int, slow: bool, request_id: str) -> None:
        with self.lock:
            self.total += 1
            if status >= 500:
                self.errors += 1
            if slow:
                self.slow += 1
                self.recent_slow.append(
                    {"time": datetime.now(timezone.utc).isoformat(), "method": method, "path": path, "status": status, "ms": ms, "request_id": request_id}
                )

    def snapshot(self) -> dict:
        with self.lock:
            return {
                "since": datetime.fromtimestamp(self.started, timezone.utc).isoformat(),
                "uptime_seconds": int(time.time() - self.started),
                "total": self.total,
                "errors_5xx": self.errors,
                "slow": self.slow,
                "slow_threshold_ms": slow_threshold_ms(),
                "recent_slow": list(self.recent_slow),
            }


STATS = RequestStats()
PROBLEMS = RecentProblems()


def recent_problems(limit: int = 30) -> list[dict]:
    return list(PROBLEMS.records)[-limit:][::-1]  # newest first


def slow_threshold_ms(environ=None) -> int:
    raw = (environ or os.environ).get("ORION_SLOW_REQUEST_MS", "")
    try:
        return max(50, int(raw))
    except ValueError:
        return DEFAULT_SLOW_MS


def access_log_enabled(environ=None) -> bool:
    return (environ or os.environ).get("ORION_ACCESS_LOG", "1").strip().lower() not in ("0", "false", "no", "off")


# ------------------------------------------------------------------------------------------------------------ the set-up


def log_dir(environ=None) -> Path:
    given = (environ or os.environ).get("ORION_LOG_DIR", "").strip()
    return Path(given) if given else ROOT / "data" / "logs"


def log_level(environ=None) -> int:
    name = ((environ or os.environ).get("ORION_LOG_LEVEL") or "INFO").strip().upper()
    level = logging.getLevelName(name)
    return level if isinstance(level, int) else logging.INFO


def log_file_enabled(environ=None) -> bool:
    return (environ or os.environ).get("ORION_LOG_FILE", "1").strip().lower() not in ("0", "false", "no", "off")


def configure_logging(environ=None) -> None:
    """Set up the console and file handlers, once (a reload or a second call changes nothing)."""
    root = logging.getLogger()
    if any(getattr(handler, "_orion", False) for handler in root.handlers):
        return
    formatter = logging.Formatter(LOG_FORMAT)
    context = ContextFilter()

    console = logging.StreamHandler()
    handlers: list[logging.Handler] = [console]
    if log_file_enabled(environ):
        try:
            folder = log_dir(environ)
            folder.mkdir(parents=True, exist_ok=True)
            handlers.append(
                logging.handlers.RotatingFileHandler(
                    folder / LOG_FILE_NAME, maxBytes=LOG_FILE_BYTES, backupCount=LOG_FILE_KEEP, encoding="utf-8", delay=True
                )
            )
        except OSError as exc:  # a read-only folder must not stop the app from starting
            print(f"Orion: could not open the log file in {log_dir(environ)}: {exc}")
    for handler in handlers:
        handler.setFormatter(formatter)
        handler.addFilter(context)
        handler._orion = True  # type: ignore[attr-defined]
        root.addHandler(handler)
    PROBLEMS._orion = True  # type: ignore[attr-defined]
    PROBLEMS.addFilter(context)
    root.addHandler(PROBLEMS)
    root.setLevel(log_level(environ))
    for name in QUIET_LIBRARIES:
        logging.getLogger(name).setLevel(logging.WARNING)

    # uvicorn keeps its own console handler and does not pass its lines up, so the file would miss the server's own messages
    # (startup, shutdown, a crash it reports). Our access line replaces its access log.
    for name in ("uvicorn", "uvicorn.error"):
        server = logging.getLogger(name)
        for handler in handlers[1:] + [PROBLEMS]:
            if handler not in server.handlers:
                server.addHandler(handler)
    logging.getLogger("uvicorn.access").disabled = True

    def thread_crashed(args: threading.ExceptHookArgs) -> None:
        if args.exc_type is SystemExit:
            return
        name = args.thread.name if args.thread else "?"
        logging.getLogger("orion.threads").error(
            "Background thread %s stopped with an error", name, exc_info=(args.exc_type, args.exc_value, args.exc_traceback)
        )

    threading.excepthook = thread_crashed
    where = f"the console and {log_dir(environ) / LOG_FILE_NAME}" if len(handlers) > 1 else "the console"
    logger.info("Logging to %s at %s", where, logging.getLevelName(root.level))


# ------------------------------------------------------------------------------------------------------------ middleware


class RequestContextMiddleware:
    """Outermost. Gives the request an id, times it and writes its access line. Plain ASGI, so streamed files and the chat
    WebSocket pass through untouched."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        kind = scope["type"]
        if kind not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers") or [])
        request_id = request_id_from(headers.get(b"x-request-id", b"").decode("latin-1"))
        id_token = REQUEST_ID.set(request_id)
        actor_token = ACTOR.set({"id": "-"})
        try:
            if kind == "websocket":
                await self.app(scope, receive, send)
                return
            await self._http(scope, receive, send, request_id)
        finally:
            REQUEST_ID.reset(id_token)
            ACTOR.reset(actor_token)

    async def _http(self, scope, receive, send, request_id: str) -> None:
        started = time.perf_counter()
        status = {"code": 0}

        async def with_id(message):
            if message["type"] == "http.response.start":
                status["code"] = message["status"]
                MutableHeaders(scope=message)["X-Request-ID"] = request_id
            await send(message)

        try:
            await self.app(scope, receive, with_id)
        finally:
            ms = int((time.perf_counter() - started) * 1000)
            self._log(scope, status["code"], ms, request_id)

    @staticmethod
    def _log(scope, code: int, ms: int, request_id: str) -> None:
        path = scope.get("path", "")  # the path only: never the query string, which can carry a reset token
        method = scope.get("method", "?")
        slow = ms >= slow_threshold_ms()
        STATS.record(method, path, code, ms, slow, request_id)
        if not access_log_enabled():
            return
        if code >= 500 or code == 0:
            level = logging.ERROR
        elif slow:
            level = logging.WARNING
        elif path.startswith(_PLAIN_PATHS):
            level = logging.DEBUG
        else:
            level = logging.INFO
        access_log.log(level, "%s %s -> %s in %dms%s", method, path, code or "no response", ms, " (slow)" if slow else "")


class ErrorBoundaryMiddleware:
    """Innermost of ours, so that the answer to an unhandled error still passes through the CORS and security-header layers
    (the browser then shows the message instead of a network error)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = {"yes": False}

        async def watching(message):
            if message["type"] == "http.response.start":
                started["yes"] = True
            await send(message)

        try:
            await self.app(scope, receive, watching)
        except Exception:
            request_id = REQUEST_ID.get()
            logging.getLogger("orion.errors").exception("Unhandled error in %s %s", scope.get("method", "?"), scope.get("path", ""))
            if started["yes"]:
                raise  # the browser already has part of an answer; nothing honest can still be said
            body = json.dumps(
                {
                    "detail": f"Something went wrong on the server. Quote this reference if you report it: {request_id}",
                    "request_id": request_id,
                }
            ).encode()
            await send({"type": "http.response.start", "status": 500, "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
            await send({"type": "http.response.body", "body": body})
