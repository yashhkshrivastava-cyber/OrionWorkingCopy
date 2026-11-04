"""What hangs off a task: comments, watchers, the checklist, links to other tasks and to Orion's own records, and time worked.

Each change is one transaction that also writes its line of history and tells the right people. This is the only writer of ``task_comment``, ``task_watcher``,
``task_checklist_item``, ``task_link``, ``task_record_link`` and ``task_time_log``, and of ``task.spent_minutes``.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from app import auth
from app import task_common as common
from app import task_notify as notify
from app.database import db_cursor
from app.idempotency import Idempotency

MAX_COMMENT = 10000
MAX_COMMENTS_PAGE = 200
MAX_WATCHERS = 100

# What each kind of record link needs the person to be allowed to see (so a link never shows what the person cannot open), and how it is found.
RECORD_SOURCES: dict[str, dict[str, Any]] = {
    "bill": {"allowed": auth.can_access_billing, "sql": "SELECT bill_code, 'Bill ' || bill_number FROM orion_ods.bill WHERE bill_code = %s OR bill_number = %s", "twice": True},
    "case": {"allowed": auth.can_access_ods, "sql": 'SELECT case_code, case_name FROM orion_ods."case" WHERE case_code = %s'},
    "client": {"allowed": auth.can_access_ods, "sql": "SELECT client_code, client_name FROM orion_ods.client WHERE client_code = %s"},
    "employee": {"allowed": auth.can_access_ods, "sql": "SELECT employee_code, employee_name FROM orion_ods.employee WHERE employee_code = %s"},
    "opportunity": {"allowed": auth.can_access_ods, "sql": "SELECT opportunity_code, opportunity_name FROM orion_ods.opportunity WHERE opportunity_code = %s"},
    "emd": {"allowed": auth.can_access_ods, "sql": "SELECT emd_code, 'EMD ' || emd_code FROM orion_ods.emd WHERE emd_code = %s"},
    "expense": {"allowed": auth.can_access_ods, "sql": "SELECT expense_code, COALESCE(transaction_description, 'Expense ' || expense_code) FROM orion_ods.expense_transaction WHERE expense_code = %s"},
    "document": {"allowed": auth.can_access_documents, "sql": "SELECT document_id::text, title FROM orion_ods.document WHERE document_id::text = %s AND NOT is_deleted"},
}


def _touch(cur, task_id: int, user_id: int) -> None:
    cur.execute("UPDATE orion_ods.task SET updated_timestamp = clock_timestamp(), updated_by = %s WHERE task_id = %s", (user_id, task_id))


def _interested(cur, task: dict[str, Any]) -> list[int | None]:
    """The people a change to a task concerns: who it is for, who raised it, who reviews it and who watches it."""
    cur.execute("SELECT user_id FROM orion_ods.task_watcher WHERE task_id = %s", (task["task_id"],))
    return [task["assignee_id"], task["reporter_id"], task["reviewer_id"], *[row[0] for row in cur.fetchall()]]


def _watch(cur, task_id: int, user_id: int | None, by: int | None) -> None:
    if user_id is not None:
        cur.execute(
            "INSERT INTO orion_ods.task_watcher (task_id, user_id, added_by) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING", (task_id, user_id, by)
        )


def auto_watch(cur, task_id: int, *user_ids: int | None) -> None:
    """Whoever has something to do with a task follows it, unless they chose otherwise (they can stop)."""
    for uid in user_ids:
        _watch(cur, task_id, uid, None)


# ------------------------------------------------------------------------------------------------------------------------------- comments


def _comment_json(row: dict[str, Any], viewer: dict[str, Any], role: str) -> dict[str, Any]:
    deleted = bool(row["is_deleted"])
    return {
        "id": row["comment_id"], "author": common.person(row, "author"), "body": None if deleted else row["body"], "deleted": deleted,
        "created": common.iso(row["created_timestamp"]), "edited": common.iso(row["edited_timestamp"]),
        "can_edit": (not deleted) and row["author_user"] == viewer["id"],
        "can_delete": (not deleted) and (row["author_user"] == viewer["id"] or role == "Manager"),
    }


def list_comments(user: dict[str, Any], key: str) -> list[dict[str, Any]]:
    with db_cursor() as cur:
        task, _project, role = common.load_task(cur, key, user)
        cur.execute(
            f"""
            SELECT c.comment_id, c.author_id AS author_user, c.body, c.created_timestamp, c.edited_timestamp, c.is_deleted, {common.person_columns('au', 'author')}
              FROM orion_ods.task_comment c LEFT JOIN orion_ods.app_user au ON au.id = c.author_id
             WHERE c.task_id = %s ORDER BY c.created_timestamp, c.comment_id LIMIT %s
            """,
            (task["task_id"], MAX_COMMENTS_PAGE),
        )
        return [_comment_json(row, user, role) for row in common.rows(cur)]


def add_comment(user: dict[str, Any], key: str, body: Any, idem: Idempotency | None = None) -> dict[str, Any]:
    text = common.clean_text(body, MAX_COMMENT, "A comment", required=True, multiline=True)
    with db_cursor(commit=True) as cur:
        if idem is not None:
            prior = idem.claim(cur)
            if prior is not None:
                return prior
        task, project, role = common.load_task(cur, key, user, level="comment", lock=True)
        cur.execute("INSERT INTO orion_ods.task_comment (task_id, author_id, body) VALUES (%s, %s, %s) RETURNING comment_id", (task["task_id"], user["id"], text))
        comment_id = cur.fetchone()[0]
        _touch(cur, task["task_id"], user["id"])
        common.log(cur, project["project_id"], task["task_id"], user["id"], "comment", comment_id=comment_id)
        mentions = [uid for uid in common.mentioned_ids(text) if common.can_see_project_id(cur, project, uid)]
        auto_watch(cur, task["task_id"], user["id"], *mentions)
        cur.execute("SELECT display_name FROM orion_ods.app_user WHERE id = %s", (user["id"],))
        who = cur.fetchone()[0]
        snippet = " ".join(text.split())[:140]
        notify.notify(cur, project, task, "mentioned", user["id"], mentions, f"{who} mentioned you on {task['task_key']}: {snippet}")
        others = [uid for uid in _interested(cur, task) if uid not in mentions]
        notify.notify(cur, project, task, "comment", user["id"], others, f"{who} commented on {task['task_key']}: {snippet}")
        cur.execute(
            f"""
            SELECT c.comment_id, c.author_id AS author_user, c.body, c.created_timestamp, c.edited_timestamp, c.is_deleted, {common.person_columns('au', 'author')}
              FROM orion_ods.task_comment c LEFT JOIN orion_ods.app_user au ON au.id = c.author_id WHERE c.comment_id = %s
            """,
            (comment_id,),
        )
        made = _comment_json(common.one(cur), user, role)
        if idem is not None:
            idem.remember(cur, made)
    return made


def _comment_row(cur, comment_id: int) -> dict[str, Any]:
    cur.execute("SELECT * FROM orion_ods.task_comment WHERE comment_id = %s FOR UPDATE", (comment_id,))
    found = common.one(cur)
    if not found or found["is_deleted"]:
        raise common.NotFound("That comment does not exist.")
    return found


def edit_comment(user: dict[str, Any], comment_id: int, body: Any) -> dict[str, Any]:
    text = common.clean_text(body, MAX_COMMENT, "A comment", required=True, multiline=True)
    with db_cursor(commit=True) as cur:
        comment = _comment_row(cur, comment_id)
        cur.execute("SELECT task_key FROM orion_ods.task WHERE task_id = %s", (comment["task_id"],))
        task, project, _role = common.load_task(cur, cur.fetchone()[0], user, level="comment")
        if comment["author_id"] != user["id"]:
            raise common.Forbidden("Only the person who wrote a comment can change it.")
        cur.execute("UPDATE orion_ods.task_comment SET body = %s, edited_timestamp = CURRENT_TIMESTAMP WHERE comment_id = %s", (text, comment_id))
        common.log(cur, project["project_id"], task["task_id"], user["id"], "comment_edited", comment_id=comment_id)
        new = [uid for uid in common.mentioned_ids(text) if uid not in common.mentioned_ids(comment["body"]) and common.can_see_project_id(cur, project, uid)]
        cur.execute("SELECT display_name FROM orion_ods.app_user WHERE id = %s", (user["id"],))
        notify.notify(cur, project, task, "mentioned", user["id"], new, f"{cur.fetchone()[0]} mentioned you on {task['task_key']}")
        auto_watch(cur, task["task_id"], *new)
    return {"ok": True}


def delete_comment(user: dict[str, Any], comment_id: int) -> dict[str, Any]:
    with db_cursor(commit=True) as cur:
        comment = _comment_row(cur, comment_id)
        cur.execute("SELECT task_key FROM orion_ods.task WHERE task_id = %s", (comment["task_id"],))
        task, project, role = common.load_task(cur, cur.fetchone()[0], user, level="comment")
        if comment["author_id"] != user["id"] and role != "Manager":
            raise common.Forbidden("Only the person who wrote a comment, or a manager, can delete it.")
        cur.execute("UPDATE orion_ods.task_comment SET is_deleted = TRUE, deleted_by = %s WHERE comment_id = %s", (user["id"], comment_id))
        common.log(cur, project["project_id"], task["task_id"], user["id"], "comment_deleted", comment_id=comment_id)
    return {"ok": True}


# ------------------------------------------------------------------------------------------------------------------------------- watchers


def list_watchers(cur, task_id: int) -> list[dict[str, Any]]:
    cur.execute(
        f"SELECT {common.person_columns('u', 'w')} FROM orion_ods.task_watcher w JOIN orion_ods.app_user u ON u.id = w.user_id WHERE w.task_id = %s ORDER BY u.display_name",
        (task_id,),
    )
    return [common.person(row, "w") for row in common.rows(cur)]


def set_watching(user: dict[str, Any], key: str, watching: bool, who: int | None = None) -> list[dict[str, Any]]:
    """Follow or stop following a task. A person does it for themselves; someone who can change the task can add another person."""
    target = who if who is not None else user["id"]
    with db_cursor(commit=True) as cur:
        task, project, _role = common.load_task(cur, key, user, level="edit" if target != user["id"] else "view")
        if target != user["id"] and not common.can_see_project_id(cur, project, target):
            raise common.TaskError("That person cannot see this project.")
        if watching:
            cur.execute("SELECT COUNT(*) FROM orion_ods.task_watcher WHERE task_id = %s", (task["task_id"],))
            if cur.fetchone()[0] >= MAX_WATCHERS:
                raise common.TaskError(f"A task can have at most {MAX_WATCHERS} watchers.")
            _watch(cur, task["task_id"], target, user["id"])
            if target != user["id"]:
                cur.execute("SELECT display_name FROM orion_ods.app_user WHERE id = %s", (user["id"],))
                notify.notify(cur, project, task, "watching", user["id"], [target], f"{cur.fetchone()[0]} added you as a watcher of {task['task_key']}")
        else:
            cur.execute("DELETE FROM orion_ods.task_watcher WHERE task_id = %s AND user_id = %s", (task["task_id"], target))
        return list_watchers(cur, task["task_id"])


# ----------------------------------------------------------------------------------------------------------------------------- checklist


def list_checklist(cur, task_id: int) -> list[dict[str, Any]]:
    cur.execute(
        "SELECT item_id AS id, text, done, position, done_timestamp FROM orion_ods.task_checklist_item WHERE task_id = %s ORDER BY position, item_id", (task_id,)
    )
    return [{**row, "done_timestamp": common.iso(row["done_timestamp"])} for row in common.rows(cur)]


def add_checklist_item(user: dict[str, Any], key: str, text: Any) -> list[dict[str, Any]]:
    clean = common.clean_text(text, 300, "A checklist item", required=True)
    with db_cursor(commit=True) as cur:
        task, project, _role = common.load_task(cur, key, user, level="edit", lock=True)
        cur.execute("SELECT COUNT(*), COALESCE(MAX(position), 0) FROM orion_ods.task_checklist_item WHERE task_id = %s", (task["task_id"],))
        count, last = cur.fetchone()
        if count >= common.MAX_CHECKLIST:
            raise common.TaskError(f"A checklist can have at most {common.MAX_CHECKLIST} items.")
        cur.execute("INSERT INTO orion_ods.task_checklist_item (task_id, text, position) VALUES (%s, %s, %s)", (task["task_id"], clean, last + 1))
        _touch(cur, task["task_id"], user["id"])
        common.log(cur, project["project_id"], task["task_id"], user["id"], "checklist_added", text=clean)
        return list_checklist(cur, task["task_id"])


def _item(cur, item_id: int, user: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    cur.execute("SELECT i.*, t.task_key FROM orion_ods.task_checklist_item i JOIN orion_ods.task t ON t.task_id = i.task_id WHERE i.item_id = %s FOR UPDATE OF i", (item_id,))
    item = common.one(cur)
    if not item:
        raise common.NotFound("That checklist item does not exist.")
    task, project, _role = common.load_task(cur, item["task_key"], user, level="edit")
    return item, task, project


def update_checklist_item(user: dict[str, Any], item_id: int, *, text: Any = None, done: bool | None = None, position: int | None = None) -> list[dict[str, Any]]:
    with db_cursor(commit=True) as cur:
        item, task, project = _item(cur, item_id, user)
        if text is not None:
            clean = common.clean_text(text, 300, "A checklist item", required=True)
            cur.execute("UPDATE orion_ods.task_checklist_item SET text = %s WHERE item_id = %s", (clean, item_id))
        if done is not None and bool(done) != item["done"]:
            cur.execute(
                "UPDATE orion_ods.task_checklist_item SET done = %s, done_by = %s, done_timestamp = CASE WHEN %s THEN CURRENT_TIMESTAMP END WHERE item_id = %s",
                (bool(done), user["id"] if done else None, bool(done), item_id),
            )
            common.log(cur, project["project_id"], task["task_id"], user["id"], "checklist_checked" if done else "checklist_unchecked", text=item["text"])
        if position is not None:
            cur.execute("UPDATE orion_ods.task_checklist_item SET position = %s WHERE item_id = %s", (int(position), item_id))
        _touch(cur, task["task_id"], user["id"])
        return list_checklist(cur, task["task_id"])


def delete_checklist_item(user: dict[str, Any], item_id: int) -> list[dict[str, Any]]:
    with db_cursor(commit=True) as cur:
        item, task, project = _item(cur, item_id, user)
        cur.execute("DELETE FROM orion_ods.task_checklist_item WHERE item_id = %s", (item_id,))
        common.log(cur, project["project_id"], task["task_id"], user["id"], "checklist_removed", text=item["text"])
        _touch(cur, task["task_id"], user["id"])
        return list_checklist(cur, task["task_id"])


# ------------------------------------------------------------------------------------------------------------------------ links between tasks

_LINK_WORDS = {"blocks": ("blocks", False), "blocked_by": ("blocks", True), "relates": ("relates", False), "duplicates": ("duplicates", False), "duplicated_by": ("duplicates", True)}


def list_links(cur, task_id: int) -> list[dict[str, Any]]:
    """The links of a task, each said from this task's side: blocks, is blocked by, relates to, duplicates, is duplicated by."""
    cur.execute(
        """
        SELECT l.link_id AS id, l.kind, (l.from_task_id = %s) AS outgoing, o.task_key, o.title, s.name AS status_name, s.category AS status_category
          FROM orion_ods.task_link l
          JOIN orion_ods.task o ON o.task_id = CASE WHEN l.from_task_id = %s THEN l.to_task_id ELSE l.from_task_id END
          JOIN orion_ods.task_status s ON s.status_id = o.status_id
         WHERE (l.from_task_id = %s OR l.to_task_id = %s) AND NOT o.is_deleted
         ORDER BY l.link_id
        """,
        (task_id, task_id, task_id, task_id),
    )
    out = []
    for row in common.rows(cur):
        side = {("blocks", True): "blocks", ("blocks", False): "blocked_by", ("relates", True): "relates", ("relates", False): "relates",
                ("duplicates", True): "duplicates", ("duplicates", False): "duplicated_by"}[(row["kind"], row["outgoing"])]
        out.append({"id": row["id"], "kind": side, "key": row["task_key"], "title": row["title"], "status": row["status_name"], "done": row["status_category"] == "done"})
    return out


