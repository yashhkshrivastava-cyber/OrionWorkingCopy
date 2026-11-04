"""The parts of a deploy that are better as code than as PowerShell: a safety dump, a smoke test, and a record of what is running.

``deploy.ps1`` calls these, from ``backend`` with the production virtualenv's Python:

    python -m app.deploy_tools backup --dir C:\\orion-backups --label v1.2.3 [--keep 5]
    python -m app.deploy_tools smoke  --url http://127.0.0.1:8100 --commit <sha> [--timeout 120]
    python -m app.deploy_tools release --ref v1.2.3 --commit <sha> --previous <sha>

Each exits 0 on success and 1 on failure, with a plain line saying what happened.

* **backup** takes a ``pg_dump`` of the whole database in PostgreSQL's custom format BEFORE the deploy changes anything, checks that it
  can be read back (``pg_restore --list`` shows the four schemas), and keeps the newest few. It is the way back if a release damages
  data; rolling the code back does not undo data. It is not encrypted and sits on this PC, so it is a safety net for a deploy, not
  a backup (docs/backup.md is the backup).
* **smoke** waits for the new server, then proves it is the NEW code (the commit it reports is the one deployed), that its database
  and schema are fine (``/api/health/ready``), that the built UI and its script are served, and that the security headers are on.
  A server that never came up, or that is still the old one, fails it.
* **release** writes ``data/release.json``, which ``/api/health/version`` reads.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from app.config import ROOT, db_settings

RELEASE_FILE = ROOT / "data" / "release.json"
DUMP_PATTERN = "orion_{db}_before_*.dump"
SCHEMAS = ("orion_ods", "orion_dw", "tally_ods", "tally_dw")
MIN_FREE_FACTOR = 1.5  # the dump needs at most the database's size; ask for half as much again


# ------------------------------------------------------------------------------------------------------------- backup


def safe_label(label: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", label).strip("-.")[:60] or "release"


def dump_name(db: str, label: str, now: Optional[datetime] = None) -> str:
    stamp = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
    return f"orion_{db}_before_{safe_label(label)}_{stamp}.dump"


def prune(directory: Path, db: str, keep: int) -> list[Path]:
    """Delete all but the newest ``keep`` safety dumps of this database. Never touches anything else in the folder."""
    dumps = sorted(directory.glob(DUMP_PATTERN.format(db=db)), key=lambda p: p.stat().st_mtime, reverse=True)
    gone = dumps[max(keep, 1):]
    for path in gone:
        path.unlink()
    return gone


def listing_covers_the_schemas(text: str) -> Optional[str]:
    """None when a ``pg_restore --list`` shows a PostgreSQL archive that holds every schema; otherwise what is wrong."""
    if "Archive created at" not in text:
        return "it does not read back as a PostgreSQL archive"
    missing = [name for name in SCHEMAS if not re.search(rf"\bSCHEMA - {re.escape(name)}\b", text)]
    return f"it is missing the schema(s) {', '.join(missing)}" if missing else None


def backup(directory: Path, label: str, keep: int = 5) -> Path:
    from app import backup as backup_module

    settings = db_settings()
    pg_dump, pg_restore = backup_module.find_pg_tool("pg_dump"), backup_module.find_pg_tool("pg_restore")
    if not pg_dump or not pg_restore:
        raise RuntimeError("pg_dump / pg_restore were not found. Install the PostgreSQL client tools or set ORION_PG_BIN.")
    directory.mkdir(parents=True, exist_ok=True)

    size = _database_size(settings)
    free = shutil.disk_usage(directory).free
    if size and free < size * MIN_FREE_FACTOR:
        raise RuntimeError(f"Not enough free disk space in {directory} for a dump: {free // 2**20} MB free, the database is {size // 2**20} MB.")

    target = directory / dump_name(settings["database"], label)
    environment = {**os.environ, "PGPASSWORD": str(settings["password"]), "PGCONNECT_TIMEOUT": "20"}
    command = [pg_dump, "-w", "-h", str(settings["host"]), "-p", str(settings["port"]), "-U", str(settings["user"]), "-d", str(settings["database"]), "-F", "c", "-f", str(target)]
    done = subprocess.run(command, env=environment, capture_output=True, timeout=3600)
    if done.returncode != 0:
        target.unlink(missing_ok=True)
        raise RuntimeError(f"pg_dump failed (exit {done.returncode}): {done.stderr.decode('utf-8', 'replace').strip()[:400]}")
    if not target.is_file() or target.stat().st_size == 0:
        raise RuntimeError("pg_dump produced no file.")
    check = subprocess.run([pg_restore, "--list", str(target)], capture_output=True, timeout=300)
    problem = listing_covers_the_schemas(check.stdout.decode("utf-8", "replace")) if check.returncode == 0 else "pg_restore could not read it"
    if problem:
        target.unlink(missing_ok=True)
        raise RuntimeError(f"The dump was made but cannot be trusted: {problem}.")
    return target


def _database_size(settings: dict) -> Optional[int]:
    try:
        from app.database import raw_connection

        with raw_connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT pg_database_size(current_database())")
            return int(cur.fetchone()[0])
    except Exception:  # noqa: BLE001 - if it cannot be asked, pg_dump will say what is wrong
        return None


# -------------------------------------------------------------------------------------------------------------- smoke


class Check:
    def __init__(self, name: str, ok: bool, detail: str = ""):
        self.name, self.ok, self.detail = name, ok, detail


def fetch(url: str, timeout: float = 10.0) -> tuple[int, dict, bytes]:
    """(status, headers lower-cased, body). A connection that fails is status 0."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return response.status, {k.lower(): v for k, v in response.headers.items()}, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, {k.lower(): v for k, v in exc.headers.items()}, exc.read()
    except Exception:  # noqa: BLE001
        return 0, {}, b""


