import logging
import re
import threading
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from app.column_filters import FilterError
from app.auth import ensure_default_admin, ensure_user_profile_columns
from app.chat import ensure_chat_tables
from app.signup import ensure_signup_table
from app.entities import ENTITIES
from app import backup, documents_filing, dw_auto, etl, pdf_tools, task_templates, tenders
from app.request_limits import RequestSizeLimitMiddleware
from app import migrate
from app.dw_sync import REFRESH_ORDER
from app.avatars import avatar_response
from app.dependencies import get_current_user
from app import database, deploy_tools, health
from app.frontend_serving import mount_frontend
from app.observability import ErrorBoundaryMiddleware, RequestContextMiddleware, configure_logging
from app.security_headers import SecurityHeadersMiddleware, api_docs_enabled, cors_options
from app.startup_checks import is_production, verify_production, warn_if_development_defaults
from app.routers import (
    auth_router,
    dashboard_router,
    dw_router,
    entities_router,
    location_router,
    messages_router,
    support_router,
    tally_dw_router,
    tally_dashboard_router,
    tally_router,
    users_router,
    bank_router,
    payables_router,
    payroll_router,
    billing_router,
    tds_router,
    clients_router,
    cases_router,
    employees_router,
    gst_router,
    statutory_router,
    credit_notes_router,
    tasks_router,
    etl_router,
    backup_router,
    letterhead_router,
    pdf_tools_router,
    employee_documents_router,
    emd_documents_router,
    attendance_router,
    followups_router,
    documents_router,
    gdrive_router,
    sql_router,
    tenders_router,
    ai_router,
    health_router,
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    configure_logging()  # first, so that even a refusal to start (the next line) is in the file
    verify_production()  # before anything touches the database: a production server with development secrets must not start
    deploy_tools.warm()  # which commit this process is running, for /api/health/version
    warn_if_development_defaults()
    ensure_user_profile_columns()
    ensure_chat_tables()
    ensure_signup_table()
    # Every schema step, in order, each result recorded in orion_ods.schema_migrations. In production a failed step refuses the start
    # (deploy.ps1 has already run the same thing before stopping the old server, so this is the second chance, not the first);
    # elsewhere it is logged and /api/health/ready and the System page say the schema is not right.
    migrate.apply_at_startup(production=is_production())
    ensure_default_admin()
    logger.info("ODS entities ready: %s", ", ".join(ENTITIES))
    logger.info("DW tables ready: %s", ", ".join(REFRESH_ORDER))
    database.warm_pool()  # a few connections ready before the first request, so it does not pay to open them
    etl.close_interrupted_runs()
    stop_autoload = threading.Event()
    dw_auto.start(stop_autoload)
    backup.close_interrupted_runs()
    backup.start(stop_autoload)
    tenders.start(stop_autoload)
    documents_filing.start(stop_autoload)
    task_templates.start(stop_autoload)
    yield
    stop_autoload.set()
    database.close_pool()


_docs_on = api_docs_enabled()  # off in production: they list every route and let anyone try them
app = FastAPI(
    title="Orion API",
    version="2.0.0",
    lifespan=lifespan,
    docs_url="/docs" if _docs_on else None,
    redoc_url="/redoc" if _docs_on else None,
    openapi_url="/openapi.json" if _docs_on else None,
)

# Each add_middleware wraps the ones before it, so the LAST is outermost: a request meets the request-id layer first, and an
# unhandled error is caught innermost, so its 500 still passes through the CORS and security-header layers on its way out.
@app.exception_handler(FilterError)
async def bad_column_filter(_request, exc: FilterError):
    """A column filter that names a column that is not there, or asks of it what it cannot answer: the person is told, it is not a fault."""
    return JSONResponse({"detail": str(exc)}, status_code=400)


@app.exception_handler(database.PoolTimeout)
async def database_busy(_request, exc: database.PoolTimeout):
    """Every database connection was in use for the whole wait: say so, and say when to try again, instead of a 500."""
    logging.getLogger("orion.errors").warning("Refused a request: %s", exc)
    return JSONResponse(
        {"detail": "The server is busy right now. Try again in a few seconds."},
        status_code=503,
        headers={"Retry-After": "5"},
    )


# Innermost, so what it raises while an upload is being read reaches it and not the catch-all below. The PDF tools take whole files in one
# request: nothing bigger than their own limit (and a little for the form) is accepted.
app.add_middleware(RequestSizeLimitMiddleware, limits={"/api/pdf-tools": pdf_tools.MAX_TOTAL_BYTES + 8 * 1024 * 1024})
app.add_middleware(ErrorBoundaryMiddleware)
app.add_middleware(SecurityHeadersMiddleware)

app.add_middleware(CORSMiddleware, expose_headers=["X-Request-ID", "X-Orion-Pages", "X-Orion-Result"], **cors_options())
# Compress what is worth it (the app's scripts, JSON lists): about a third of the size over a slow link. Server-sent events and
# already-compressed files (images, PDFs inside zips) are left alone by Starlette's defaults. Inside the request-id layer, outside
# CORS and the security headers, which set headers on the uncompressed answer.
app.add_middleware(GZipMiddleware, minimum_size=1024, compresslevel=5)
app.add_middleware(RequestContextMiddleware)

app.include_router(auth_router.router, prefix="/api")
app.include_router(users_router.router, prefix="/api")
app.include_router(entities_router.router, prefix="/api")
app.include_router(dw_router.router, prefix="/api")
app.include_router(dashboard_router.router, prefix="/api")
app.include_router(location_router.router, prefix="/api")
app.include_router(messages_router.router, prefix="/api")
app.include_router(support_router.router, prefix="/api")
app.include_router(tally_dw_router.router, prefix="/api")
app.include_router(tally_dashboard_router.router, prefix="/api")
app.include_router(tally_router.router, prefix="/api")
app.include_router(billing_router.router, prefix="/api")
app.include_router(tds_router.router, prefix="/api")
app.include_router(clients_router.router, prefix="/api")
app.include_router(cases_router.router, prefix="/api")
app.include_router(employees_router.router, prefix="/api")
app.include_router(gst_router.router, prefix="/api")
app.include_router(statutory_router.router, prefix="/api")
app.include_router(credit_notes_router.router, prefix="/api")
app.include_router(tasks_router.router, prefix="/api")
app.include_router(bank_router.router, prefix="/api")
app.include_router(payables_router.router, prefix="/api")
app.include_router(payroll_router.router, prefix="/api")
app.include_router(etl_router.router, prefix="/api")
app.include_router(backup_router.router, prefix="/api")
app.include_router(letterhead_router.router, prefix="/api")
app.include_router(pdf_tools_router.router, prefix="/api")
app.include_router(employee_documents_router.router, prefix="/api")
app.include_router(emd_documents_router.router, prefix="/api")
app.include_router(followups_router.router, prefix="/api")
app.include_router(attendance_router.router, prefix="/api")
app.include_router(documents_router.router, prefix="/api")
app.include_router(gdrive_router.router, prefix="/api")
app.include_router(sql_router.router, prefix="/api")
app.include_router(tenders_router.router, prefix="/api")
app.include_router(ai_router.router, prefix="/api")
app.include_router(health_router.router, prefix="/api")


@app.get("/api/health")
def health_alive():
    """The process is up. Unchanged on purpose: the desktop launchers poll it and the docs say what it returns."""
    return {"status": "ok"}


@app.get("/api/health/version")
def health_version():
    """Which version is running: the commit, and the ref and time it was deployed. Public: a deploy's smoke test asks it, to be sure
    the NEW code answered and not the old server that was meant to be replaced."""
    info = deploy_tools.release_info()
    return {key: info.get(key) for key in ("commit", "ref", "previous", "deployed")}


@app.get("/api/health/ready")
def health_ready():
    """The process can reach its database (503 when it cannot). Public: it says only up or down."""
    ok, body = health.ready()
    return JSONResponse(body, status_code=200 if ok else 503)


@app.get("/api/media/avatars/{filename}")
def media_avatar(filename: str, _user=Depends(get_current_user)):
    """A profile photo, for signed-in people only (it used to be a public static folder, so anyone who guessed a user number could
    fetch a colleague's photo). The address keeps its old shape, ``/api/media/avatars/12.jpg?v=3``, so stored links still work."""
    match = re.fullmatch(r"(\d{1,9})\.(?:jpg|jpeg|png|webp)", filename)
    if not match:
        raise HTTPException(status_code=404)
    return avatar_response(int(match.group(1)))


# Production: serve the built React app from this process (same origin as /api).
# Dev keeps using the Vite dev server, so this is off unless ORION_SERVE_FRONTEND=1.
if os.environ.get("ORION_SERVE_FRONTEND") == "1":
    if not mount_frontend(app, Path(__file__).resolve().parents[2] / "frontend" / "dist"):
        logger.warning("ORION_SERVE_FRONTEND=1 but frontend/dist is missing; run npm run build")