def add_link(user: dict[str, Any], key: str, kind: str, other_key: str) -> list[dict[str, Any]]:
    if kind not in _LINK_WORDS:
        raise common.TaskError("Choose how the tasks are linked.")
    stored, flipped = _LINK_WORDS[kind]
    with db_cursor(commit=True) as cur:
        task, project, _role = common.load_task(cur, key, user, level="edit", lock=True)
        other, _other_project, _r = common.load_task(cur, other_key, user, level="view")
        if other["task_id"] == task["task_id"]:
            raise common.TaskError("A task cannot be linked to itself.")
        source, target = (other, task) if flipped else (task, other)
        if stored == "blocks":
            # a task that already (even through others) waits for the one it would block would wait for itself
            cur.execute(
                """
                WITH RECURSIVE reach(id) AS (
                    SELECT to_task_id FROM orion_ods.task_link WHERE from_task_id = %s AND kind = 'blocks'
                    UNION SELECT l.to_task_id FROM orion_ods.task_link l JOIN reach r ON l.from_task_id = r.id WHERE l.kind = 'blocks'
                ) SELECT 1 FROM reach WHERE id = %s
                """,
                (target["task_id"], source["task_id"]),
            )
            if cur.fetchone():
                raise common.TaskError(f"{target['task_key']} already blocks {source['task_key']}, directly or through other tasks, so that would go round in a circle.")
        cur.execute(
            "INSERT INTO orion_ods.task_link (from_task_id, to_task_id, kind, created_by) VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING RETURNING link_id",
            (source["task_id"], target["task_id"], stored, user["id"]),
        )
        if cur.fetchone():
            common.log(cur, project["project_id"], task["task_id"], user["id"], "link_added", kind=kind, other=other["task_key"])
            common.log(cur, other["project_id"], other["task_id"], user["id"], "link_added", kind={"blocks": "blocked_by", "blocked_by": "blocks", "duplicates": "duplicated_by", "duplicated_by": "duplicates"}.get(kind, kind), other=task["task_key"])
            _touch(cur, task["task_id"], user["id"])
        return list_links(cur, task["task_id"])


