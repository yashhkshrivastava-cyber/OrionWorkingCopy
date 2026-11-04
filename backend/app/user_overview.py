"""What an administrator wants to know about one account besides what it may do: when it was last used, from where, and what work is on it. Read only.

The cookie's random half is never selected: a session is shown by its own number, as the sign-in sessions list does.
"""

from __future__ import annotations

from typing import Any

from app.database import db_cursor

RECENT_SESSIONS = 6


def _plain(value: Any) -> Any:
    return value.isoformat() if hasattr(value, "isoformat") else value


def overview(user_id: int) -> dict[str, Any]:
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*) FILTER (WHERE revoked_timestamp IS NULL AND expires_timestamp > CURRENT_TIMESTAMP) AS active,
                   MAX(last_seen_timestamp) AS last_seen,
                   MAX(created_timestamp) AS last_signed_in
              FROM orion_ods.app_session
             WHERE user_id = %s
            """,
            (user_id,),
        )
        active, last_seen, last_signed_in = cur.fetchone()
        cur.execute(
            """
            SELECT id, created_timestamp, last_seen_timestamp, ip, user_agent,
                   (revoked_timestamp IS NOT NULL OR expires_timestamp <= CURRENT_TIMESTAMP) AS ended
              FROM orion_ods.app_session
             WHERE user_id = %s
             ORDER BY created_timestamp DESC
             LIMIT %s
            """,
            (user_id, RECENT_SESSIONS),
        )
        sessions = [
            {"id": row[0], "signed_in": _plain(row[1]), "last_seen": _plain(row[2]), "ip": row[3], "device": (row[4] or "")[:120], "ended": row[5]}
            for row in cur.fetchall()
        ]
        cur.execute(
            """
            SELECT COUNT(*) FILTER (WHERE s.category <> 'done') AS open,
                   COUNT(*) FILTER (WHERE s.category <> 'done' AND t.due_date < CURRENT_DATE) AS overdue,
                   COUNT(*) FILTER (WHERE s.category = 'review') AS in_review
              FROM orion_ods.task t
              JOIN orion_ods.task_status s ON s.status_id = t.status_id
             WHERE t.assignee_id = %s AND NOT t.is_deleted
            """,
            (user_id,),
        )
        open_tasks, overdue, in_review = cur.fetchone()
        cur.execute("SELECT COUNT(*) FROM orion_ods.task_member WHERE user_id = %s", (user_id,))
        projects = cur.fetchone()[0]
    return {
        "sessions": {"active": int(active or 0), "last_seen": _plain(last_seen), "last_signed_in": _plain(last_signed_in), "recent": sessions},
        "tasks": {"open": int(open_tasks or 0), "overdue": int(overdue or 0), "in_review": int(in_review or 0), "projects": int(projects or 0)},
    }
