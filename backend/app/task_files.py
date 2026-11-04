"""Files attached to tasks (and to comments on them). The same kinds of file, checks and size limit as the Document Center; each different file is kept once.

This is the only writer of ``task_file`` and ``task_attachment``. A file is shown in the browser only when it is a picture or a PDF; anything else is
downloaded, and every answer says ``nosniff`` so the browser never guesses a file into something else.
"""

from __future__ import annotations

import hashlib
from typing import Any

from app import documents
from app import task_common as common
from app import task_items as items
from app import task_notify as notify
from app.database import db_cursor

MAX_PER_TASK = 60


def _clean(file_name: str | None, data: bytes) -> tuple[str, str]:
    try:
        name, _ext, content_type = documents.check_file(file_name, data)
    except documents.DocumentCenterError as exc:
        raise common.TaskError(str(exc)) from exc
    return name, content_type


def list_attachments(cur, task_id: int, user: dict[str, Any], role: str) -> list[dict[str, Any]]:
    cur.execute(
        f"""
        SELECT a.attachment_id AS id, a.comment_id, a.file_name, a.content_type, a.size_bytes, a.uploaded_timestamp, a.uploaded_by, {common.person_columns('u', 'who')}
          FROM orion_ods.task_attachment a LEFT JOIN orion_ods.app_user u ON u.id = a.uploaded_by
         WHERE a.task_id = %s AND NOT a.is_deleted ORDER BY a.attachment_id
        """,
        (task_id,),
    )
    return [
        {"id": r["id"], "comment_id": r["comment_id"], "name": r["file_name"], "type": r["content_type"], "size": r["size_bytes"], "uploaded": common.iso(r["uploaded_timestamp"]),
         "who": common.person(r, "who"), "image": r["content_type"].startswith("image/"), "can_delete": r["uploaded_by"] == user["id"] or role == "Manager"}
        for r in common.rows(cur)
    ]


def attachments(user: dict[str, Any], key: str) -> list[dict[str, Any]]:
    with db_cursor() as cur:
        task, _project, role = common.load_task(cur, key, user)
        return list_attachments(cur, task["task_id"], user, role)


def add_attachment(user: dict[str, Any], key: str, file_name: str | None, data: bytes, comment_id: int | None = None) -> list[dict[str, Any]]:
    name, content_type = _clean(file_name, data)
    digest = hashlib.sha256(data).hexdigest()
    with db_cursor(commit=True) as cur:
        task, project, role = common.load_task(cur, key, user, level="comment", lock=True)
        cur.execute("SELECT COUNT(*) FROM orion_ods.task_attachment WHERE task_id = %s AND NOT is_deleted", (task["task_id"],))
        if cur.fetchone()[0] >= MAX_PER_TASK:
            raise common.TaskError(f"A task can have at most {MAX_PER_TASK} files.")
        if comment_id is not None:
            cur.execute("SELECT 1 FROM orion_ods.task_comment WHERE comment_id = %s AND task_id = %s AND NOT is_deleted", (comment_id, task["task_id"]))
            if not cur.fetchone():
                raise common.NotFound("That comment does not exist.")
        cur.execute("INSERT INTO orion_ods.task_file (sha256, size_bytes, data) VALUES (%s, %s, %s) ON CONFLICT (sha256) DO NOTHING", (digest, len(data), data))
        cur.execute(
            """
            INSERT INTO orion_ods.task_attachment (task_id, comment_id, file_name, content_type, size_bytes, sha256, uploaded_by) VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (task["task_id"], comment_id, name, content_type, len(data), digest, user["id"]),
        )
        cur.execute("UPDATE orion_ods.task SET updated_timestamp = clock_timestamp(), updated_by = %s WHERE task_id = %s", (user["id"], task["task_id"]))
        common.log(cur, project["project_id"], task["task_id"], user["id"], "attachment_added", name=name, size=len(data))
        items.auto_watch(cur, task["task_id"], user["id"])
        cur.execute("SELECT display_name FROM orion_ods.app_user WHERE id = %s", (user["id"],))
        who = cur.fetchone()[0]
        notify.notify(cur, project, task, "attachment", user["id"], items._interested(cur, task), f"{who} attached {name} to {task['task_key']}")
        return list_attachments(cur, task["task_id"], user, role)


def get_file(user: dict[str, Any], attachment_id: int) -> dict[str, Any]:
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT a.file_name, a.content_type, a.task_id, f.data FROM orion_ods.task_attachment a JOIN orion_ods.task_file f ON f.sha256 = a.sha256
             WHERE a.attachment_id = %s AND NOT a.is_deleted
            """,
            (attachment_id,),
        )
        found = cur.fetchone()
        if not found:
            raise common.NotFound("That file does not exist.")
        cur.execute("SELECT task_key FROM orion_ods.task WHERE task_id = %s AND NOT is_deleted", (found[2],))
        key = cur.fetchone()
        if not key:
            raise common.NotFound("That file does not exist.")
        common.load_task(cur, key[0], user)  # the person must be able to see the task
        return {"name": found[0], "content_type": found[1], "data": bytes(found[3]), "inline": documents.is_inline(found[1])}


def delete_attachment(user: dict[str, Any], attachment_id: int) -> list[dict[str, Any]]:
    with db_cursor(commit=True) as cur:
        cur.execute("SELECT a.task_id, a.file_name, a.uploaded_by, t.task_key FROM orion_ods.task_attachment a JOIN orion_ods.task t ON t.task_id = a.task_id WHERE a.attachment_id = %s AND NOT a.is_deleted FOR UPDATE OF a", (attachment_id,))
        found = cur.fetchone()
        if not found:
            raise common.NotFound("That file does not exist.")
        task, project, role = common.load_task(cur, found[3], user, level="comment")
        if found[2] != user["id"] and role != "Manager":
            raise common.Forbidden("Only the person who attached a file, or a manager, can remove it.")
        cur.execute("UPDATE orion_ods.task_attachment SET is_deleted = TRUE, deleted_by = %s, deleted_timestamp = CURRENT_TIMESTAMP WHERE attachment_id = %s", (user["id"], attachment_id))
        common.log(cur, project["project_id"], task["task_id"], user["id"], "attachment_removed", name=found[1])
        # the bytes go when no attachment of any task still uses them
        cur.execute("DELETE FROM orion_ods.task_file f WHERE NOT EXISTS (SELECT 1 FROM orion_ods.task_attachment a WHERE a.sha256 = f.sha256 AND NOT a.is_deleted) AND f.sha256 = (SELECT sha256 FROM orion_ods.task_attachment WHERE attachment_id = %s)", (attachment_id,))
        return list_attachments(cur, task["task_id"], user, role)