def remove_link(user: dict[str, Any], key: str, link_id: int) -> list[dict[str, Any]]:
    with db_cursor(commit=True) as cur:
        task, project, _role = common.load_task(cur, key, user, level="edit", lock=True)
        cur.execute("DELETE FROM orion_ods.task_link WHERE link_id = %s AND (from_task_id = %s OR to_task_id = %s) RETURNING from_task_id, to_task_id, kind", (link_id, task["task_id"], task["task_id"]))
        gone = cur.fetchone()
        if gone:
            common.log(cur, project["project_id"], task["task_id"], user["id"], "link_removed", kind=gone[2])
            _touch(cur, task["task_id"], user["id"])
        return list_links(cur, task["task_id"])


# ------------------------------------------------------------------------------------------------------------------ links to Orion records


def list_record_links(cur, task_id: int, user: dict[str, Any]) -> list[dict[str, Any]]:
    cur.execute("SELECT link_id AS id, record_type, record_ref, label FROM orion_ods.task_record_link WHERE task_id = %s ORDER BY link_id", (task_id,))
    out = []
    for row in common.rows(cur):
        source = RECORD_SOURCES.get(row["record_type"])
        allowed = bool(source and (common.is_admin(user) or source["allowed"](user)))
        out.append({"id": row["id"], "type": row["record_type"], "ref": row["record_ref"] if allowed else None, "label": row["label"] if allowed else None, "restricted": not allowed})
    return out


