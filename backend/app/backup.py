"""Encrypted PostgreSQL backups to Backblaze B2, taken only on the machine the bucket is meant for.

What a backup is: ``pg_dump`` of the four schemas (orion_ods, orion_dw, tally_ods, tally_dw), piped straight into
``age`` encryption and written as one file, so the plain dump never touches the disk. The file is then uploaded to the
bucket. The PC holds only the *public* key, so it can lock a backup but never unlock one; the private key lives with
the owner. See docs/backup.md for setup, retention, restore and the reasoning.

Which machine may back up: every bucket has a role, ``prod`` or ``dev`` (``ORION_BACKUP_BUCKET_ROLE``), and the machine
has to match it, or nothing runs. A ``prod`` bucket is written only when ``ORION_ENV=production`` and the database is
the production one; a ``dev`` bucket only when neither is true. Backups run as a read-only database role, never as the
application's own user, and the bucket key can only add files, never read, list or delete them.

Nothing here is reachable to download a backup: the API shows status only.
"""

from __future__ import annotations

import glob
import hashlib
import logging
import os
import platform
import re
import shutil
import subprocess
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Protocol

from app.config import ROOT, db_settings, env
from app.database import db_cursor

logger = logging.getLogger(__name__)

SCHEMAS = ("orion_ods", "orion_dw", "tally_ods", "tally_dw")
ROLES = ("dev", "prod")
DEFAULT_PROD_DB = "orion_prod"
ERROR_LIMIT = 800
TOC_BYTES = 4 * 1024 * 1024  # the archive's table of contents is at its start; this much is read to check it
CHUNK = 1024 * 1024
MAX_SINGLE_UPLOAD = 5 * 1024**3  # B2 takes up to 5 GB in one request; bigger needs multipart, which is not built yet
FIRST_CHECK_DELAY_SECONDS = 300
FORCE_AFTER_HOURS = 24
STALE_AFTER_INTERVALS = 3
ALERT_EVERY_HOURS = 6


class BackupError(RuntimeError):
    """A backup failed. The message is safe to show: secrets are removed from it."""


class BackupBlocked(BackupError):
    """Backups cannot run here. ``problems`` says why, in words a person can act on."""

    def __init__(self, problems: list[str]):
        super().__init__("; ".join(problems))
        self.problems = problems


class BackupBusy(BackupError):
    """A backup is already running."""


# --------------------------------------------------------------------------- configuration


@dataclass(frozen=True)
class BackupConfig:
    enabled: bool
    role: str
    endpoint: str
    region: str
    bucket: str
    key_id: str
    key: str
    recipients: tuple[str, ...]
    db_user: str
    db_password: str
    interval_hours: float
    alert_email: str
    app_env: str
    db_name: str
    db_host: str
    db_port: int
    app_db_user: str
    prod_db_name: str

    @property
    def secrets(self) -> tuple[str, ...]:
        return tuple(value for value in (self.key, self.key_id, self.db_password) if value)


def _flag(value: str) -> bool:
    return value.strip().lower() in ("1", "true", "yes", "on")


def load_config() -> BackupConfig:
    """The backup settings from the environment. Missing ones are empty; ``problems`` says what is wrong."""
    db = db_settings()
    try:
        interval = float(env("ORION_BACKUP_INTERVAL_HOURS", "24").strip() or "24")
    except ValueError:
        interval = 24.0
    return BackupConfig(
        enabled=_flag(env("ORION_BACKUP_ENABLED", "0")),
        role=env("ORION_BACKUP_BUCKET_ROLE", "").strip().lower(),
        endpoint=env("ORION_BACKUP_S3_ENDPOINT", "").strip().rstrip("/"),
        region=env("ORION_BACKUP_S3_REGION", "").strip(),
        bucket=env("ORION_BACKUP_BUCKET", "").strip(),
        key_id=env("ORION_BACKUP_KEY_ID", "").strip(),
        key=env("ORION_BACKUP_KEY", "").strip(),
        recipients=tuple(part.strip() for part in env("ORION_BACKUP_AGE_RECIPIENTS", "").split(",") if part.strip()),
        db_user=env("ORION_BACKUP_DB_USER", "").strip(),
        db_password=env("ORION_BACKUP_DB_PASSWORD", "").strip(),
        interval_hours=max(0.25, interval),
        alert_email=env("ORION_BACKUP_ALERT_EMAIL", "").strip(),
        app_env=env("ORION_ENV", "development").strip().lower(),
        db_name=str(db["database"]),
        db_host=str(db["host"]),
        db_port=int(db["port"]),
        app_db_user=str(db["user"]),
        prod_db_name=env("ORION_BACKUP_PROD_DB", DEFAULT_PROD_DB).strip() or DEFAULT_PROD_DB,
    )


