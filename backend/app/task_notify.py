"""Each person's task inbox: what happened on the work that is theirs or that they watch.

Only people who may see the project are told, never the person who did it. A reminder that a task is due is not stored: it is worked out when the
inbox is read (``reminders``), so it is always about the task as it is now. This is the only writer of ``orion_ods.task_notification``.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Iterable

from app import task_common as common
from app.database import db_cursor

MAX_INBOX = 200
SOON_DAYS = 3

KINDS = (
    "assigned", "mentioned", "comment", "status", "review_requested", "review_approved", "review_changes", "review_withdrawn", "updated", "added_to_project",
    "watching", "attachment",
)


def notify(cur, project: dict[str, Any], task: dict[str, Any] | None, kind: str, actor_id: int | None, recipients: Iterable[int | None], text: str) -> int:
    """Tell people. The actor is never told about their own action, a person is told once, and only people who may see the project are told."""
    wanted: list[int] = []
    for uid in recipients:
        if uid is not None and uid != actor_id and uid not in wanted:
            wanted.append(int(uid))
    if not wanted:
        return 0
    cur.execute(
        """
        SELECT u.id FROM orion_ods.app_user u
         WHERE u.id = ANY(%s) AND u.is_active
           AND (u.role = 'admin' OR %s = 'Company' OR EXISTS (SELECT 1 FROM orion_ods.task_member m WHERE m.project_id = %s AND m.user_id = u.id))
        """,
        (wanted, project["visibility"], project["project_id"]),
    )
    allowed = {row[0] for row in cur.fetchall()}
    made = 0
    for uid in wanted:
        if uid in allowed:
            cur.execute(
                """
                INSERT INTO orion_ods.task_notification (user_id, task_id, project_id, kind, actor_id, text)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (uid, task["task_id"] if task else None, project["project_id"], kind, actor_id, text[:400]),
            )
            made += 1
    return made


def unread_count(user_id: int) -> int:
    with db_cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM orion_ods.task_notification WHERE user_id = %s AND read_timestamp IS NULL", (user_id,))
        return cur.fetchone()[0]


def inbox(user: dict[str, Any], *, unread_only: bool = False, limit: int = 60, before_id: int | None = None) -> dict[str, Any]:
    limit = max(1, min(int(limit or 60), MAX_INBOX))
    where, params = ["n.user_id = %s"], [user["id"]]
    if unread_only:
        where.append("n.read_timestamp IS NULL")
    if before_id:
        where.append("n.notification_id < %s")
        params.append(int(before_id))
    with db_cursor() as cur:
        cur.execute(
            f"""
            SELECT n.notification_id AS id, n.kind, n.text, n.created_timestamp, n.read_timestamp, n.project_id, p.project_key,
                   t.task_key, t.title AS task_title, {common.person_columns('a', 'actor')}
              FROM orion_ods.task_notification n
              LEFT JOIN orion_ods.task t ON t.task_id = n.task_id
              LEFT JOIN orion_ods.task_project p ON p.project_id = n.project_id
              LEFT JOIN orion_ods.app_user a ON a.id = n.actor_id
             WHERE {' AND '.join(where)}
             ORDER BY n.notification_id DESC LIMIT %s
            """,
            (*params, limit),
        )
        items = common.rows(cur)
    out = []
    for row in items:
        out.append(
            {
                "id": row["id"], "kind": row["kind"], "text": row["text"], "created": common.iso(row["created_timestamp"]), "read": row["read_timestamp"] is not None,
                "project_key": row["project_key"], "task_key": row["task_key"], "task_title": row["task_title"], "actor": common.person(row, "actor"),
            }
        )
    return {"items": out, "unread": unread_count(user["id"]), "more": len(items) >= limit}


def mark_read(user: dict[str, Any], ids: list[int] | None = None) -> int:
    """Mark some of the person's notifications read, or all of them (``ids`` empty)."""
    with db_cursor(commit=True) as cur:
        if ids:
            cur.execute(
                "UPDATE orion_ods.task_notification SET read_timestamp = CURRENT_TIMESTAMP WHERE user_id = %s AND notification_id = ANY(%s) AND read_timestamp IS NULL",
                (user["id"], [int(i) for i in ids][:500]),
            )
        else:
            cur.execute("UPDATE orion_ods.task_notification SET read_timestamp = CURRENT_TIMESTAMP WHERE user_id = %s AND read_timestamp IS NULL", (user["id"],))
        return cur.rowcount


def reminders(user: dict[str, Any], today: date | None = None) -> dict[str, Any]:
    """The tasks of this person that are late or due soon, worked out now: their own, still open, in projects they can see."""
    today = today or date.today()
    condition, params = common.visible_sql(user)
    with db_cursor() as cur:
        cur.execute(
            f"""
            SELECT t.task_key, t.title, t.due_date, t.priority, p.project_key, s.name AS status_name
              FROM orion_ods.task t
              JOIN orion_ods.task_project p ON p.project_id = t.project_id
              JOIN orion_ods.task_status s ON s.status_id = t.status_id
             WHERE NOT t.is_deleted AND t.assignee_id = %s AND s.category <> 'done' AND t.due_date IS NOT NULL AND t.due_date <= %s
               AND p.state = 'Active' AND {condition}
             ORDER BY t.due_date, t.task_key LIMIT 100
            """,
            (user["id"], today + timedelta(days=SOON_DAYS), *params),
        )
        found = common.rows(cur)
    overdue = [r for r in found if r["due_date"] < today]
    due_today = [r for r in found if r["due_date"] == today]
    soon = [r for r in found if r["due_date"] > today]
    shape = lambda r: {"key": r["task_key"], "title": r["title"], "due": common.iso(r["due_date"]), "priority": r["priority"], "project_key": r["project_key"], "status": r["status_name"]}  # noqa: E731
    return {"overdue": [shape(r) for r in overdue], "today": [shape(r) for r in due_today], "soon": [shape(r) for r in soon], "count": len(found)}
