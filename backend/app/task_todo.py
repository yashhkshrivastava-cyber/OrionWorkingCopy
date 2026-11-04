"""A person's own to-do lists: quick items, lists, "My day", due dates, and turning an item into a real task.

They are private. Every query here is for the signed-in person's own rows; no one else's request can reach them, an admin's included. This is the only writer of
``task_todo`` and ``task_todo_list``.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from app import task_common as common
from app import tasks
from app.database import db_cursor
from app.idempotency import Idempotency

MAX_OPEN = 500
MAX_LISTS = 30
KEEP_DONE_DAYS = 14


def _item_json(row: dict[str, Any], today: date) -> dict[str, Any]:
    return {
        "id": row["todo_id"], "list_id": row["list_id"], "text": row["text"], "notes": row["notes"], "done": row["done"], "done_at": common.iso(row["done_timestamp"]),
        "due_date": common.iso(row["due_date"]), "overdue": bool(row["due_date"] and row["due_date"] < today and not row["done"]), "my_day": common.iso(row["my_day"]),
        "in_my_day": row["my_day"] == today, "position": row["position"], "task": {"key": row["task_key"], "title": row["task_title"]} if row["task_key"] else None,
    }


def overview(user: dict[str, Any], today: date | None = None) -> dict[str, Any]:
    today = today or date.today()
    with db_cursor() as cur:
        cur.execute("SELECT list_id AS id, name, position FROM orion_ods.task_todo_list WHERE user_id = %s ORDER BY position, list_id", (user["id"],))
        lists = common.rows(cur)
        cur.execute(
            """
            SELECT d.*, t.task_key, t.title AS task_title FROM orion_ods.task_todo d LEFT JOIN orion_ods.task t ON t.task_id = d.task_id
             WHERE d.user_id = %s AND (NOT d.done OR d.done_timestamp >= CURRENT_TIMESTAMP - make_interval(days => %s))
             ORDER BY d.done, d.position, d.todo_id
            """,
            (user["id"], KEEP_DONE_DAYS),
        )
        items = [_item_json(r, today) for r in common.rows(cur)]
    for entry in lists:
        entry["open"] = sum(1 for i in items if i["list_id"] == entry["id"] and not i["done"])
    return {
        "lists": lists, "items": items, "inbox_open": sum(1 for i in items if i["list_id"] is None and not i["done"]),
        "my_day_open": sum(1 for i in items if i["in_my_day"] and not i["done"]), "today": today.isoformat(), "week": (today + timedelta(days=7)).isoformat(),
    }


def create_list(user: dict[str, Any], name: Any) -> dict[str, Any]:
    label = common.clean_text(name, 60, "The name of the list", required=True)
    with db_cursor(commit=True) as cur:
        cur.execute("SELECT COUNT(*), COALESCE(MAX(position), 0) FROM orion_ods.task_todo_list WHERE user_id = %s", (user["id"],))
        count, last = cur.fetchone()
        if count >= MAX_LISTS:
            raise common.TaskError(f"You can have at most {MAX_LISTS} lists.")
        cur.execute("INSERT INTO orion_ods.task_todo_list (user_id, name, position) VALUES (%s, %s, %s)", (user["id"], label, last + 1))
    return overview(user)


def rename_list(user: dict[str, Any], list_id: int, name: Any) -> dict[str, Any]:
    label = common.clean_text(name, 60, "The name of the list", required=True)
    with db_cursor(commit=True) as cur:
        cur.execute("UPDATE orion_ods.task_todo_list SET name = %s WHERE list_id = %s AND user_id = %s", (label, list_id, user["id"]))
        if not cur.rowcount:
            raise common.NotFound("That list does not exist.")
    return overview(user)


def delete_list(user: dict[str, Any], list_id: int) -> dict[str, Any]:
    """A list goes; what was on it goes back to the plain to-do list."""
    with db_cursor(commit=True) as cur:
        cur.execute("SELECT 1 FROM orion_ods.task_todo_list WHERE list_id = %s AND user_id = %s", (list_id, user["id"]))
        if not cur.fetchone():
            raise common.NotFound("That list does not exist.")
        cur.execute("UPDATE orion_ods.task_todo SET list_id = NULL WHERE list_id = %s AND user_id = %s", (list_id, user["id"]))
        cur.execute("DELETE FROM orion_ods.task_todo_list WHERE list_id = %s AND user_id = %s", (list_id, user["id"]))
    return overview(user)


def _own_list(cur, user: dict[str, Any], list_id: Any) -> int | None:
    if list_id in (None, "", 0):
        return None
    cur.execute("SELECT 1 FROM orion_ods.task_todo_list WHERE list_id = %s AND user_id = %s", (int(list_id), user["id"]))
    if not cur.fetchone():
        raise common.NotFound("That list does not exist.")
    return int(list_id)


def add_item(user: dict[str, Any], data: dict[str, Any], idem: Idempotency | None = None) -> dict[str, Any]:
    text = common.clean_text(data.get("text"), 300, "The item", required=True)
    due = common.clean_date(data.get("due_date"), "The due date")
    my_day = common.clean_date(data.get("my_day"), "The day")
    with db_cursor(commit=True) as cur:
        if idem is not None:
            prior = idem.claim(cur)
            if prior is not None:
                return overview(user)
        list_id = _own_list(cur, user, data.get("list_id"))
        cur.execute("SELECT COUNT(*), COALESCE(MAX(position), 0) FROM orion_ods.task_todo WHERE user_id = %s AND NOT done", (user["id"],))
        count, last = cur.fetchone()
        if count >= MAX_OPEN:
            raise common.TaskError(f"You have {MAX_OPEN} items still open. Finish or clear some first.")
        cur.execute(
            "INSERT INTO orion_ods.task_todo (user_id, list_id, text, notes, due_date, my_day, position) VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING todo_id",
            (user["id"], list_id, text, common.clean_text(data.get("notes"), 2000, "The notes", multiline=True), due, my_day, last + 1),
        )
        todo_id = cur.fetchone()[0]
        if idem is not None:
            idem.remember(cur, {"id": todo_id})
    return overview(user)


def update_item(user: dict[str, Any], todo_id: int, changes: dict[str, Any]) -> dict[str, Any]:
    with db_cursor(commit=True) as cur:
        cur.execute("SELECT * FROM orion_ods.task_todo WHERE todo_id = %s AND user_id = %s FOR UPDATE", (todo_id, user["id"]))
        item = common.one(cur)
        if not item:
            raise common.NotFound("That item does not exist.")
        sets, params = [], []
        if "text" in changes:
            sets.append("text = %s"), params.append(common.clean_text(changes["text"], 300, "The item", required=True))
        if "notes" in changes:
            sets.append("notes = %s"), params.append(common.clean_text(changes["notes"], 2000, "The notes", multiline=True))
        if "due_date" in changes:
            sets.append("due_date = %s"), params.append(common.clean_date(changes["due_date"], "The due date"))
        if "my_day" in changes:
            sets.append("my_day = %s"), params.append(common.clean_date(changes["my_day"], "The day"))
        if "list_id" in changes:
            sets.append("list_id = %s"), params.append(_own_list(cur, user, changes["list_id"]))
        if "position" in changes:
            sets.append("position = %s"), params.append(int(changes["position"]))
        if "done" in changes and bool(changes["done"]) != item["done"]:
            sets.append("done = %s"), params.append(bool(changes["done"]))
            sets.append("done_timestamp = CASE WHEN %s THEN CURRENT_TIMESTAMP END"), params.append(bool(changes["done"]))
        if sets:
            cur.execute(f"UPDATE orion_ods.task_todo SET {', '.join(sets)} WHERE todo_id = %s", (*params, todo_id))
    return overview(user)


def delete_item(user: dict[str, Any], todo_id: int) -> dict[str, Any]:
    with db_cursor(commit=True) as cur:
        cur.execute("DELETE FROM orion_ods.task_todo WHERE todo_id = %s AND user_id = %s", (todo_id, user["id"]))
    return overview(user)


def clear_done(user: dict[str, Any], list_id: Any = None) -> dict[str, Any]:
    with db_cursor(commit=True) as cur:
        if list_id in (None, "", "all"):
            cur.execute("DELETE FROM orion_ods.task_todo WHERE user_id = %s AND done", (user["id"],))
        else:
            cur.execute("DELETE FROM orion_ods.task_todo WHERE user_id = %s AND done AND list_id = %s", (user["id"], int(list_id)))
    return overview(user)


def make_task(user: dict[str, Any], todo_id: int, project_key: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
    """Turn an item into a task of a project (given to its owner unless said otherwise). The item stays, ticked, and says which task it became."""
    extra = data or {}
    with db_cursor() as cur:
        cur.execute("SELECT text, notes, due_date, task_id FROM orion_ods.task_todo WHERE todo_id = %s AND user_id = %s", (todo_id, user["id"]))
        item = cur.fetchone()
    if not item:
        raise common.NotFound("That item does not exist.")
    if item[3]:
        raise common.TaskError("That item is already a task.")
    task = tasks.create_task(
        user, project_key,
        {"title": item[0], "description": item[1], "due_date": item[2], "assignee_id": extra.get("assignee_id", user["id"]), "priority": extra.get("priority") or "Medium",
         "type": extra.get("type") or "Task"},
    )
    with db_cursor(commit=True) as cur:
        cur.execute(
            "UPDATE orion_ods.task_todo SET task_id = %s, done = TRUE, done_timestamp = CURRENT_TIMESTAMP WHERE todo_id = %s AND user_id = %s",
            (task["id"], todo_id, user["id"]),
        )
    return {"task": task, "todo": overview(user)}