def find_pg_tool(name: str) -> str | None:
    """pg_dump or pg_restore: ORION_PG_BIN, the PATH, then the usual install folders."""
    exe = name + (".exe" if platform.system() == "Windows" else "")
    folder = env("ORION_PG_BIN", "").strip()
    if folder and (Path(folder) / exe).is_file():
        return str(Path(folder) / exe)
    found = shutil.which(name)
    if found:
        return found
    patterns = [
        rf"C:\Program Files\PostgreSQL\*\bin\{exe}",
        f"/usr/lib/postgresql/*/bin/{exe}",
        f"/opt/homebrew/opt/postgresql@*/bin/{exe}",
        f"/Applications/Postgres.app/Contents/Versions/*/bin/{exe}",
    ]
    candidates = sorted((hit for pattern in patterns for hit in glob.glob(pattern)), reverse=True)
    return candidates[0] if candidates else None


def valid_recipient(text: str) -> bool:
    if not text.startswith("age1"):
        return False
    try:
        from pyrage import x25519

        x25519.Recipient.from_str(text)
        return True
    except Exception:
        return False


def problems(cfg: BackupConfig, *, check_tools: bool = True) -> list[str]:
    """Everything that stops a backup running on this machine. Empty means it may run.

    The first three are the "is this the right machine" rules; the rest are missing settings.
    """
    if cfg.role not in ROLES:
        return [f"ORION_BACKUP_BUCKET_ROLE must be 'dev' or 'prod', not {cfg.role!r}."]
    found: list[str] = []
    on_prod_machine = cfg.app_env == "production"
    on_prod_database = cfg.db_name == cfg.prod_db_name
    if cfg.role == "prod":
        if not on_prod_machine:
            found.append(f"This bucket is for production, but ORION_ENV is {cfg.app_env!r} here. Production backups run only on the production machine.")
        if not on_prod_database:
            found.append(f"This bucket is for production, but the database here is {cfg.db_name!r}, not {cfg.prod_db_name!r}.")
    else:
        if on_prod_machine:
            found.append("This is a production machine (ORION_ENV=production), so it must not use a dev bucket. Set ORION_BACKUP_BUCKET_ROLE=prod.")
        if on_prod_database:
            found.append(f"The database here is the production one ({cfg.prod_db_name!r}); a dev bucket must not hold production data.")
    name = cfg.bucket.lower()
    if cfg.role == "prod" and "dev" in name:
        found.append(f"The bucket {cfg.bucket!r} looks like a dev bucket but the role is prod.")
    if cfg.role == "dev" and "prod" in name:
        found.append(f"The bucket {cfg.bucket!r} looks like a production bucket but the role is dev.")
    if not cfg.enabled:
        return found + ["Backups are switched off (ORION_BACKUP_ENABLED is not 1)."]
    for label, value in (
        ("ORION_BACKUP_BUCKET", cfg.bucket),
        ("ORION_BACKUP_S3_ENDPOINT", cfg.endpoint),
        ("ORION_BACKUP_KEY_ID", cfg.key_id),
        ("ORION_BACKUP_KEY", cfg.key),
        ("ORION_BACKUP_DB_USER", cfg.db_user),
        ("ORION_BACKUP_DB_PASSWORD", cfg.db_password),
    ):
        if not value:
            found.append(f"{label} is not set.")
    if cfg.endpoint and not cfg.endpoint.startswith("https://"):
        found.append("ORION_BACKUP_S3_ENDPOINT must start with https://.")
    if not cfg.recipients:
        found.append("ORION_BACKUP_AGE_RECIPIENTS is empty. Backups are encrypted to a public key; without one nothing can be locked.")
    else:
        for recipient in cfg.recipients:
            if not valid_recipient(recipient):
                found.append("ORION_BACKUP_AGE_RECIPIENTS has a value that is not an age public key (it must start with age1). Never put the private key here.")
                break
    if cfg.db_user and cfg.db_user == cfg.app_db_user:
        found.append("Backups must run as a read-only role, not the application's own database user. Create orion_backup with deploy/create_backup_role.sql.")
    if check_tools:
        for tool in ("pg_dump", "pg_restore"):
            if not find_pg_tool(tool):
                found.append(f"{tool} was not found. Install the PostgreSQL client tools or set ORION_PG_BIN.")
    return found