def add_record_link_in(cur, user: dict[str, Any], task: dict[str, Any], project: dict[str, Any], record_type: str, ref: Any) -> None:
    """Link a record of Orion to a task inside the caller's transaction. The person must be allowed to see that kind of record, and it must exist."""
    source = RECORD_SOURCES.get(record_type)
    if not source:
        raise common.TaskError("That kind of record cannot be linked.")
    reference = common.clean_text(ref, 80, "The record", required=True)
    if not (common.is_admin(user) or source["allowed"](user)):
        raise common.Forbidden("You are not allowed to see that kind of record, so you cannot link it.")
    cur.execute(source["sql"], (reference, reference) if source.get("twice") else (reference,))
    found = cur.fetchone()
    if not found:
        raise common.TaskError("That record does not exist.")
    cur.execute(
        "INSERT INTO orion_ods.task_record_link (task_id, record_type, record_ref, label, created_by) VALUES (%s, %s, %s, %s, %s) ON CONFLICT DO NOTHING RETURNING link_id",
        (task["task_id"], record_type, found[0], str(found[1])[:120], user["id"]),
    )
    if cur.fetchone():
        common.log(cur, project["project_id"], task["task_id"], user["id"], "record_linked", type=record_type, label=str(found[1])[:120])
        _touch(cur, task["task_id"], user["id"])