def wait_until_up(base: str, seconds: float, sleep=time.sleep, clock=time.monotonic) -> bool:
    deadline = clock() + seconds
    while True:
        status, _headers, _body = fetch(base + "/api/health", timeout=3)
        if status == 200:
            return True
        if clock() >= deadline:
            return False
        sleep(1.0)


def smoke(base: str, commit: Optional[str], seconds: float = 120.0) -> list[Check]:
    base = base.rstrip("/")
    if not wait_until_up(base, seconds):
        return [Check("server answers", False, f"nothing answered /api/health at {base} within {int(seconds)} seconds")]
    checks = [Check("server answers", True)]

    status, _h, body = fetch(base + "/api/health")
    checks.append(Check("liveness unchanged", status == 200 and _json(body) == {"status": "ok"}, f"{status} {body[:80]!r}"))

    status, _h, body = fetch(base + "/api/health/ready")
    answer = _json(body)
    checks.append(Check("database and schema ready", status == 200, f"{status} {answer}"))

    status, _h, body = fetch(base + "/api/health/version")
    running = (_json(body) or {}).get("commit") if status == 200 else None
    if commit:
        checks.append(Check("it is the new code", bool(running) and str(running).startswith(commit[:12]), f"running {running}, expected {commit[:12]}"))
    else:
        checks.append(Check("version reported", status == 200 and bool(running), f"{status}"))

    status, headers, body = fetch(base + "/")
    html = body.decode("utf-8", "replace")
    checks.append(Check("the web app is served", status == 200 and 'id="root"' in html, f"{status}"))
    scripts = re.findall(r'<script[^>]+src="(/assets/[^"]+\.js)"', html)
    if scripts:
        code, _h, js = fetch(base + scripts[0])
        checks.append(Check("its script loads", code == 200 and len(js) > 1000, f"{scripts[0]} -> {code}, {len(js)} bytes"))
    else:
        checks.append(Check("its script loads", False, "index.html names no /assets script: the frontend was not built or not served"))

    status, headers, _body = fetch(base + "/api/health")
    protected = bool(headers.get("content-security-policy")) and bool(headers.get("x-request-id"))
    checks.append(Check("security headers and request id are on", protected, "missing" if not protected else ""))

    status, _h, body = fetch(base + "/api/auth/config")
    checks.append(Check("a public page of the API answers", status == 200 and "roles" in (_json(body) or {}), f"{status}"))
    return checks


def _json(body: bytes):
    try:
        return json.loads(body.decode("utf-8"))
    except Exception:  # noqa: BLE001
        return None