def scrub(text: str, cfg: BackupConfig) -> str:
    """Remove anything secret from text before it is logged, stored or sent."""
    for secret in cfg.secrets:
        text = text.replace(secret, "***")
    return text


# --------------------------------------------------------------------------- stores


class Store(Protocol):
    def put(self, key: str, path: Path, size: int, sha256: str, md5: str, metadata: dict[str, str]) -> None: ...


class LocalStore:
    """A folder standing in for the bucket: used by tests and for trying the pipeline without a network."""

    def __init__(self, root: Path):
        self.root = root

    def put(self, key: str, path: Path, size: int, sha256: str, md5: str, metadata: dict[str, str]) -> None:
        target = self.root / key
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)


class S3Store:
    """Backblaze B2 through its S3-compatible API. Needs only permission to write: it never lists, reads or deletes."""

    def __init__(self, cfg: BackupConfig):
        import boto3
        from botocore.config import Config

        self.bucket = cfg.bucket
        self.client = boto3.client(
            "s3",
            endpoint_url=cfg.endpoint,
            region_name=cfg.region or None,
            aws_access_key_id=cfg.key_id,
            aws_secret_access_key=cfg.key,
            config=Config(
                signature_version="s3v4",
                s3={"addressing_style": "path"},
                retries={"max_attempts": 5, "mode": "standard"},
                connect_timeout=20,
                read_timeout=300,
                # B2 does not take the newer automatic checksum trailers; the ETag check below covers integrity.
                request_checksum_calculation="when_required",
                response_checksum_validation="when_required",
            ),
        )

    def put(self, key: str, path: Path, size: int, sha256: str, md5: str, metadata: dict[str, str]) -> None:
        if size > MAX_SINGLE_UPLOAD:
            raise BackupError(f"The backup is {size / 1024**3:.1f} GB, more than one upload can carry (5 GB). Multipart upload is not built yet.")
        with open(path, "rb") as body:
            reply = self.client.put_object(Bucket=self.bucket, Key=key, Body=body, ContentLength=size, Metadata=metadata)
        etag = str(reply.get("ETag", "")).strip('"')
        if etag and re.fullmatch(r"[0-9a-f]{32}", etag) and etag != md5:
            raise BackupError(f"The bucket stored {key} with checksum {etag}, but the file's is {md5}. The upload is not trustworthy.")


def make_store(cfg: BackupConfig) -> Store:
    return S3Store(cfg)


# --------------------------------------------------------------------------- the dump


class _Tee:
    """What pyrage reads from: the dump as it comes out of pg_dump, remembering the first bytes for the check."""

    def __init__(self, source):
        self.source = source
        self.head = bytearray()

    def read(self, size: int = -1) -> bytes:
        data = self.source.read(CHUNK if size is None or size < 0 else size)
        if len(self.head) < TOC_BYTES:
            self.head.extend(data[: TOC_BYTES - len(self.head)])
        return data


