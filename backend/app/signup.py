import logging
from typing import Optional

from app.auth import (
    APP_USER_TABLE,
    ROLES,
    create_user,
    hash_password,
    validate_display_name,
    validate_email,
    validate_password,
    validate_phone,
    validate_username,
    _normalize_email,
    _normalize_phone,
)
from app.database import db_cursor
from app.mail import send_account_ready

SIGNUP_TABLE = "orion_ods.signup_request"

logger = logging.getLogger(__name__)

DDL = (
    f"""
    CREATE TABLE IF NOT EXISTS {SIGNUP_TABLE} (
        id SERIAL PRIMARY KEY,
        username TEXT NOT NULL,
        display_name TEXT NOT NULL,
        password_hash TEXT NOT NULL,
        email TEXT NOT NULL,
        phone TEXT,
        status TEXT NOT NULL DEFAULT 'pending'
            CHECK (status IN ('pending', 'approved', 'rejected')),
        requested_timestamp TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        reviewed_timestamp TIMESTAMPTZ,
        reviewed_by INTEGER REFERENCES {APP_USER_TABLE}(id) ON DELETE SET NULL,
        created_user_id INTEGER REFERENCES {APP_USER_TABLE}(id) ON DELETE SET NULL,
        rejection_reason TEXT
    )
    """,
    f"""
    CREATE UNIQUE INDEX IF NOT EXISTS signup_request_pending_username_idx
        ON {SIGNUP_TABLE} (LOWER(username))
        WHERE status = 'pending'
    """,
    f"""
    CREATE UNIQUE INDEX IF NOT EXISTS signup_request_pending_email_idx
        ON {SIGNUP_TABLE} (LOWER(email))
        WHERE status = 'pending'
    """,
)

SIGNUP_SELECT = (
    "id, username, display_name, email, phone, status, "
    "requested_timestamp, reviewed_timestamp, reviewed_by, created_user_id, rejection_reason"
)


def ensure_signup_table() -> None:
    try:
        with db_cursor(commit=True) as cur:
            for statement in DDL:
                cur.execute(statement)
    except Exception as exc:
        # Not owning a table that already exists is expected and harmless (the schema scripts made it): say nothing. Anything
        # else is worth knowing, and would otherwise be a silent failure.
        owner = "must be owner" in str(exc).lower() or "permission denied" in str(exc).lower()
        if owner:
            logger.debug("Sign-up request table is owned by another role; left as it is: %s", exc)
        else:
            logger.exception("Could not create or check the sign-up request table")


def _row(cur, row) -> Optional[dict]:
    if not row:
        return None
    cols = [desc[0] for desc in cur.description]
    return dict(zip(cols, row))


def _ts(value):
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def public_signup(row: dict) -> dict:
    return {
        "id": row["id"],
        "username": row["username"],
        "display_name": row["display_name"],
        "email": row.get("email"),
        "phone": row.get("phone"),
        "status": row["status"],
        "requested_timestamp": _ts(row.get("requested_timestamp")),
        "reviewed_timestamp": _ts(row.get("reviewed_timestamp")),
        "reviewed_by": row.get("reviewed_by"),
        "created_user_id": row.get("created_user_id"),
        "rejection_reason": row.get("rejection_reason"),
    }


def count_pending_signups() -> int:
    try:
        with db_cursor() as cur:
            cur.execute(f"SELECT COUNT(*) FROM {SIGNUP_TABLE} WHERE status = 'pending'")
            return int(cur.fetchone()[0])
    except Exception:
        logger.exception("Could not count the pending sign-up requests")
        return 0


def _pending_username(username: str) -> bool:
    with db_cursor() as cur:
        cur.execute(
            f"""
            SELECT 1 FROM {SIGNUP_TABLE}
            WHERE LOWER(username) = LOWER(%s) AND status = 'pending'
            """,
            (username,),
        )
        return cur.fetchone() is not None


def _pending_email(email: str) -> bool:
    with db_cursor() as cur:
        cur.execute(
            f"""
            SELECT 1 FROM {SIGNUP_TABLE}
            WHERE LOWER(email) = LOWER(%s) AND status = 'pending'
            """,
            (email,),
        )
        return cur.fetchone() is not None


def _user_username_taken(username: str) -> bool:
    with db_cursor() as cur:
        cur.execute(
            f"SELECT 1 FROM {APP_USER_TABLE} WHERE LOWER(username) = LOWER(%s)",
            (username,),
        )
        return cur.fetchone() is not None


