import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
# override=True so editing .env and restarting/reloading actually picks up SMTP settings.
load_dotenv(ROOT / ".env", override=True)

SESSION_COOKIE_NAME = "orion_session"

# What the application falls back to when nothing is configured, so a fresh checkout runs with no setup. They are public
# (they are in this repository), which is why startup_checks.py refuses all of them when ORION_ENV=production.
DEV_SESSION_SECRET = "orion-dev-session-secret-change-in-production"
DEV_DB_PASSWORD = "orion_dev_password"
DEV_ADMIN_PASSWORD = "orion_dev_password"
DEFAULT_SESSION_TTL_DAYS = 7


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def db_settings() -> dict:
    return {
        "host": env("ORION_DB_HOST", "localhost"),
        "database": env("ORION_DB_NAME", "orion"),
        "user": env("ORION_DB_USER", "orion_user"),
        "password": env("ORION_DB_PASSWORD", DEV_DB_PASSWORD),
        "port": int(env("ORION_DB_PORT", "5432")),
    }


def session_secret() -> bytes:
    return env("ORION_SESSION_SECRET", DEV_SESSION_SECRET).encode()


def session_ttl_seconds() -> int:
    days = int(env("ORION_SESSION_TTL_DAYS", str(DEFAULT_SESSION_TTL_DAYS)))
    return max(1, days) * 86400


def avatar_dir() -> Path:
    path = ROOT / "data" / "avatars"
    path.mkdir(parents=True, exist_ok=True)
    return path


def chat_media_dir() -> Path:
    path = ROOT / "data" / "chat-media"
    path.mkdir(parents=True, exist_ok=True)
    return path


def support_dir() -> Path:
    path = ROOT / "data" / "support"
    path.mkdir(parents=True, exist_ok=True)
    return path