class _Sink:
    """What pyrage writes to: the encrypted file, with its size and checksums worked out as it goes."""

    def __init__(self, handle):
        self.handle = handle
        self.sha256 = hashlib.sha256()
        self.md5 = hashlib.md5()  # the bucket's ETag, to compare after upload; not used for anything secret
        self.size = 0

    def write(self, data: bytes) -> int:
        self.handle.write(data)
        self.sha256.update(data)
        self.md5.update(data)
        self.size += len(data)
        return len(data)

    def flush(self) -> None:
        self.handle.flush()


@dataclass
class Dump:
    path: Path
    size: int
    sha256: str
    md5: str


def check_archive_head(head: bytes, cfg: BackupConfig) -> None:
    """Confirm, without decrypting anything, that the dump is a PostgreSQL archive that covers all four schemas."""
    tool = find_pg_tool("pg_restore")
    if not tool:
        raise BackupError("pg_restore was not found, so the dump could not be checked.")
    listing = subprocess.run([tool, "--list"], input=bytes(head), capture_output=True, timeout=120)
    text = listing.stdout.decode("utf-8", "replace")
    if "Archive created at" not in text:
        raise BackupError("The dump does not look like a PostgreSQL archive: its table of contents could not be read.")
    missing = [s for s in SCHEMAS if not re.search(rf"\bSCHEMA - {re.escape(s)}\b", text)]
    if missing:
        raise BackupError(f"The dump is missing the schema(s): {', '.join(missing)}.")


def dump_encrypted(cfg: BackupConfig, directory: Path) -> Dump:
    """pg_dump of the four schemas, encrypted as it is written. Returns the encrypted file."""
    import pyrage
    from pyrage import x25519

    tool = find_pg_tool("pg_dump")
    if not tool:
        raise BackupError("pg_dump was not found.")
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{uuid.uuid4().hex}.part"
    command = [
        tool, "-h", cfg.db_host, "-p", str(cfg.db_port), "-U", cfg.db_user, "-d", cfg.db_name,
        "-Fc", "--no-owner", "--no-acl", *[arg for schema in SCHEMAS for arg in ("-n", schema)],
    ]
    child_env = {**os.environ, "PGPASSWORD": cfg.db_password, "PGCONNECT_TIMEOUT": "20", "PGOPTIONS": "-c default_transaction_read_only=on"}
    recipients = [x25519.Recipient.from_str(r) for r in cfg.recipients]
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=child_env)
    stderr_chunks: list[bytes] = []
    drain = threading.Thread(target=lambda: stderr_chunks.append(process.stderr.read()), daemon=True)
    drain.start()
    try:
        tee = _Tee(process.stdout)
        with open(path, "wb") as handle:
            sink = _Sink(handle)
            pyrage.encrypt_io(tee, sink, recipients)
        returncode = process.wait()
        drain.join(timeout=10)
        complaint = scrub(b"".join(stderr_chunks).decode("utf-8", "replace").strip(), cfg)
        if returncode != 0:
            raise BackupError(f"pg_dump failed (exit {returncode}): {complaint[:ERROR_LIMIT]}")
        check_archive_head(bytes(tee.head), cfg)
        return Dump(path=path, size=sink.size, sha256=sink.sha256.hexdigest(), md5=sink.md5.hexdigest())
    except BaseException:
        process.kill()
        path.unlink(missing_ok=True)
        raise
    finally:
        process.stdout.close()


# --------------------------------------------------------------------------- what is kept, and for how long


def object_key(prefix: str, cfg: BackupConfig, when: datetime, sha256: str) -> str:
    """Where a backup goes. The prefix is what the bucket's lifecycle rules keep for different lengths of time."""
    stamp = when.strftime("%Y%m%dT%H%M%SZ")
    return f"{prefix}/{cfg.db_name}/{when:%Y}/{when:%m}/{cfg.db_name}-{stamp}-{sha256[:8]}.dump.age"


