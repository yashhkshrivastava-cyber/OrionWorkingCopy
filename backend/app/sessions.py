"""Signed-in sessions that the server can end.

Before this, a session was only a signed ``user_id:expiry`` in a cookie. Nothing on the server knew about it, so signing out
only deleted the browser's copy: a cookie that had been copied (a shared PC, a backup of a browser profile) kept working for
seven days after the person signed out, changed their password, or was disabled.

Now each sign-in is a row of ``orion_ods.app_session`` and the cookie is ``<random id>:<expiry>:<signature>``. A request is
accepted only if the signature is ours AND the row is neither revoked nor expired AND the person is still active. The signature
means a copy of the database is not enough to make a cookie; the row means a stolen cookie can be ended.

This module has no import from ``auth`` at the top (``auth`` calls it when a password changes), so it can be loaded first.
"""

import hashlib
import hmac
import logging
import re
import secrets
import time
from typing import Optional

from app.config import session_secret, session_ttl_seconds
from app.database import db_cursor

logger = logging.getLogger(__name__)

SESSION_TABLE = "orion_ods.app_session"

# last_seen is for the person looking at their devices, not a security control, so it is written at most this often
# (otherwise every request would also be a write).
TOUCH_AFTER_SECONDS = 300
MAX_TOKEN_CHARS = 200
KEEP_ENDED_DAYS = 7

REASON_SIGNED_OUT = "signed out"
REASON_PASSWORD = "password changed"
REASON_DISABLED = "account disabled"
REASON_ADMIN = "ended by an administrator"
REASON_OTHERS = "signed out from another device"
REASON_ONE = "ended from the devices list"


# ------------------------------------------------------------------------------------------------------------- the cookie


def _sign(payload: str) -> str:
    return hmac.new(session_secret(), payload.encode(), hashlib.sha256).hexdigest()


def make_token(token_id: str, expires_at: int) -> str:
    payload = f"{token_id}:{expires_at}"
    return f"{payload}:{_sign(payload)}"


def parse_token(token: Optional[str]) -> Optional[str]:
    """The session's random id when the cookie is ours and unexpired, else None. Looks at nothing but the cookie itself."""
    if not token or len(token) > MAX_TOKEN_CHARS:
        return None
    parts = token.split(":")
    if len(parts) != 3:
        return None
    token_id, expires, signature = parts
    try:
        if int(expires) < time.time():
            return None
    except ValueError:
        return None
    if not hmac.compare_digest(signature, _sign(f"{token_id}:{expires}")):
        return None
    return token_id or None


# ------------------------------------------------------------------------------------------------------------ the session


def create_session(user_id: int, ip: Optional[str] = None, user_agent: Optional[str] = None) -> str:
    """Record a sign-in and return the cookie value for it."""
    token_id = secrets.token_urlsafe(24)
    expires_at = int(time.time()) + session_ttl_seconds()
    with db_cursor(commit=True) as cur:
        # Tidy as a side effect of signing in: sessions that have been over for a week are no use to anyone.
        cur.execute(
            f"DELETE FROM {SESSION_TABLE} WHERE LEAST(expires_timestamp, COALESCE(revoked_timestamp, expires_timestamp)) "
            f"< CURRENT_TIMESTAMP - make_interval(days => %s)",
            (KEEP_ENDED_DAYS,),
        )
        cur.execute(
            f"INSERT INTO {SESSION_TABLE} (token_id, user_id, expires_timestamp, ip, user_agent) "
            f"VALUES (%s, %s, to_timestamp(%s), %s, %s)",
            (token_id, user_id, expires_at, (ip or "")[:64] or None, (user_agent or "")[:300] or None),
        )
    return make_token(token_id, expires_at)


def lookup(token: Optional[str]) -> Optional[dict]:
    """The live session behind a cookie ({'ref', 'user_id'}), or None if it is forged, expired or has been ended."""
    token_id = parse_token(token)
    if not token_id:
        return None
    with db_cursor(commit=True) as cur:
        cur.execute(
            f"""
            SELECT id, user_id, last_seen_timestamp < CURRENT_TIMESTAMP - make_interval(secs => %s)
            FROM {SESSION_TABLE}
            WHERE token_id = %s AND revoked_timestamp IS NULL AND expires_timestamp > CURRENT_TIMESTAMP
            """,
            (TOUCH_AFTER_SECONDS, token_id),
        )
        row = cur.fetchone()
        if not row:
            return None
        if row[2]:
            cur.execute(f"UPDATE {SESSION_TABLE} SET last_seen_timestamp = CURRENT_TIMESTAMP WHERE id = %s", (row[0],))
        return {"ref": row[0], "user_id": row[1]}


