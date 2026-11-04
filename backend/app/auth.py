import hashlib
import logging
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional

import bcrypt

from app.appearance import AppearanceError, dump_appearance, load_appearance
from app import sessions
from app.config import DEV_ADMIN_PASSWORD, db_settings, env
from app.database import db_cursor
from app.startup_checks import StartupConfigError, admin_password_problem, is_production

APP_USER_TABLE = "orion_ods.app_user"

logger = logging.getLogger(__name__)
ROLES = ("admin", "editor", "viewer")

ROLE_PAGES = {
    "admin": {"home", "dashboard", "data", "admin"},
    "editor": {"home", "dashboard", "data"},
    "viewer": {"home", "dashboard"},
}

ROLE_LABELS = {
    "admin": "Admin — full access + user management",
    "editor": "Editor — dashboard and data management",
    "viewer": "Viewer — dashboard only",
}

ROLE_DEFAULT_DATA_ACCESS = {
    "admin": {
        "ods_access": True,
        "ods_write": True,
        "dw_access": True,
        "dw_write": True,
        "tally_access": True,
        "tally_write": True,
        "tally_dw_access": True,
        "tally_dw_write": True,
        "orion_dashboard_access": True,
        "tally_dashboard_access": True,
        "billing_access": True,
        "billing_write": True,
        "etl_access": True,
        "etl_write": True,
        "letterhead_access": True,
        "letterhead_write": True,
        "documents_access": True,
        "documents_write": True,
        "bank_access": True,
        "bank_write": True,
        "tenders_access": True,
        "tenders_write": True,
        "attendance_access": True,
        "attendance_write": True,
        "ai_access": True,
    },
    "editor": {
        "ods_access": True,
        "ods_write": True,
        "dw_access": True,
        "dw_write": True,
        "tally_access": True,
        "tally_write": True,
        "tally_dw_access": True,
        "tally_dw_write": True,
        "orion_dashboard_access": True,
        "tally_dashboard_access": True,
        "billing_access": True,
        "billing_write": True,
        "etl_access": True,
        "etl_write": True,
        "letterhead_access": True,
        "letterhead_write": True,
        "documents_access": True,
        "documents_write": True,
        "bank_access": False,
        "bank_write": False,
        "tenders_access": True,
        "tenders_write": True,
        "attendance_access": True,
        "attendance_write": True,
        "ai_access": True,
    },
    "viewer": {
        "ods_access": False,
        "ods_write": False,
        "dw_access": False,
        "dw_write": False,
        "tally_access": False,
        "tally_write": False,
        "tally_dw_access": False,
        "tally_dw_write": False,
        "orion_dashboard_access": True,
        "tally_dashboard_access": False,
        "billing_access": False,
        "billing_write": False,
        "etl_access": False,
        "etl_write": False,
        "letterhead_access": False,
        "letterhead_write": False,
        "documents_access": False,
        "documents_write": False,
        "bank_access": False,
        "bank_write": False,
        "tenders_access": False,
        "tenders_write": False,
        "attendance_access": False,
        "attendance_write": False,
        "ai_access": True,
    },
}

ACCESS_FLAGS = (
    "ods_access",
    "ods_write",
    "dw_access",
    "dw_write",
    "tally_access",
    "tally_write",
    "tally_dw_access",
    "tally_dw_write",
    "orion_dashboard_access",
    "tally_dashboard_access",
    "billing_access",
    "billing_write",
    "etl_access",
    "etl_write",
    "letterhead_access",
    "letterhead_write",
    "documents_access",
    "documents_write",
    "bank_access",
    "bank_write",
    "tenders_access",
    "tenders_write",
    "attendance_access",
    "attendance_write",
    "ai_access",
)

# Being allowed to change something always includes being allowed to see it.
WRITE_IMPLIES_ACCESS = (
    ("ods_write", "ods_access"),
    ("dw_write", "dw_access"),
    ("tally_write", "tally_access"),
    ("tally_dw_write", "tally_dw_access"),
    ("billing_write", "billing_access"),
    ("etl_write", "etl_access"),
    ("letterhead_write", "letterhead_access"),
    ("documents_write", "documents_access"),
    ("bank_write", "bank_access"),
    ("tenders_write", "tenders_access"),
    ("attendance_write", "attendance_access"),
)

USER_SELECT_COLUMNS = (
    "id, username, display_name, role, is_active, "
    + ", ".join(ACCESS_FLAGS)
    + ", created_timestamp, preferred_theme, appearance, avatar_ext, avatar_version, email, phone"
)

THEMES = ("light", "dark")

USERNAME_PATTERN = re.compile(r"^[a-zA-Z0-9._-]{3,32}$")
PASSWORD_RESET_TTL = timedelta(hours=1)
RESET_GENERIC_ERROR = "This reset link is invalid or has expired."


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode(), password_hash.encode())


def _access_defaults(role: Optional[str]) -> dict:
    return dict(ROLE_DEFAULT_DATA_ACCESS.get(role, ROLE_DEFAULT_DATA_ACCESS["viewer"]))


def _normalize_access(user: dict) -> dict:
    defaults = _access_defaults(user.get("role"))
    for flag in ACCESS_FLAGS:
        if user.get(flag) is None:
            user[flag] = defaults[flag]
        else:
            user[flag] = bool(user[flag])
    for write, access in WRITE_IMPLIES_ACCESS:
        if user[write]:
            user[access] = True
    return user


def _session_user_from_row(row, columns):
    user = dict(zip(columns, row))
    user.pop("password_hash", None)
    return _normalize_access(user)