def prefixes_for(already_today: bool, already_this_month: bool) -> list[str]:
    """The first backup of a day is kept as a daily, the first of a month also as a monthly. A further one the same
    day (a manual run, say) goes under ``recent``, which the bucket's lifecycle rules keep only briefly."""
    chosen = ["recent"] if already_today else ["daily"]
    if not already_this_month:
        chosen.append("monthly")
    return chosen


def data_fingerprint(cur) -> str:
    """How much the four schemas have been written to. Differs after any insert, update or delete, and after a server
    crash (which resets the counters), so it can only err towards taking a backup. The backup log itself is left out."""
    cur.execute(
        """
        SELECT COALESCE(SUM(n_tup_ins + n_tup_upd + n_tup_del), 0), COUNT(*)
          FROM pg_stat_all_tables
         WHERE schemaname = ANY(%s) AND NOT (schemaname = 'orion_ods' AND relname = 'backup_run')
        """,
        (list(SCHEMAS),),
    )
    writes, tables = cur.fetchone()
    return hashlib.sha1(f"{writes}:{tables}".encode()).hexdigest()


# --------------------------------------------------------------------------- running one


_lock = threading.Lock()
_state: dict[str, Any] = {"last_checked": None, "next_run": None, "alerted_at": None, "stale_alerted_at": None}


def _temp_dir() -> Path:
    return ROOT / "data" / "backup-tmp"


def _record_start(cfg: BackupConfig, trigger: str, user_id: int | None, fingerprint: str) -> int:
    with db_cursor(commit=True) as cur:
        cur.execute(
            """
            INSERT INTO orion_ods.backup_run
                (trigger, started_by, bucket_role, bucket, db_name, schemas, source_fingerprint, runner_host, app_env)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id
            """,
            (trigger, user_id, cfg.role, cfg.bucket, cfg.db_name, list(SCHEMAS), fingerprint, platform.node(), cfg.app_env),
        )
        return cur.fetchone()[0]


def _record_finish(run_id: int, started: datetime, status: str, *, error: str | None = None, dump: Dump | None = None,
                   prefixes: list[str] | None = None, keys: list[str] | None = None) -> None:
    with db_cursor(commit=True) as cur:
        cur.execute(
            """
            UPDATE orion_ods.backup_run
               SET status = %s, finished_timestamp = CURRENT_TIMESTAMP, duration_ms = %s, error = %s,
                   size_bytes = %s, sha256 = %s, prefixes = %s, object_keys = %s
             WHERE id = %s
            """,
            (
                status, round((datetime.now(timezone.utc) - started).total_seconds() * 1000), error,
                dump.size if dump else None, dump.sha256 if dump else None, prefixes, keys, run_id,
            ),
        )


def _already_kept(cur, prefix: str, unit: str) -> bool:
    cur.execute(
        f"""
        SELECT EXISTS (
            SELECT 1 FROM orion_ods.backup_run
             WHERE status = 'succeeded' AND %s = ANY(prefixes)
               AND date_trunc('{unit}', started_timestamp) = date_trunc('{unit}', CURRENT_TIMESTAMP)
        )
        """,
        (prefix,),
    )
    return bool(cur.fetchone()[0])