def add_record_link(user: dict[str, Any], key: str, record_type: str, ref: Any) -> list[dict[str, Any]]:
    with db_cursor(commit=True) as cur:
        task, project, _role = common.load_task(cur, key, user, level="edit", lock=True)
        add_record_link_in(cur, user, task, project, record_type, ref)
        return list_record_links(cur, task["task_id"], user)


def remove_record_link(user: dict[str, Any], key: str, link_id: int) -> list[dict[str, Any]]:
    with db_cursor(commit=True) as cur:
        task, project, _role = common.load_task(cur, key, user, level="edit", lock=True)
        cur.execute("DELETE FROM orion_ods.task_record_link WHERE link_id = %s AND task_id = %s RETURNING record_type, label", (link_id, task["task_id"]))
        gone = cur.fetchone()
        if gone:
            common.log(cur, project["project_id"], task["task_id"], user["id"], "record_unlinked", type=gone[0], label=gone[1])
            _touch(cur, task["task_id"], user["id"])
        return list_record_links(cur, task["task_id"], user)


# --------------------------------------------------------------------------------------------------------------------------------- time


def _recount(cur, task_id: int) -> int:
    cur.execute(
        "UPDATE orion_ods.task SET spent_minutes = (SELECT COALESCE(SUM(minutes), 0) FROM orion_ods.task_time_log WHERE task_id = %s AND NOT is_deleted) WHERE task_id = %s RETURNING spent_minutes",
        (task_id, task_id),
    )
    return cur.fetchone()[0]