def _resolved_access(role: str, **given: Optional[bool]) -> dict:
    """Every flag for a user: what was given, else the role's default, with write implying access."""
    unknown = set(given) - set(ACCESS_FLAGS)
    if unknown:
        raise TypeError(f"Unknown access flags: {sorted(unknown)}")
    defaults = _access_defaults(role)
    resolved = {
        flag: defaults[flag] if given.get(flag) is None else bool(given[flag]) for flag in ACCESS_FLAGS
    }
    for write, access in WRITE_IMPLIES_ACCESS:
        if resolved[write]:
            resolved[access] = True
    return resolved


def _fetch_user_by_username(username: str):
    with db_cursor() as cur:
        cur.execute(
            f"""
            SELECT id, username, display_name, password_hash, role, is_active,
                   {", ".join(ACCESS_FLAGS)},
                   preferred_theme, appearance, avatar_ext, avatar_version,
                   email, phone
            FROM {APP_USER_TABLE}
            WHERE username = %s
            """,
            (username,),
        )
        row = cur.fetchone()
        if not row:
            return None
        cols = [desc[0] for desc in cur.description]
        return dict(zip(cols, row))


def fetch_user_by_id(user_id: int):
    with db_cursor() as cur:
        cur.execute(
            f"SELECT {USER_SELECT_COLUMNS} FROM {APP_USER_TABLE} WHERE id = %s",
            (user_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        cols = [desc[0] for desc in cur.description]
        return _session_user_from_row(row, cols)


def list_users():
    with db_cursor() as cur:
        cur.execute(
            f"SELECT {USER_SELECT_COLUMNS} FROM {APP_USER_TABLE} ORDER BY username"
        )
        rows = cur.fetchall()
        cols = [desc[0] for desc in cur.description]
        return [_session_user_from_row(row, cols) for row in rows]


def _user_count() -> int:
    with db_cursor() as cur:
        cur.execute(f"SELECT COUNT(*) FROM {APP_USER_TABLE}")
        return cur.fetchone()[0]


def count_active_admins(exclude_user_id: Optional[int] = None) -> int:
    with db_cursor() as cur:
        if exclude_user_id is None:
            cur.execute(
                f"SELECT COUNT(*) FROM {APP_USER_TABLE} WHERE role = 'admin' AND is_active = TRUE"
            )
        else:
            cur.execute(
                f"""
                SELECT COUNT(*) FROM {APP_USER_TABLE}
                WHERE role = 'admin' AND is_active = TRUE AND id <> %s
                """,
                (exclude_user_id,),
            )
        return cur.fetchone()[0]


def validate_username(username: str) -> Optional[str]:
    username = username.strip()
    if not USERNAME_PATTERN.match(username):
        return "Username must be 3-32 characters and use letters, numbers, dots, dashes, or underscores."
    return None


def validate_password(password: str) -> Optional[str]:
    if len(password) < 8:
        return "Password must be at least 8 characters."
    return None


def validate_email(email: Optional[str]) -> Optional[str]:
    if email is None or not str(email).strip():
        return None
    email = str(email).strip()
    if len(email) > 254:
        return "Email must be 254 characters or fewer."
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        return "Enter a valid email address."
    return None


def validate_phone(phone: Optional[str]) -> Optional[str]:
    if phone is None or not str(phone).strip():
        return None
    phone = re.sub(r"[\s-]", "", str(phone).strip())
    if len(phone) > 20:
        return "Phone must be 20 characters or fewer."
    if not re.match(r"^\+?[0-9]{7,15}$", phone):
        return "Enter a valid phone number."
    return None


def _normalize_email(email: Optional[str]) -> Optional[str]:
    if email is None:
        return None
    value = str(email).strip().lower()
    return value or None


def _normalize_phone(phone: Optional[str]) -> Optional[str]:
    if phone is None:
        return None
    value = re.sub(r"[\s-]", "", str(phone).strip())
    return value or None


def create_user(
    username: str,
    display_name: str,
    password: str,
    role: str = "viewer",
    *,
    password_hash: Optional[str] = None,
    email: Optional[str] = None,
    phone: Optional[str] = None,
    exclude_signup_id: Optional[int] = None,
    **flags: Optional[bool],
) -> int:
    """Create a user. ``flags`` are any of ACCESS_FLAGS; one left out takes the role's default."""
    username = username.strip()
    display_name = display_name.strip()
    email = _normalize_email(email)
    phone = _normalize_phone(phone)
    if role not in ROLES:
        raise ValueError("Invalid role.")
    if err := validate_username(username):
        raise ValueError(err)
    if password_hash:
        stored_hash = password_hash
    else:
        if err := validate_password(password):
            raise ValueError(err)
        stored_hash = hash_password(password)
    if err := validate_email(email):
        raise ValueError(err)
    if err := validate_phone(phone):
        raise ValueError(err)
    if not display_name:
        raise ValueError("Display name is required.")
    if _username_taken(username, exclude_signup_id=exclude_signup_id):
        raise ValueError("Username already exists.")

    access = _resolved_access(role, **flags)
    columns = ["username", "display_name", "password_hash", "role", *ACCESS_FLAGS, "email", "phone"]
    values = [username, display_name, stored_hash, role, *(access[flag] for flag in ACCESS_FLAGS), email, phone]

    with db_cursor(commit=True) as cur:
        cur.execute(
            f"""
            INSERT INTO {APP_USER_TABLE} ({", ".join(columns)})
            VALUES ({", ".join(["%s"] * len(columns))})
            RETURNING id
            """,
            values,
        )
        return cur.fetchone()[0]


def _username_taken(username: str, *, exclude_signup_id: Optional[int] = None) -> bool:
    with db_cursor() as cur:
        cur.execute(
            f"SELECT 1 FROM {APP_USER_TABLE} WHERE LOWER(username) = LOWER(%s)",
            (username,),
        )
        if cur.fetchone():
            return True
    try:
        with db_cursor() as cur:
            cur.execute(
                """
                SELECT 1 FROM orion_ods.signup_request
                WHERE LOWER(username) = LOWER(%s) AND status = 'pending'
                  AND (%s IS NULL OR id <> %s)
                """,
                (username, exclude_signup_id, exclude_signup_id),
            )
            return cur.fetchone() is not None
    except Exception:
        logger.exception("Could not check whether a pending sign-up request already uses that username")
        return False


def update_user_data_access(user_id: int, acting_user_id: int, **flags: Optional[bool]):
    """Set a user's access. A flag left out (or None) keeps the value the user has now."""
    target = fetch_user_by_id(user_id)
    if not target:
        raise ValueError("User not found.")
    kept = {flag: bool(target.get(flag)) for flag in ACCESS_FLAGS}
    access = _resolved_access(target["role"], **{**kept, **{k: v for k, v in flags.items() if v is not None}})
    if user_id == acting_user_id and not any(access[flag] for flag in ACCESS_FLAGS):
        raise ValueError("You cannot remove all data access from your own account.")
    assignments = ", ".join(f"{flag} = %s" for flag in ACCESS_FLAGS)
    with db_cursor(commit=True) as cur:
        cur.execute(
            f"UPDATE {APP_USER_TABLE} SET {assignments}, updated_timestamp = CURRENT_TIMESTAMP WHERE id = %s",
            [*(access[flag] for flag in ACCESS_FLAGS), user_id],
        )


def update_user_role(user_id: int, role: str, acting_user_id: int):
    if role not in ROLES:
        raise ValueError("Invalid role.")
    target = fetch_user_by_id(user_id)
    if not target:
        raise ValueError("User not found.")
    if target["role"] == "admin" and role != "admin" and count_active_admins(exclude_user_id=user_id) == 0:
        raise ValueError("Cannot change role of the last active admin.")
    if user_id == acting_user_id and role != "admin":
        raise ValueError("You cannot remove your own admin access.")
    with db_cursor(commit=True) as cur:
        cur.execute(
            f"UPDATE {APP_USER_TABLE} SET role = %s, updated_timestamp = CURRENT_TIMESTAMP WHERE id = %s",
            (role, user_id),
        )


def set_user_active(user_id: int, is_active: bool, acting_user_id: int):
    target = fetch_user_by_id(user_id)
    if not target:
        raise ValueError("User not found.")
    if user_id == acting_user_id and not is_active:
        raise ValueError("You cannot disable your own account.")
    if target["role"] == "admin" and not is_active and count_active_admins(exclude_user_id=user_id) == 0:
        raise ValueError("Cannot disable the last active admin.")
    with db_cursor(commit=True) as cur:
        cur.execute(
            f"UPDATE {APP_USER_TABLE} SET is_active = %s, updated_timestamp = CURRENT_TIMESTAMP WHERE id = %s",
            (is_active, user_id),
        )
        if not is_active:
            sessions.revoke_all(user_id, sessions.REASON_DISABLED, cur=cur)


def update_user_contact(
    user_id: int,
    *,
    email: Optional[str] = None,
    phone: Optional[str] = None,
):
    updates = []
    values = []
    if email is not None:
        email_value = _normalize_email(email)
        if err := validate_email(email_value):
            raise ValueError(err)
        updates.append("email = %s")
        values.append(email_value)
    if phone is not None:
        phone_value = _normalize_phone(phone)
        if err := validate_phone(phone_value):
            raise ValueError(err)
        updates.append("phone = %s")
        values.append(phone_value)
    if not updates:
        return
    updates.append("updated_timestamp = CURRENT_TIMESTAMP")
    values.append(user_id)
    with db_cursor(commit=True) as cur:
        cur.execute(
            f"UPDATE {APP_USER_TABLE} SET {', '.join(updates)} WHERE id = %s",
            values,
        )
        if cur.rowcount == 0:
            raise ValueError("User not found.")


def _hash_reset_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _store_password_reset_token(user_id: int) -> str:
    raw = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + PASSWORD_RESET_TTL
    with db_cursor(commit=True) as cur:
        cur.execute(
            f"""
            UPDATE {APP_USER_TABLE}
            SET password_reset_token = %s,
                password_reset_expires = %s,
                updated_timestamp = CURRENT_TIMESTAMP
            WHERE id = %s
            """,
            (_hash_reset_token(raw), expires, user_id),
        )
    return raw


def request_password_reset(username: str, email: str) -> None:
    """Send a reset link when username + email match. Always silent to the caller."""
    user = _fetch_user_by_username(username.strip())
    if not user or not user.get("is_active"):
        return
    stored_email = user.get("email")
    if not stored_email or _normalize_email(email) != _normalize_email(stored_email):
        return
    raw = _store_password_reset_token(user["id"])
    from app.mail import send_password_reset

    send_password_reset(stored_email, user.get("display_name") or user["username"], raw)


def send_user_password_reset(user_id: int) -> str:
    """Admin: email a reset link. Returns the destination address."""
    user = fetch_user_by_id(user_id)
    if not user:
        raise ValueError("User not found.")
    if not user.get("is_active"):
        raise ValueError("Cannot send a reset link to a disabled account.")
    stored_email = (user.get("email") or "").strip()
    if not stored_email:
        raise ValueError("This user has no email. Add one under Contact first.")
    raw = _store_password_reset_token(user["id"])
    from app.mail import send_password_reset

    send_password_reset(
        stored_email,
        user.get("display_name") or user["username"],
        raw,
        by_admin=True,
        raise_on_error=True,
    )
    return stored_email


def password_reset_token_valid(token: str) -> bool:
    if not token or len(token) > 200:
        return False
    with db_cursor() as cur:
        cur.execute(
            f"""
            SELECT 1 FROM {APP_USER_TABLE}
            WHERE password_reset_token = %s
              AND password_reset_expires > CURRENT_TIMESTAMP
              AND is_active = TRUE
            """,
            (_hash_reset_token(token),),
        )
        return cur.fetchone() is not None


def complete_password_reset(token: str, password: str):
    if err := validate_password(password):
        raise ValueError(err)
    if not token or len(token) > 200:
        raise ValueError(RESET_GENERIC_ERROR)
    digest = _hash_reset_token(token)
    with db_cursor(commit=True) as cur:
        cur.execute(
            f"""
            SELECT id FROM {APP_USER_TABLE}
            WHERE password_reset_token = %s
              AND password_reset_expires > CURRENT_TIMESTAMP
              AND is_active = TRUE
            """,
            (digest,),
        )
        row = cur.fetchone()
        if not row:
            raise ValueError(RESET_GENERIC_ERROR)
        cur.execute(
            f"""
            UPDATE {APP_USER_TABLE}
            SET password_hash = %s,
                password_reset_token = NULL,
                password_reset_expires = NULL,
                updated_timestamp = CURRENT_TIMESTAMP
            WHERE id = %s
            """,
            (hash_password(password), row[0]),
        )
        # Whoever knew the old password (or held a cookie made with it) must sign in again.
        sessions.revoke_all(row[0], sessions.REASON_PASSWORD, cur=cur)


def update_user_password(user_id: int, password: str):
    if err := validate_password(password):
        raise ValueError(err)
    with db_cursor(commit=True) as cur:
        cur.execute(
            f"""
            UPDATE {APP_USER_TABLE}
            SET password_hash = %s,
                password_reset_token = NULL,
                password_reset_expires = NULL,
                updated_timestamp = CURRENT_TIMESTAMP
            WHERE id = %s
            """,
            (hash_password(password), user_id),
        )
        if cur.rowcount == 0:
            raise ValueError("User not found.")
        sessions.revoke_all(user_id, sessions.REASON_PASSWORD, cur=cur)


def delete_user(user_id: int, acting_user_id: int):
    target = fetch_user_by_id(user_id)
    if not target:
        raise ValueError("User not found.")
    if user_id == acting_user_id:
        raise ValueError("You cannot delete your own account.")
    if target["role"] == "admin" and count_active_admins(exclude_user_id=user_id) == 0:
        raise ValueError("Cannot delete the last active admin.")
    with db_cursor(commit=True) as cur:
        cur.execute(
            """
            UPDATE orion_ods.signup_request
            SET created_user_id = NULL
            WHERE created_user_id = %s
            """,
            (user_id,),
        )
        cur.execute(
            """
            UPDATE orion_ods.signup_request
            SET reviewed_by = NULL
            WHERE reviewed_by = %s
            """,
            (user_id,),
        )
        cur.execute(f"DELETE FROM {APP_USER_TABLE} WHERE id = %s", (user_id,))


def _app_user_column_exists(cur, column: str) -> bool:
    cur.execute(
        """
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'orion_ods'
          AND table_name = 'app_user'
          AND column_name = %s
        """,
        (column,),
    )
    return cur.fetchone() is not None


def _apply_user_access_columns(cur):
    added_ods = not _app_user_column_exists(cur, "ods_write")
    added_dw = not _app_user_column_exists(cur, "dw_write")
    added_tally_access = not _app_user_column_exists(cur, "tally_access")
    added_tally_write = not _app_user_column_exists(cur, "tally_write")
    added_tally_dw_access = not _app_user_column_exists(cur, "tally_dw_access")
    added_tally_dw_write = not _app_user_column_exists(cur, "tally_dw_write")
    added_orion_dashboard = not _app_user_column_exists(cur, "orion_dashboard_access")
    added_tally_dashboard = not _app_user_column_exists(cur, "tally_dashboard_access")
    added_billing = not _app_user_column_exists(cur, "billing_access")
    added_etl = not _app_user_column_exists(cur, "etl_access")
    added_letterhead = not _app_user_column_exists(cur, "letterhead_access")
    added_documents = not _app_user_column_exists(cur, "documents_access")
    added_bank = not _app_user_column_exists(cur, "bank_access")
    added_tenders = not _app_user_column_exists(cur, "tenders_access")
    added_attendance = not _app_user_column_exists(cur, "attendance_access")
    cur.execute(
        f"ALTER TABLE {APP_USER_TABLE} ADD COLUMN IF NOT EXISTS ods_write BOOLEAN NOT NULL DEFAULT FALSE"
    )
    cur.execute(
        f"ALTER TABLE {APP_USER_TABLE} ADD COLUMN IF NOT EXISTS dw_write BOOLEAN NOT NULL DEFAULT FALSE"
    )
    cur.execute(
        f"ALTER TABLE {APP_USER_TABLE} ADD COLUMN IF NOT EXISTS tally_access BOOLEAN NOT NULL DEFAULT FALSE"
    )
    cur.execute(
        f"ALTER TABLE {APP_USER_TABLE} ADD COLUMN IF NOT EXISTS tally_write BOOLEAN NOT NULL DEFAULT FALSE"
    )
    cur.execute(
        f"ALTER TABLE {APP_USER_TABLE} ADD COLUMN IF NOT EXISTS tally_dw_access BOOLEAN NOT NULL DEFAULT FALSE"
    )
    cur.execute(
        f"ALTER TABLE {APP_USER_TABLE} ADD COLUMN IF NOT EXISTS tally_dw_write BOOLEAN NOT NULL DEFAULT FALSE"
    )
    cur.execute(
        f"ALTER TABLE {APP_USER_TABLE} ADD COLUMN IF NOT EXISTS orion_dashboard_access BOOLEAN NOT NULL DEFAULT TRUE"
    )
    cur.execute(
        f"ALTER TABLE {APP_USER_TABLE} ADD COLUMN IF NOT EXISTS tally_dashboard_access BOOLEAN NOT NULL DEFAULT FALSE"
    )
    for column in ("billing_access", "billing_write", "etl_access", "etl_write", "letterhead_access", "letterhead_write", "documents_access", "documents_write", "bank_access", "bank_write", "tenders_access", "tenders_write", "attendance_access", "attendance_write"):
        cur.execute(f"ALTER TABLE {APP_USER_TABLE} ADD COLUMN IF NOT EXISTS {column} BOOLEAN NOT NULL DEFAULT FALSE")
    # The AI assistant starts on for everyone (it can only use what a person's other permissions allow); an admin can turn it off.
    cur.execute(f"ALTER TABLE {APP_USER_TABLE} ADD COLUMN IF NOT EXISTS ai_access BOOLEAN NOT NULL DEFAULT TRUE")
    if added_billing:
        # Billing used to follow operational data access, so nobody loses it.
        cur.execute(
            f"""
            UPDATE {APP_USER_TABLE}
            SET billing_access = COALESCE(ods_access, FALSE) OR COALESCE(ods_write, FALSE),
                billing_write = COALESCE(ods_write, FALSE)
            """
        )
    if added_etl:
        # Loading used to follow the write flags of the warehouse and the two Tally copies.
        cur.execute(
            f"""
            UPDATE {APP_USER_TABLE}
            SET etl_access = COALESCE(dw_access, FALSE) OR COALESCE(tally_access, FALSE)
                          OR COALESCE(tally_dw_access, FALSE) OR COALESCE(dw_write, FALSE)
                          OR COALESCE(tally_write, FALSE) OR COALESCE(tally_dw_write, FALSE),
                etl_write = COALESCE(dw_write, FALSE) OR COALESCE(tally_write, FALSE)
                         OR COALESCE(tally_dw_write, FALSE)
            """
        )
    if added_letterhead:
        # Letterhead is new, so it follows what a new user of each role gets: admins and editors, not viewers.
        cur.execute(
            f"""
            UPDATE {APP_USER_TABLE}
            SET letterhead_access = role IN ('admin', 'editor'),
                letterhead_write = role IN ('admin', 'editor')
            """
        )
    if added_documents:
        # The Document Center is new too: admins and editors get it, viewers do not.
        cur.execute(
            f"""
            UPDATE {APP_USER_TABLE}
            SET documents_access = role IN ('admin', 'editor'),
                documents_write = role IN ('admin', 'editor')
            """
        )
    if added_bank:
        # Money is the most sensitive thing here: only admins get the Bank at first. Everyone else is given it in Admin.
        cur.execute(
            f"""
            UPDATE {APP_USER_TABLE}
            SET bank_access = role = 'admin',
                bank_write = role = 'admin'
            """
        )
    if added_tenders:
        # Tenders is new: admins and editors get it, as a new user of those roles does; viewers do not.
        cur.execute(
            f"""
            UPDATE {APP_USER_TABLE}
            SET tenders_access = role IN ('admin', 'editor'),
                tenders_write = role IN ('admin', 'editor')
            """
        )
    if added_attendance:
        # Attendance is new: admins and editors get it, as a new user of those roles does; viewers do not.
        cur.execute(
            f"""
            UPDATE {APP_USER_TABLE}
            SET attendance_access = role IN ('admin', 'editor'),
                attendance_write = role IN ('admin', 'editor')
            """
        )
    if added_ods:
        cur.execute(f"UPDATE {APP_USER_TABLE} SET ods_write = COALESCE(ods_access, FALSE)")
    if added_dw:
        cur.execute(f"UPDATE {APP_USER_TABLE} SET dw_write = COALESCE(dw_access, FALSE)")
    if added_tally_access:
        cur.execute(
            f"""
            UPDATE {APP_USER_TABLE}
            SET tally_access = COALESCE(ods_access, FALSE) OR COALESCE(dw_access, FALSE)
            """
        )
    if added_tally_write:
        cur.execute(
            f"""
            UPDATE {APP_USER_TABLE}
            SET tally_write = COALESCE(ods_write, FALSE) OR COALESCE(dw_write, FALSE)
            """
        )
    if added_tally_dw_access:
        cur.execute(
            f"""
            UPDATE {APP_USER_TABLE}
            SET tally_dw_access = COALESCE(tally_access, FALSE)
            """
        )
    if added_tally_dw_write:
        cur.execute(
            f"""
            UPDATE {APP_USER_TABLE}
            SET tally_dw_write = COALESCE(tally_write, FALSE)
            """
        )
    if added_orion_dashboard:
        cur.execute(f"UPDATE {APP_USER_TABLE} SET orion_dashboard_access = TRUE")
    if added_tally_dashboard:
        cur.execute(
            f"""
            UPDATE {APP_USER_TABLE}
            SET tally_dashboard_access = COALESCE(tally_dw_access, FALSE)
                                      OR COALESCE(tally_dw_write, FALSE)
            """
        )
    else:
        # Column already existed with the default FALSE (e.g. added before
        # backfill landed). Copy from Tally DW only while nobody has the
        # dashboard yet, so a later Admin uncheck is not overwritten.
        cur.execute(
            f"SELECT COUNT(*) FROM {APP_USER_TABLE} WHERE COALESCE(tally_dashboard_access, FALSE)"
        )
        if cur.fetchone()[0] == 0:
            cur.execute(
                f"""
                UPDATE {APP_USER_TABLE}
                SET tally_dashboard_access = COALESCE(tally_dw_access, FALSE)
                                          OR COALESCE(tally_dw_write, FALSE)
                """
            )


def _run_as_superuser(fn) -> bool:
    password = env("ORION_POSTGRES_SUPER_PASSWORD")
    if not password:
        return False
    import psycopg2

    settings = {
        **db_settings(),
        "user": env("ORION_POSTGRES_SUPERUSER", "postgres"),
        "password": password,
    }
    conn = psycopg2.connect(**settings)
    cur = conn.cursor()
    try:
        fn(cur)
        conn.commit()
        return True
    except Exception as exc:
        conn.rollback()
        # Expected on a machine where the owner role is not available; say so, without anything that was in the statement.
        logger.warning("A change that needs the database owner could not be made (%s: %s)", type(exc).__name__, str(exc).splitlines()[0][:160] if str(exc) else "")
        return False
    finally:
        cur.close()
        conn.close()


def ensure_user_profile_columns():
    statements = (
        f"ALTER TABLE {APP_USER_TABLE} ADD COLUMN IF NOT EXISTS preferred_theme TEXT",
        f"ALTER TABLE {APP_USER_TABLE} ADD COLUMN IF NOT EXISTS appearance TEXT",
        f"ALTER TABLE {APP_USER_TABLE} ADD COLUMN IF NOT EXISTS avatar_ext TEXT",
        f"""
        ALTER TABLE {APP_USER_TABLE}
        ADD COLUMN IF NOT EXISTS avatar_version INTEGER NOT NULL DEFAULT 0
        """,
        f"ALTER TABLE {APP_USER_TABLE} ADD COLUMN IF NOT EXISTS email TEXT",
        f"ALTER TABLE {APP_USER_TABLE} ADD COLUMN IF NOT EXISTS phone TEXT",
        f"ALTER TABLE {APP_USER_TABLE} ADD COLUMN IF NOT EXISTS password_reset_token TEXT",
        f"ALTER TABLE {APP_USER_TABLE} ADD COLUMN IF NOT EXISTS password_reset_expires TIMESTAMPTZ",
    )
    try:
        with db_cursor(commit=True) as cur:
            for statement in statements:
                cur.execute(statement)
            _apply_user_access_columns(cur)
    except Exception:
        # orion_user is often not the table owner. Try the superuser, then
        # let startup continue so sign-in still works.
        if not _run_as_superuser(lambda cur: (
            [cur.execute(statement) for statement in statements],
            _apply_user_access_columns(cur),
        )):
            return


def validate_display_name(display_name: str) -> Optional[str]:
    name = display_name.strip()
    if not name:
        return "Name is required."
    if len(name) > 80:
        return "Name must be 80 characters or fewer."
    return None


def update_own_profile(
    user_id: int,
    *,
    display_name: Optional[str] = None,
    preferred_theme: Optional[str] = None,
    appearance: Optional[dict] = None,
    email: Optional[str] = None,
    phone: Optional[str] = None,
):
    updates = []
    values = []
    if display_name is not None:
        if err := validate_display_name(display_name):
            raise ValueError(err)
        updates.append("display_name = %s")
        values.append(display_name.strip())
    if preferred_theme is not None:
        if preferred_theme not in THEMES:
            raise ValueError("Theme must be light or dark.")
        updates.append("preferred_theme = %s")
        values.append(preferred_theme)
    if appearance is not None:
        try:
            stored = dump_appearance(appearance)
        except AppearanceError as exc:
            raise ValueError(str(exc)) from exc
        updates.append("appearance = %s")
        values.append(stored)
    if email is not None:
        email_value = _normalize_email(email)
        if err := validate_email(email_value):
            raise ValueError(err)
        updates.append("email = %s")
        values.append(email_value)
    if phone is not None:
        phone_value = _normalize_phone(phone)
        if err := validate_phone(phone_value):
            raise ValueError(err)
        updates.append("phone = %s")
        values.append(phone_value)
    if not updates:
        return fetch_user_by_id(user_id)
    updates.append("updated_timestamp = CURRENT_TIMESTAMP")
    values.append(user_id)
    with db_cursor(commit=True) as cur:
        cur.execute(
            f"UPDATE {APP_USER_TABLE} SET {', '.join(updates)} WHERE id = %s",
            values,
        )
        if cur.rowcount == 0:
            raise ValueError("User not found.")
    return fetch_user_by_id(user_id)


def set_user_avatar(user_id: int, ext: str):
    with db_cursor(commit=True) as cur:
        cur.execute(
            f"""
            UPDATE {APP_USER_TABLE}
            SET avatar_ext = %s,
                avatar_version = COALESCE(avatar_version, 0) + 1,
                updated_timestamp = CURRENT_TIMESTAMP
            WHERE id = %s
            """,
            (ext, user_id),
        )
        if cur.rowcount == 0:
            raise ValueError("User not found.")
    return fetch_user_by_id(user_id)


def clear_user_avatar(user_id: int):
    with db_cursor(commit=True) as cur:
        cur.execute(
            f"""
            UPDATE {APP_USER_TABLE}
            SET avatar_ext = NULL,
                avatar_version = 0,
                updated_timestamp = CURRENT_TIMESTAMP
            WHERE id = %s
            """,
            (user_id,),
        )
        if cur.rowcount == 0:
            raise ValueError("User not found.")
    return fetch_user_by_id(user_id)


def ensure_default_admin():
    if _user_count() > 0:
        return
    username = env("ORION_ADMIN_USERNAME", "admin")
    password = env("ORION_ADMIN_PASSWORD", DEV_ADMIN_PASSWORD)
    if is_production():
        # The first administrator is the one account nobody has approved, so it never gets a published password.
        problem = admin_password_problem(env("ORION_ADMIN_PASSWORD"))
        if problem:
            raise StartupConfigError(f"The first administrator cannot be created: {problem}")
    create_user(username, username.title(), password, role="admin")


_NO_SUCH_USER_HASH: Optional[str] = None


def _hash_nobody_has() -> str:
    """A real bcrypt hash of a password no one has, to check against when the name is unknown (made once, on first use)."""
    global _NO_SUCH_USER_HASH
    if _NO_SUCH_USER_HASH is None:
        _NO_SUCH_USER_HASH = hash_password(secrets.token_urlsafe(16))
    return _NO_SUCH_USER_HASH


def authenticate(username: str, password: str):
    user = _fetch_user_by_username(username.strip())
    # Always spend the same bcrypt check, so a wrong name, a disabled account and a wrong password cannot be told apart by timing.
    matches = verify_password(password, user["password_hash"] if user else _hash_nobody_has())
    if not user or not user["is_active"] or not matches:
        return None
    return _to_session_user(user)


def public_user(user: dict) -> dict:
    user = _normalize_access(dict(user))
    theme = user.get("preferred_theme")
    if theme not in THEMES:
        theme = None
    version = int(user.get("avatar_version") or 0)
    ext = user.get("avatar_ext") or "jpg"
    has_avatar = bool(user.get("has_avatar")) or version > 0
    avatar_url = user.get("avatar_url")
    if has_avatar and not avatar_url:
        avatar_url = f"/api/media/avatars/{user['id']}.{ext}?v={version or 1}"
    created = user.get("created_timestamp")
    return {
        "id": user["id"],
        "username": user["username"],
        "display_name": user["display_name"],
        "role": user["role"],
        # When the account was made: the welcome tour opens by itself for a new one.
        "created_timestamp": created.isoformat() if hasattr(created, "isoformat") else created,
        "ods_access": user["ods_access"],
        "ods_write": user["ods_write"],
        "dw_access": user["dw_access"],
        "dw_write": user["dw_write"],
        "tally_access": user["tally_access"],
        "tally_write": user["tally_write"],
        "tally_dw_access": user["tally_dw_access"],
        "tally_dw_write": user["tally_dw_write"],
        "orion_dashboard_access": user.get("orion_dashboard_access", True),
        "tally_dashboard_access": user.get("tally_dashboard_access", False),
        "billing_access": user["billing_access"],
        "billing_write": user["billing_write"],
        "etl_access": user["etl_access"],
        "etl_write": user["etl_write"],
        "letterhead_access": user["letterhead_access"],
        "letterhead_write": user["letterhead_write"],
        "documents_access": user.get("documents_access", False),
        "documents_write": user.get("documents_write", False),
        "bank_access": user.get("bank_access", False),
        "bank_write": user.get("bank_write", False),
        "tenders_access": user.get("tenders_access", False),
        "tenders_write": user.get("tenders_write", False),
        "attendance_access": user.get("attendance_access", False),
        "attendance_write": user.get("attendance_write", False),
        "ai_access": user.get("ai_access", True),
        "preferred_theme": theme,
        "appearance": load_appearance(user.get("appearance")),
        "has_avatar": has_avatar,
        "avatar_version": version,
        "avatar_url": avatar_url,
        "email": user.get("email"),
        "phone": user.get("phone"),
    }


def _to_session_user(user: dict) -> dict:
    return public_user(user)


def can_access_ods(user: Optional[Dict]) -> bool:
    if not user:
        return False
    if "ods_access" in user or "ods_write" in user:
        return bool(user.get("ods_access") or user.get("ods_write"))
    return user.get("role") in ("admin", "editor")


def can_write_ods(user: Optional[Dict]) -> bool:
    if not user:
        return False
    if "ods_write" in user:
        return bool(user["ods_write"])
    return user.get("role") in ("admin", "editor")


def can_access_dw(user: Optional[Dict]) -> bool:
    if not user:
        return False
    if "dw_access" in user or "dw_write" in user:
        return bool(user.get("dw_access") or user.get("dw_write"))
    return user.get("role") == "admin"


def can_write_dw(user: Optional[Dict]) -> bool:
    if not user:
        return False
    if "dw_write" in user:
        return bool(user["dw_write"])
    return user.get("role") == "admin"


def can_access_tally(user: Optional[Dict]) -> bool:
    if not user:
        return False
    if "tally_access" in user or "tally_write" in user:
        return bool(user.get("tally_access") or user.get("tally_write"))
    return can_access_ods(user) or can_access_dw(user)


def can_write_tally(user: Optional[Dict]) -> bool:
    if not user:
        return False
    if "tally_write" in user:
        return bool(user["tally_write"])
    return can_write_ods(user) or can_write_dw(user)


def can_access_tally_dw(user: Optional[Dict]) -> bool:
    if not user:
        return False
    if "tally_dw_access" in user or "tally_dw_write" in user:
        return bool(user.get("tally_dw_access") or user.get("tally_dw_write"))
    return can_access_tally(user)


def can_write_tally_dw(user: Optional[Dict]) -> bool:
    if not user:
        return False
    if "tally_dw_write" in user:
        return bool(user["tally_dw_write"])
    return can_write_tally(user)


def can_access_orion_dashboard(user: Optional[Dict]) -> bool:
    if not user:
        return False
    if "orion_dashboard_access" in user:
        return bool(user["orion_dashboard_access"])
    return "dashboard" in ROLE_PAGES.get(user.get("role"), set())


def can_access_tally_dashboard(user: Optional[Dict]) -> bool:
    if not user:
        return False
    if "tally_dashboard_access" in user:
        return bool(user["tally_dashboard_access"])
    return can_access_tally_dw(user)


def can_access_billing(user: Optional[Dict]) -> bool:
    if not user:
        return False
    if "billing_access" in user or "billing_write" in user:
        return bool(user.get("billing_access") or user.get("billing_write"))
    return can_access_ods(user)


def can_write_billing(user: Optional[Dict]) -> bool:
    if not user:
        return False
    if "billing_write" in user:
        return bool(user["billing_write"])
    return can_write_ods(user)


def can_access_etl(user: Optional[Dict]) -> bool:
    if not user:
        return False
    if "etl_access" in user or "etl_write" in user:
        return bool(user.get("etl_access") or user.get("etl_write"))
    return can_access_dw(user) or can_access_tally(user) or can_access_tally_dw(user)


def can_write_etl(user: Optional[Dict]) -> bool:
    if not user:
        return False
    if "etl_write" in user:
        return bool(user["etl_write"])
    return can_write_dw(user) or can_write_tally(user) or can_write_tally_dw(user)


def can_access_letterhead(user: Optional[Dict]) -> bool:
    if not user:
        return False
    if "letterhead_access" in user or "letterhead_write" in user:
        return bool(user.get("letterhead_access") or user.get("letterhead_write"))
    return user.get("role") in ("admin", "editor")


def can_write_letterhead(user: Optional[Dict]) -> bool:
    if not user:
        return False
    if "letterhead_write" in user:
        return bool(user["letterhead_write"])
    return user.get("role") in ("admin", "editor")


def can_access_documents(user: Optional[Dict]) -> bool:
    if not user:
        return False
    if "documents_access" in user or "documents_write" in user:
        return bool(user.get("documents_access") or user.get("documents_write"))
    return user.get("role") in ("admin", "editor")


def can_access_bank(user: Optional[Dict]) -> bool:
    """The bank balance and its book. Admins only until someone else is given it in Admin: no flag on the user, no access."""
    if not user:
        return False
    if "bank_access" in user or "bank_write" in user:
        return bool(user.get("bank_access") or user.get("bank_write"))
    return user.get("role") == "admin"


def can_write_bank(user: Optional[Dict]) -> bool:
    if not user:
        return False
    if "bank_write" in user:
        return bool(user["bank_write"])
    return user.get("role") == "admin"


def can_access_tenders(user: Optional[Dict]) -> bool:
    """The GeM tender searches and the bids they found."""
    if not user:
        return False
    if "tenders_access" in user or "tenders_write" in user:
        return bool(user.get("tenders_access") or user.get("tenders_write"))
    return user.get("role") in ("admin", "editor")


def can_write_tenders(user: Optional[Dict]) -> bool:
    """Saving searches, checking GeM now, and shortlisting or dismissing a bid."""
    if not user:
        return False
    if "tenders_write" in user:
        return bool(user["tenders_write"])
    return user.get("role") in ("admin", "editor")


def can_access_attendance(user: Optional[Dict]) -> bool:
    """The attendance registers: who worked at each case in a month, and the pay that follows."""
    if not user:
        return False
    if "attendance_access" in user or "attendance_write" in user:
        return bool(user.get("attendance_access") or user.get("attendance_write"))
    return user.get("role") in ("admin", "editor")


def can_write_attendance(user: Optional[Dict]) -> bool:
    """Making and changing registers, and posting them (which enters the salary lines and expenses)."""
    if not user:
        return False
    if "attendance_write" in user:
        return bool(user["attendance_write"])
    return user.get("role") in ("admin", "editor")


def can_access_ai(user: Optional[Dict]) -> bool:
    """The assistant is on for a person unless an admin turned it off. What it can then do is decided tool by tool."""
    if not user:
        return False
    return bool(user.get("ai_access", True))


def can_write_documents(user: Optional[Dict]) -> bool:
    if not user:
        return False
    if "documents_write" in user:
        return bool(user["documents_write"])
    return user.get("role") in ("admin", "editor")


def can_access_page(user: Optional[Dict], page_id: str) -> bool:
    if not user:
        return False
    if page_id == "data":
        return (
            can_access_ods(user)
            or can_access_dw(user)
            or can_access_tally(user)
            or can_access_tally_dw(user)
        )
    if page_id == "dashboard":
        return can_access_orion_dashboard(user) or can_access_tally_dashboard(user)
    if page_id == "utility":
        return can_access_billing(user)
    if page_id == "etl":
        return can_access_etl(user)
    if page_id == "letterhead":
        return can_access_letterhead(user)
    if page_id == "documents":
        return can_access_documents(user)
    if page_id == "bank":
        return can_access_bank(user)
    if page_id == "tenders":
        return can_access_tenders(user)
    if page_id == "attendance":
        return can_access_attendance(user)
    if page_id == "sql":
        from app import sql_lab  # the editor is for administrators, and may be switched off on this server

        return sql_lab.can_use(user)
    return page_id in ROLE_PAGES.get(user["role"], set())


def is_admin(user: Optional[Dict]) -> bool:
    return bool(user and user.get("role") == "admin")