def _user_email_taken(email: str) -> bool:
    with db_cursor() as cur:
        cur.execute(
            f"SELECT 1 FROM {APP_USER_TABLE} WHERE email IS NOT NULL AND LOWER(email) = LOWER(%s)",
            (email,),
        )
        return cur.fetchone() is not None


def request_signup(
    username: str,
    display_name: str,
    password: str,
    email: str,
    phone: Optional[str] = None,
) -> None:
    username = username.strip()
    display_name = display_name.strip()
    email = _normalize_email(email)
    phone = _normalize_phone(phone)
    if err := validate_username(username):
        raise ValueError(err)
    if err := validate_display_name(display_name):
        raise ValueError(err)
    if err := validate_password(password):
        raise ValueError(err)
    if not email:
        raise ValueError("Email is required.")
    if err := validate_email(email):
        raise ValueError(err)
    if err := validate_phone(phone):
        raise ValueError(err)
    if _user_username_taken(username) or _pending_username(username):
        raise ValueError("Username already exists.")
    if _user_email_taken(email) or _pending_email(email):
        raise ValueError("An account with this email already exists, or a request is already waiting.")

    with db_cursor(commit=True) as cur:
        cur.execute(
            f"""
            INSERT INTO {SIGNUP_TABLE} (
                username, display_name, password_hash, email, phone
            ) VALUES (%s, %s, %s, %s, %s)
            """,
            (username, display_name, hash_password(password), email, phone),
        )


def list_signup_requests() -> dict:
    with db_cursor() as cur:
        cur.execute(
            f"""
            SELECT {SIGNUP_SELECT}
            FROM {SIGNUP_TABLE}
            WHERE status = 'pending'
            ORDER BY requested_timestamp
            """
        )
        pending = [public_signup(_row(cur, row)) for row in cur.fetchall()]
        cur.execute(
            f"""
            SELECT {SIGNUP_SELECT}
            FROM {SIGNUP_TABLE}
            WHERE status <> 'pending'
            ORDER BY reviewed_timestamp DESC NULLS LAST
            LIMIT 30
            """
        )
        reviewed = [public_signup(_row(cur, row)) for row in cur.fetchall()]
    return {"pending": pending, "reviewed": reviewed}


def _fetch_signup(request_id: int) -> Optional[dict]:
    with db_cursor() as cur:
        cur.execute(
            f"""
            SELECT {SIGNUP_SELECT}, password_hash
            FROM {SIGNUP_TABLE}
            WHERE id = %s
            """,
            (request_id,),
        )
        return _row(cur, cur.fetchone())


def approve_signup(request_id: int, acting_user_id: int, role: str = "viewer", **flags: Optional[bool]) -> dict:
    """Approve a request and create the account. ``flags`` are any of auth.ACCESS_FLAGS."""
    row = _fetch_signup(request_id)
    if not row:
        raise ValueError("Request not found.")
    if row["status"] != "pending":
        raise ValueError("This request has already been reviewed.")
    if role not in ROLES:
        raise ValueError("Invalid role.")

    user_id = create_user(
        row["username"],
        row["display_name"],
        "",
        role,
        password_hash=row["password_hash"],
        email=row["email"],
        phone=row.get("phone"),
        exclude_signup_id=request_id,
        **flags,
    )
    with db_cursor(commit=True) as cur:
        cur.execute(
            f"""
            UPDATE {SIGNUP_TABLE}
            SET status = 'approved',
                reviewed_timestamp = CURRENT_TIMESTAMP,
                reviewed_by = %s,
                created_user_id = %s
            WHERE id = %s AND status = 'pending'
            """,
            (acting_user_id, user_id, request_id),
        )
    send_account_ready(row["email"], row["display_name"], row["username"])
    return {"ok": True, "email": row["email"], "user_id": user_id}


def reject_signup(request_id: int, acting_user_id: int, reason: Optional[str] = None) -> None:
    row = _fetch_signup(request_id)
    if not row:
        raise ValueError("Request not found.")
    if row["status"] != "pending":
        raise ValueError("This request has already been reviewed.")
    note = (reason or "").strip() or None
    if note and len(note) > 240:
        raise ValueError("Reason must be 240 characters or fewer.")
    with db_cursor(commit=True) as cur:
        cur.execute(
            f"""
            UPDATE {SIGNUP_TABLE}
            SET status = 'rejected',
                reviewed_timestamp = CURRENT_TIMESTAMP,
                reviewed_by = %s,
                rejection_reason = %s
            WHERE id = %s AND status = 'pending'
            """,
            (acting_user_id, note, request_id),
        )