def _last_success() -> dict[str, Any] | None:
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT id, finished_timestamp, source_fingerprint, size_bytes
              FROM orion_ods.backup_run WHERE status = 'succeeded' ORDER BY finished_timestamp DESC, id DESC LIMIT 1
            """
        )
        row = cur.fetchone()
    return dict(zip(("id", "finished", "fingerprint", "size"), row)) if row else None


def run_backup(trigger: str = "manual", user_id: int | None = None, *, force: bool = False,
               store: Store | None = None, directory: Path | None = None) -> int | None:
    """Take one backup. Returns the run id, or None if a scheduled check found nothing had changed.

    Raises BackupBlocked when this machine may not back up, BackupBusy if one is running, and BackupError if it fails
    (the failure is also recorded, with secrets removed).
    """
    cfg = load_config()
    stop = problems(cfg, check_tools=store is None)
    if stop:
        raise BackupBlocked(stop)
    if not _lock.acquire(blocking=False):
        raise BackupBusy("A backup is already running.")
    run_id: int | None = None
    dump: Dump | None = None
    started = datetime.now(timezone.utc)
    try:
        with db_cursor() as cur:
            fingerprint = data_fingerprint(cur)
        _state["last_checked"] = started
        previous = _last_success()
        # Skipping an unchanged database only makes sense when backups are more often than the daily one that is
        # always taken; at one a day every check takes a backup.
        if trigger == "scheduled" and not force and previous and cfg.interval_hours < FORCE_AFTER_HOURS:
            age = started - previous["finished"].astimezone(timezone.utc)
            if previous["fingerprint"] == fingerprint and age < timedelta(hours=FORCE_AFTER_HOURS):
                return None
        run_id = _record_start(cfg, trigger, user_id, fingerprint)
        folder = directory or _temp_dir()
        dump = dump_encrypted(cfg, folder)
        with db_cursor() as cur:
            chosen = prefixes_for(_already_kept(cur, "daily", "day"), _already_kept(cur, "monthly", "month"))
        target = store or make_store(cfg)
        keys: list[str] = []
        meta = {"sha256": dump.sha256, "orion-env": cfg.app_env, "orion-db": cfg.db_name, "orion-role": cfg.role}
        for prefix in chosen:
            key = object_key(prefix, cfg, started, dump.sha256)
            target.put(key, dump.path, dump.size, dump.sha256, dump.md5, meta)
            keys.append(key)
        _record_finish(run_id, started, "succeeded", dump=dump, prefixes=chosen, keys=keys)
        logger.info("Backup %s done: %s bytes to %s (%s)", run_id, dump.size, cfg.bucket, ", ".join(chosen))
        return run_id
    except BaseException as exc:
        message = scrub(str(exc) or type(exc).__name__, cfg)[:ERROR_LIMIT]
        if run_id is not None:
            try:
                _record_finish(run_id, started, "failed", error=message, dump=dump)
            except Exception:
                logger.exception("Could not record the failure of backup %s", run_id)
        logger.error("Backup failed: %s", message)
        if isinstance(exc, BackupError):
            raise BackupError(message) from None
        raise BackupError(message) from None
    finally:
        if dump is not None:
            dump.path.unlink(missing_ok=True)
        _lock.release()


# --------------------------------------------------------------------------- status and alerts


def _iso(value: Any) -> str | None:
    return value.isoformat() if hasattr(value, "isoformat") else None


def status() -> dict[str, Any]:
    """What the ETL page shows. Never a key, an endpoint or any data from a dump."""
    cfg = load_config()
    stop = problems(cfg)
    state = "ready" if not stop else ("off" if not cfg.enabled else "blocked")
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT id, trigger, status, started_timestamp, finished_timestamp, duration_ms, size_bytes, prefixes, error
              FROM orion_ods.backup_run ORDER BY started_timestamp DESC, id DESC LIMIT 10
            """
        )
        names = [col.name for col in cur.description]
        recent = [{n: _iso(v) or v for n, v in zip(names, row)} for row in cur.fetchall()]
    last_ok = next((r for r in recent if r["status"] == "succeeded"), None)
    if last_ok is None:
        found = _last_success()
        last_ok = {"id": found["id"], "finished_timestamp": _iso(found["finished"]), "size_bytes": found["size"]} if found else None
    stale = False
    if state == "ready":
        limit = timedelta(hours=cfg.interval_hours * STALE_AFTER_INTERVALS)
        finished = datetime.fromisoformat(last_ok["finished_timestamp"]) if last_ok and last_ok.get("finished_timestamp") else None
        stale = finished is None or datetime.now(timezone.utc) - finished.astimezone(timezone.utc) > limit
    return {
        "state": state,
        "problems": stop,
        "role": cfg.role or None,
        "bucket": cfg.bucket or None,
        "interval_hours": cfg.interval_hours,
        "running": _lock.locked(),
        "last_success": last_ok,
        "last_checked": _iso(_state["last_checked"]),
        "next_run": _iso(_state["next_run"]),
        "stale": stale,
        "recent": recent,
    }