# ------------------------------------------------------------------------------------------------------------- release


def write_release(ref: str, commit: str, previous: str, path: Path = RELEASE_FILE) -> dict:
    record = {"ref": ref, "commit": commit, "previous": previous, "deployed": datetime.now(timezone.utc).isoformat()}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2), encoding="utf-8")
    return record


_release_cache: Optional[tuple] = None  # (modification time of release.json or None, what it said)


_started_commit: Optional[str] = None
_started_looked = False


def warm() -> None:
    """Note which commit this process is running. Called as the server starts: the folder's HEAD can change later (a deploy with
    -NoRestart checks the new version out under a server still running the old one), and the old server must keep saying what it is."""
    global _started_commit, _started_looked
    if _started_looked:
        return
    _started_looked = True
    try:
        done = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, timeout=5)
        if done.returncode == 0:
            _started_commit = done.stdout.decode().strip() or None
    except Exception:  # noqa: BLE001, S110 - no git on this machine: the record is all there is
        pass


def release_info() -> dict:
    """What is running. The commit is the one this process started on (git), never the record's: the record is written after the
    smoke test, so it still names the PREVIOUS release while the new one is being checked. The record adds the ref, the previous
    commit and the time, only when it is about that same commit. Without git, the record alone."""
    global _release_cache
    warm()
    # Cached, but keyed on the record's modification time: the record is written AFTER the smoke test has asked for the version, and
    # a cache that ignored that kept answering from git until the next restart.
    try:
        stamp: Optional[float] = RELEASE_FILE.stat().st_mtime if RELEASE_FILE.is_file() else None
    except OSError:
        stamp = None
    if _release_cache is not None and _release_cache[0] == stamp:
        return _release_cache[1]
    info: dict = {"commit": None, "ref": None, "previous": None, "deployed": None, "source": "unknown"}
    try:
        record = json.loads(RELEASE_FILE.read_text(encoding="utf-8")) if RELEASE_FILE.is_file() else None
        if _started_commit:
            info = {**info, "commit": _started_commit, "source": "git"}
            if isinstance(record, dict) and record.get("commit") == _started_commit:
                info = {**info, **record, "source": "deploy"}
        elif isinstance(record, dict):
            info = {**info, **record, "source": "deploy"}
    except Exception:  # noqa: BLE001, S110 - not knowing the version must never take a health check down
        pass
    _release_cache = (stamp, info)
    return info


# ---------------------------------------------------------------------------------------------------- command line


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.deploy_tools")
    sub = parser.add_subparsers(dest="command", required=True)
    b = sub.add_parser("backup")
    b.add_argument("--dir", required=True)
    b.add_argument("--label", default="release")
    b.add_argument("--keep", type=int, default=5)
    s = sub.add_parser("smoke")
    s.add_argument("--url", required=True)
    s.add_argument("--commit", default="")
    s.add_argument("--timeout", type=float, default=120.0)
    r = sub.add_parser("release")
    r.add_argument("--ref", required=True)
    r.add_argument("--commit", required=True)
    r.add_argument("--previous", default="")
    args = parser.parse_args(argv)

    if args.command == "backup":
        try:
            path = backup(Path(args.dir), args.label, args.keep)
        except Exception as exc:  # noqa: BLE001
            print(f"BACKUP FAILED: {exc}")
            return 1
        gone = prune(Path(args.dir), db_settings()["database"], args.keep)
        print(f"Safety dump: {path} ({path.stat().st_size // 1024} KB, readable). Kept the newest {args.keep}; removed {len(gone)} older.")
        return 0
    if args.command == "smoke":
        checks = smoke(args.url, args.commit or None, args.timeout)
        for check in checks:
            print(f"  {'ok  ' if check.ok else 'FAIL'}  {check.name}" + (f"  ({check.detail})" if check.detail and not check.ok else ""))
        failed = [c for c in checks if not c.ok]
        print("Smoke test passed." if not failed else f"Smoke test FAILED: {len(failed)} of {len(checks)} checks.")
        return 1 if failed else 0
    record = write_release(args.ref, args.commit, args.previous)
    print(f"Release recorded: {record['ref']} ({record['commit'][:12]}), previous {record['previous'][:12] or 'none'}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