def list_time(cur, task_id: int, user: dict[str, Any], role: str) -> dict[str, Any]:
    cur.execute(
        f"""
        SELECT l.log_id AS id, l.minutes, l.work_date, l.note, l.user_id, {common.person_columns('u', 'who')}
          FROM orion_ods.task_time_log l LEFT JOIN orion_ods.app_user u ON u.id = l.user_id
         WHERE l.task_id = %s AND NOT l.is_deleted ORDER BY l.work_date DESC, l.log_id DESC LIMIT 200
        """,
        (task_id,),
    )
    logs = [
        {"id": r["id"], "minutes": r["minutes"], "date": common.iso(r["work_date"]), "note": r["note"], "who": common.person(r, "who"), "can_delete": r["user_id"] == user["id"] or role == "Manager"}
        for r in common.rows(cur)
    ]
    return {"logs": logs, "total": sum(item["minutes"] for item in logs)}


def log_time(user: dict[str, Any], key: str, minutes: Any, work_date: Any = None, note: Any = None) -> dict[str, Any]:
    spent = common.clean_minutes(minutes, "The time", maximum=1440)
    if not spent:
        raise common.TaskError("Say how much time you worked, for example 90 minutes or 1h 30m.")
    day = common.clean_date(work_date, "The day") or date.today()
    if day > date.today():
        raise common.TaskError("The day of the work cannot be in the future.")
    words = common.clean_text(note, 300, "The note")
    with db_cursor(commit=True) as cur:
        task, project, role = common.load_task(cur, key, user, level="edit", lock=True)
        cur.execute("INSERT INTO orion_ods.task_time_log (task_id, user_id, minutes, work_date, note) VALUES (%s, %s, %s, %s, %s)", (task["task_id"], user["id"], spent, day, words))
        total = _recount(cur, task["task_id"])
        _touch(cur, task["task_id"], user["id"])
        common.log(cur, project["project_id"], task["task_id"], user["id"], "time_logged", minutes=spent, date=day.isoformat())
        auto_watch(cur, task["task_id"], user["id"])
        result = list_time(cur, task["task_id"], user, role)
    return {**result, "spent_minutes": total}


def delete_time(user: dict[str, Any], key: str, log_id: int) -> dict[str, Any]:
    with db_cursor(commit=True) as cur:
        task, project, role = common.load_task(cur, key, user, level="edit", lock=True)
        cur.execute("SELECT user_id, minutes FROM orion_ods.task_time_log WHERE log_id = %s AND task_id = %s AND NOT is_deleted FOR UPDATE", (log_id, task["task_id"]))
        found = cur.fetchone()
        if not found:
            raise common.NotFound("That time entry does not exist.")
        if found[0] != user["id"] and role != "Manager":
            raise common.Forbidden("Only the person who logged the time, or a manager, can remove it.")
        cur.execute("UPDATE orion_ods.task_time_log SET is_deleted = TRUE WHERE log_id = %s", (log_id,))
        total = _recount(cur, task["task_id"])
        common.log(cur, project["project_id"], task["task_id"], user["id"], "time_removed", minutes=found[1])
        _touch(cur, task["task_id"], user["id"])
        return {**list_time(cur, task["task_id"], user, role), "spent_minutes": total}