def user_for_token(token: Optional[str]) -> Optional[dict]:
    """The active person a cookie belongs to, or None. Every authenticated request and the live-chat socket go through this."""
    found = lookup(token)
    if not found:
        return None
    from app.auth import fetch_user_by_id  # not at the top: auth imports this module

    user = fetch_user_by_id(found["user_id"])
    if not user or not user.get("is_active"):
        return None
    return user


def current_ref(token: Optional[str]) -> Optional[int]:
    found = lookup(token)
    return found["ref"] if found else None


# ------------------------------------------------------------------------------------------------------------- ending them


def _end(cur, where: str, params: tuple, reason: str) -> int:
    cur.execute(
        f"UPDATE {SESSION_TABLE} SET revoked_timestamp = CURRENT_TIMESTAMP, revoked_reason = %s "
        f"WHERE revoked_timestamp IS NULL AND {where}",
        (reason, *params),
    )
    return cur.rowcount


def revoke_token(token: Optional[str], reason: str = REASON_SIGNED_OUT) -> bool:
    """End the session this cookie belongs to (sign out). A cookie that is not ours or already over is ignored."""
    token_id = parse_token(token)
    if not token_id:
        return False
    with db_cursor(commit=True) as cur:
        return _end(cur, "token_id = %s", (token_id,), reason) > 0


def revoke_all(user_id: int, reason: str, *, keep_ref: Optional[int] = None, cur=None) -> int:
    """End every live session of a person, except one (``keep_ref``). Pass ``cur`` to do it in the same transaction as the
    change that caused it, so a password can never change while its old sessions live on."""
    where, params = ("user_id = %s", (user_id,)) if keep_ref is None else ("user_id = %s AND id <> %s", (user_id, keep_ref))
    if cur is not None:
        return _end(cur, where, params, reason)
    with db_cursor(commit=True) as own:
        return _end(own, where, params, reason)


def revoke_one(user_id: int, ref: int, reason: str = REASON_ONE) -> bool:
    """End one of a person's own sessions by its number. Someone else's number does nothing."""
    with db_cursor(commit=True) as cur:
        return _end(cur, "user_id = %s AND id = %s", (user_id, ref), reason) > 0


# ---------------------------------------------------------------------------------------------------------- the device list


def describe_agent(user_agent: Optional[str]) -> str:
    """'Chrome on Windows' from a browser's user-agent text; a person recognises their own devices by this."""
    text = user_agent or ""
    if not text:
        return "Unknown device"
    browser = next(
        (name for name, pattern in (
            ("Edge", r"Edg(e|A|iOS)?/"), ("Opera", r"OPR/|Opera"), ("Firefox", r"Firefox/|FxiOS/"),
            ("Chrome", r"Chrome/|CriOS/"), ("Safari", r"Safari/"), ("Orion app", r"pywebview|Orion"),
        ) if re.search(pattern, text)),
        "Browser",
    )
    system = next(
        (name for name, pattern in (
            ("Android", r"Android"), ("iPhone", r"iPhone"), ("iPad", r"iPad"), ("Windows", r"Windows"),
            ("Mac", r"Macintosh|Mac OS"), ("Linux", r"Linux"),
        ) if re.search(pattern, text)),
        None,
    )
    return f"{browser} on {system}" if system else browser


def list_for_user(user_id: int, current: Optional[int]) -> list[dict]:
    with db_cursor() as cur:
        cur.execute(
            f"""
            SELECT id, created_timestamp, last_seen_timestamp, expires_timestamp, ip, user_agent
            FROM {SESSION_TABLE}
            WHERE user_id = %s AND revoked_timestamp IS NULL AND expires_timestamp > CURRENT_TIMESTAMP
            ORDER BY last_seen_timestamp DESC
            """,
            (user_id,),
        )
        return [
            {
                "id": row[0],
                "created": row[1].isoformat(),
                "last_seen": row[2].isoformat(),
                "expires": row[3].isoformat(),
                "ip": row[4],
                "device": describe_agent(row[5]),
                "current": row[0] == current,
            }
            for row in cur.fetchall()
        ]
