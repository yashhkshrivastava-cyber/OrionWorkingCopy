"""Refuse to start a production server with development secrets.

``config.py`` falls back to a published session secret, database password and admin password so that a fresh checkout runs
with no setup. That is right on a developer's PC and dangerous on the server: with the published session secret anyone who
has read this repository can sign a cookie for any user. So when ``ORION_ENV=production`` the API checks its own settings
before it opens the database, and stops with one message that lists everything to fix.

Nothing here reads the database, and none of it runs outside production (development only logs a warning).
"""

import logging
import os
from typing import Mapping, Optional

from app.config import DEV_ADMIN_PASSWORD, DEV_DB_PASSWORD, DEV_SESSION_SECRET

logger = logging.getLogger(__name__)

MIN_SESSION_SECRET_CHARS = 32
MIN_ADMIN_PASSWORD_CHARS = 12

# The wording the example env files use for "put your own value here".
_PLACEHOLDER_PREFIXES = ("change-me", "changeme", "your-", "your_", "replace-me", "<")

_HOW_TO_MAKE_A_SECRET = 'python -c "import secrets; print(secrets.token_urlsafe(48))"'


class StartupConfigError(RuntimeError):
    """The settings are not safe to run production with. The message says which and how to fix each."""


def is_production(environ: Optional[Mapping[str, str]] = None) -> bool:
    source = os.environ if environ is None else environ
    return (source.get("ORION_ENV") or "").strip().lower() == "production"


def _placeholder(value: str, known_defaults: tuple[str, ...]) -> bool:
    lowered = value.strip().lower()
    return lowered in {item.lower() for item in known_defaults} or lowered.startswith(_PLACEHOLDER_PREFIXES)


def session_secret_problem(value: str) -> Optional[str]:
    if not value.strip():
        return "ORION_SESSION_SECRET is empty, so sessions are signed with a secret that is published in the repository."
    if _placeholder(value, (DEV_SESSION_SECRET,)):
        return "ORION_SESSION_SECRET is still the development or example value, which is published in the repository."
    if len(value.strip()) < MIN_SESSION_SECRET_CHARS:
        return f"ORION_SESSION_SECRET is shorter than {MIN_SESSION_SECRET_CHARS} characters."
    return None


def database_password_problem(value: str) -> Optional[str]:
    if not value.strip():
        return "ORION_DB_PASSWORD is empty, so the application would try the published development password."
    if _placeholder(value, (DEV_DB_PASSWORD,)):
        return "ORION_DB_PASSWORD is still the development or example value, which is published in the repository."
    return None


def admin_password_problem(value: str) -> Optional[str]:
    """Checked only when the first administrator is about to be created (there is no one to sign in yet)."""
    if not value.strip():
        return "ORION_ADMIN_PASSWORD is empty, so the first administrator would get the published development password."
    if _placeholder(value, (DEV_ADMIN_PASSWORD,)):
        return "ORION_ADMIN_PASSWORD is still the development or example value, which is published in the repository."
    if len(value) < MIN_ADMIN_PASSWORD_CHARS:
        return f"ORION_ADMIN_PASSWORD is shorter than {MIN_ADMIN_PASSWORD_CHARS} characters."
    return None


def google_drive_problem(source: Mapping[str, str]) -> str:
    """Production must not run on the fake Drive (it keeps people's files in a folder on one PC and looks like a real Drive), and asking for
    Google's Drive needs both halves of its credentials."""
    wanted = (source.get("ORION_GDRIVE") or "auto").strip().lower()
    if wanted == "fake":
        return "ORION_GDRIVE=fake is the development stand-in for Google Drive and is refused in production. Remove it, or add Google's client ID and secret."
    if wanted == "google" and not ((source.get("ORION_GOOGLE_CLIENT_ID") or "").strip() and (source.get("ORION_GOOGLE_CLIENT_SECRET") or "").strip()):
        return "ORION_GDRIVE=google needs ORION_GOOGLE_CLIENT_ID and ORION_GOOGLE_CLIENT_SECRET."
    return ""


def production_problems(environ: Optional[Mapping[str, str]] = None) -> list[str]:
    """Everything wrong with the settings for a production server; empty outside production or when all is well."""
    source = os.environ if environ is None else environ
    if not is_production(source):
        return []
    found = [
        session_secret_problem(source.get("ORION_SESSION_SECRET", "")),
        database_password_problem(source.get("ORION_DB_PASSWORD", "")),
        google_drive_problem(source),
    ]
    return [problem for problem in found if problem]


def verify_production(environ: Optional[Mapping[str, str]] = None) -> None:
    """Raise StartupConfigError, listing every problem, when this is a production server with unsafe settings."""
    problems = production_problems(environ)
    if problems:
        raise StartupConfigError(
            "Orion will not start in production with unsafe settings:\n"
            + "\n".join(f"  - {problem}" for problem in problems)
            + f"\nFix them in this machine's .env (see deploy/env.prod.example). A new secret:  {_HOW_TO_MAKE_A_SECRET}"
        )


def warn_if_development_defaults(environ: Optional[Mapping[str, str]] = None) -> None:
    """In development the defaults are fine; say so once, so nobody mistakes a half-configured server for a safe one."""
    source = os.environ if environ is None else environ
    if is_production(source):
        return
    if session_secret_problem(source.get("ORION_SESSION_SECRET", "")):
        logger.warning("ORION_SESSION_SECRET is not set to a private value: fine for development, refused in production.")


def main() -> int:
    """``python -m app.startup_checks`` (run from backend/): check this machine's .env without starting the server.

    deploy.ps1 runs it before stopping the running server, so a bad .env stops the deploy instead of the site.
    """
    try:
        verify_production()
    except StartupConfigError as exc:
        print(exc)
        return 1
    print("Production settings are safe." if is_production() else "Not a production machine (ORION_ENV is not 'production'); nothing to check.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