# ------------------------------------------------------------------------------------------------------------------------------- history


def _words(action: str, d: dict[str, Any]) -> str:
    """One line of history in words."""
    field_names = {
        "title": "the title", "description": "the description", "task_type": "the type", "priority": "the priority", "assignee": "the assignee", "reviewer": "the reviewer",
        "parent": "the parent", "sprint": "the sprint", "start_date": "the start date", "due_date": "the due date", "estimate_minutes": "the estimate",
        "story_points": "the story points", "labels": "the labels",
    }
    if action == "created":
        return "created this task"
    if action == "changed":
        parts = []
        for name, change in (d.get("fields") or {}).items():
            label = field_names.get(name, name)
            if name in ("description",):
                parts.append(f"changed {label}")
            else:
                parts.append(f"changed {label} from {change.get('from') or 'nothing'} to {change.get('to') or 'nothing'}")
        return "; ".join(parts) or "changed this task"
    if action == "status":
        return f"moved this from {d.get('from')} to {d.get('to')}" + (f" ({d['resolution']})" if d.get("resolution") else "") + (f": {d['note']}" if d.get("note") else "")
    if action == "comment":
        return "commented"
    if action == "comment_edited":
        return "edited a comment"
    if action == "comment_deleted":
        return "deleted a comment"
    if action == "attachment_added":
        return f"attached {d.get('name')}"
    if action == "attachment_removed":
        return f"removed the attachment {d.get('name')}"
    if action == "link_added":
        return f"linked this task ({str(d.get('kind')).replace('_', ' ')}) {d.get('other')}"
    if action == "link_removed":
        return "removed a link to another task"
    if action == "record_linked":
        return f"linked {d.get('label')}"
    if action == "record_unlinked":
        return f"removed the link to {d.get('label')}"
    if action == "checklist_added":
        return f"added to the checklist: {d.get('text')}"
    if action == "checklist_checked":
        return f"ticked off: {d.get('text')}"
    if action == "checklist_unchecked":
        return f"un-ticked: {d.get('text')}"
    if action == "checklist_removed":
        return f"removed from the checklist: {d.get('text')}"
    if action == "time_logged":
        return f"logged {d.get('minutes')} minutes"
    if action == "time_removed":
        return f"removed {d.get('minutes')} logged minutes"
    if action == "review_requested":
        return f"asked {d.get('reviewer')} to review this" + (f": {d['note']}" if d.get("note") else "")
    if action == "review_approved":
        return "approved this" + (f": {d['note']}" if d.get("note") else "")
    if action == "review_changes":
        return f"asked for changes: {d.get('note')}"
    if action == "review_withdrawn":
        return "withdrew the review request"
    if action == "deleted":
        return "deleted this task"
    if action == "restored":
        return "restored this task"
    if action == "watcher":
        return f"{d.get('what')} a watcher"
    return action.replace("_", " ")


def activity(user: dict[str, Any], key: str, limit: int = 100, before_id: int | None = None) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit or 100), 300))
    with db_cursor() as cur:
        task, _project, _role = common.load_task(cur, key, user)
        params: list[Any] = [task["task_id"]]
        extra = ""
        if before_id:
            extra = " AND a.activity_id < %s"
            params.append(int(before_id))
        cur.execute(
            f"""
            SELECT a.activity_id AS id, a.action, a.detail, a.at, {common.person_columns('u', 'who')}
              FROM orion_ods.task_activity a LEFT JOIN orion_ods.app_user u ON u.id = a.user_id
             WHERE a.task_id = %s{extra} ORDER BY a.activity_id DESC LIMIT %s
            """,
            (*params, limit),
        )
        return [{"id": r["id"], "action": r["action"], "who": common.person(r, "who"), "at": common.iso(r["at"]), "text": _words(r["action"], r["detail"] or {})} for r in common.rows(cur)]