def _alert(subject: str, body: str, cfg: BackupConfig) -> None:
    if not cfg.alert_email:
        return
    try:
        from app.mail import send_mail

        send_mail(cfg.alert_email, subject, scrub(body, cfg))
    except Exception:
        logger.exception("Could not send the backup alert")


def alert_if_needed(cfg: BackupConfig, failure: str | None) -> None:
    """Email once per few hours while backups are failing, and once a day while the latest one is too old."""
    now = datetime.now(timezone.utc)
    if failure and (not _state["alerted_at"] or now - _state["alerted_at"] > timedelta(hours=ALERT_EVERY_HOURS)):
        _state["alerted_at"] = now
        _alert(f"Orion backup failed ({cfg.role})", f"The {cfg.role} database backup to {cfg.bucket} failed:\n\n{failure}\n", cfg)
    if not failure:
        _state["alerted_at"] = None
    current = status()
    if current["stale"] and (not _state["stale_alerted_at"] or now - _state["stale_alerted_at"] > timedelta(hours=24)):
        _state["stale_alerted_at"] = now
        _alert(
            f"Orion backup is out of date ({cfg.role})",
            f"No {cfg.role} backup to {cfg.bucket} has succeeded in the last {cfg.interval_hours * STALE_AFTER_INTERVALS:g} hours.",
            cfg,
        )


# --------------------------------------------------------------------------- the schedule


def _wait(stop: threading.Event, seconds: float) -> bool:
    _state["next_run"] = datetime.now(timezone.utc) + timedelta(seconds=seconds)
    try:
        return stop.wait(seconds)
    finally:
        _state["next_run"] = None


def start(stop: threading.Event) -> threading.Thread | None:
    """Start the schedule when this machine may back up; say why in the log when it may not."""
    cfg = load_config()
    if not cfg.enabled:
        logger.info("Backups are off (ORION_BACKUP_ENABLED is not 1)")
        return None
    stop_reasons = problems(cfg)
    if stop_reasons:
        logger.warning("Backups will not run on this machine: %s", " ".join(stop_reasons))
        return None

    def loop() -> None:
        # After a restart, wait out what is left of the interval rather than taking a backup at once.
        first = FIRST_CHECK_DELAY_SECONDS
        try:
            last = _last_success()
            if last and last["finished"]:
                gone = (datetime.now(timezone.utc) - last["finished"].astimezone(timezone.utc)).total_seconds()
                first = max(first, cfg.interval_hours * 3600 - gone)
        except Exception:
            logger.exception("Could not read the last backup")
        if _wait(stop, first):
            return
        while True:
            current = load_config()
            failure: str | None = None
            try:
                run_backup("scheduled")
            except BackupBusy:
                pass
            except BackupBlocked as exc:
                failure = str(exc)
            except BackupError as exc:
                failure = str(exc)
            except Exception as exc:  # the schedule must outlive any one failure
                logger.exception("Unexpected backup error")
                failure = scrub(str(exc), current)
            try:
                alert_if_needed(current, failure)
            except Exception:
                logger.exception("Backup alert check failed")
            if _wait(stop, current.interval_hours * 3600):
                return

    thread = threading.Thread(target=loop, name="orion-backup", daemon=True)
    thread.start()
    logger.info("Backups every %g hours to %s (%s)", cfg.interval_hours, cfg.bucket, cfg.role)
    return thread


def close_interrupted_runs() -> None:
    """A backup still marked running when the API starts was cut off by a restart."""
    try:
        with db_cursor(commit=True) as cur:
            cur.execute(
                """
                UPDATE orion_ods.backup_run
                   SET status = 'failed', finished_timestamp = CURRENT_TIMESTAMP, error = 'Interrupted by a restart'
                 WHERE status = 'running'
                """
            )
    except Exception:
        logger.exception("Could not close interrupted backups")
