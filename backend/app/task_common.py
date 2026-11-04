"""What the task modules share: the errors, the vocabulary, who may do what in a project, and the history every change leaves.

The writers are split by what they own, so each table has one: ``tasks`` (projects, members, statuses, tasks, reviews), ``task_items`` (comments, watchers,
checklists, links, time), ``task_files`` (attachments), ``task_notify`` (the inbox), ``task_todo`` (personal to-do lists), ``task_sprints``,
``task_templates`` (templates and the tasks that come back by themselves) and ``task_views`` (saved filters; everything else there only reads).
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime
from typing import Any

PRIORITIES = ("Critical", "High", "Medium", "Low")
TYPES = ("Task", "Bug", "Story", "Epic", "Sub-task", "Follow-up")
CATEGORIES = ("todo", "doing", "review", "done")
RESOLUTIONS = ("Done", "Won't do", "Duplicate", "Cancelled")
ROLES = ("Manager", "Member", "Viewer")
VISIBILITIES = ("Company", "Private")
LINK_KINDS = ("blocks", "relates", "duplicates")
RECORD_TYPES = ("bill", "case", "client", "employee", "opportunity", "emd", "expense", "document")

#: The workflow a new project starts with: (name, category). "Blocked" is a status of work that has started, not a kind of task.
DEFAULT_STATUSES = (("To Do", "todo"), ("In Progress", "doing"), ("Blocked", "doing"), ("In Review", "review"), ("Done", "done"))

MAX_TITLE = 250
MAX_TEXT = 20000
MAX_LABELS = 12
MAX_LABEL = 30
MAX_CHECKLIST = 100
MAX_BULK = 200
MAX_PAGE = 500
RANK_STEP = 1000.0

MENTION = re.compile(r"@\[([^\]\n]{1,80})\]\(user:(\d+)\)")


class TaskError(ValueError):
    """Something the person can fix: the message is safe to show."""


class NotFound(TaskError):
    pass


class Forbidden(TaskError):
    pass


class Conflict(TaskError):
    """Somebody else changed it since the person opened it."""


def is_admin(user: dict[str, Any]) -> bool:
    return user.get("role") == "admin"


def iso(value: Any) -> str | None:
    if value is None:
        return None
    return value.isoformat() if isinstance(value, (date, datetime)) else str(value)


def person(row: dict[str, Any], prefix: str) -> dict[str, Any] | None:
    """A person as the pages draw them (name and photo), from the columns ``<prefix>_id``, ``_name``, ``_av`` and ``_ext`` of a joined row."""
    uid = row.get(f"{prefix}_id")
    if uid is None:
        return None
    version = int(row.get(f"{prefix}_av") or 0)
    ext = row.get(f"{prefix}_ext") or "jpg"
    return {
        "id": uid,
        "display_name": row.get(f"{prefix}_name") or "Someone",
        "has_avatar": version > 0,
        "avatar_version": version,
        "avatar_url": f"/api/media/avatars/{uid}.{ext}?v={version}" if version > 0 else None,
    }


def person_columns(table: str, prefix: str) -> str:
    return f"{table}.id AS {prefix}_id, {table}.display_name AS {prefix}_name, {table}.avatar_version AS {prefix}_av, {table}.avatar_ext AS {prefix}_ext"


def rows(cur) -> list[dict[str, Any]]:
    names = [col.name for col in cur.description]
    return [dict(zip(names, row)) for row in cur.fetchall()]


def one(cur) -> dict[str, Any] | None:
    row = cur.fetchone()
    return dict(zip([col.name for col in cur.description], row)) if row else None


def clean_text(value: Any, limit: int, label: str, *, required: bool = False, multiline: bool = False) -> str | None:
    text = str(value if value is not None else "")
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
    text = text.strip() if multiline else " ".join(text.split())
    if not text:
        if required:
            raise TaskError(f"{label} is required.")
        return None
    if len(text) > limit:
        raise TaskError(f"{label} can be at most {limit:,} characters.")
    return text


def clean_labels(value: Any) -> list[str]:
    """Labels as people type them (a list), tidied: lower case, spaces to hyphens, no duplicates."""
    if value in (None, ""):
        return []
    if isinstance(value, str):
        value = [part for part in value.split(",")]
    if not isinstance(value, (list, tuple)):
        raise TaskError("Labels are a list of short words.")
    out: list[str] = []
    for raw in value:
        text = re.sub(r"[^a-z0-9._-]", "", re.sub(r"\s+", "-", str(raw).strip().lower()))
        if not text:
            continue
        if len(text) > MAX_LABEL:
            raise TaskError(f"A label can be at most {MAX_LABEL} characters.")
        if text not in out:
            out.append(text)
    if len(out) > MAX_LABELS:
        raise TaskError(f"A task can have at most {MAX_LABELS} labels.")
    return out


def clean_date(value: Any, label: str) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        raise TaskError(f"{label} is not a date.") from None


def clean_minutes(value: Any, label: str, *, maximum: int = 100000) -> int | None:
    if value in (None, ""):
        return None
    try:
        number = int(round(float(value)))
    except (TypeError, ValueError):
        raise TaskError(f"{label} is not a number of minutes.") from None
    if number < 0 or number > maximum:
        raise TaskError(f"{label} must be between 0 and {maximum:,} minutes.")
    return number


def mentioned_ids(*texts: str | None) -> list[int]:
    """The people named with the picker in a text (``@[Name](user:12)``), each once, in order."""
    found: list[int] = []
    for text in texts:
        for _name, uid in MENTION.findall(text or ""):
            if int(uid) not in found:
                found.append(int(uid))
    return found


# --------------------------------------------------------------------------------------------------------------------------- who may do what


def project_row(cur, key: str, *, lock: bool = False) -> dict[str, Any]:
    cur.execute(f"SELECT * FROM orion_ods.task_project WHERE project_key = %s{' FOR UPDATE' if lock else ''}", (str(key or "").strip().upper(),))
    found = one(cur)
    if not found:
        raise NotFound("That project does not exist.")
    return found


def role_in(cur, project: dict[str, Any], user: dict[str, Any]) -> str | None:
    """Manager, Member or Viewer in this project, or None when the person may not see it. An admin manages every project; a company project is open to all."""
    if is_admin(user):
        return "Manager"
    cur.execute("SELECT role FROM orion_ods.task_member WHERE project_id = %s AND user_id = %s", (project["project_id"], user["id"]))
    found = cur.fetchone()
    if found:
        return found[0]
    return "Member" if project["visibility"] == "Company" else None


def need_view(cur, project: dict[str, Any], user: dict[str, Any]) -> str:
    role = role_in(cur, project, user)
    if role is None:
        raise NotFound("That project does not exist.")  # a private project is not even admitted to exist
    return role


def need_edit(cur, project: dict[str, Any], user: dict[str, Any]) -> str:
    role = need_view(cur, project, user)
    if role == "Viewer":
        raise Forbidden("You can look at this project and comment, but not change it.")
    if project["state"] == "Archived" and role != "Manager":
        raise Forbidden("This project is archived.")
    return role


def need_manage(cur, project: dict[str, Any], user: dict[str, Any]) -> str:
    role = need_view(cur, project, user)
    if role != "Manager":
        raise Forbidden("Only a manager of the project can do that.")
    return role


def visible_sql(user: dict[str, Any], alias: str = "p") -> tuple[str, list[Any]]:
    """A SQL condition (and its parameters) that keeps the projects the person may see."""
    if is_admin(user):
        return "TRUE", []
    return (
        f"({alias}.visibility = 'Company' OR EXISTS (SELECT 1 FROM orion_ods.task_member vm WHERE vm.project_id = {alias}.project_id AND vm.user_id = %s))",
        [user["id"]],
    )


def can_work_in(cur, project: dict[str, Any], user_id: int) -> bool:
    """Whether this person can be given work in the project: a member who is not only a viewer, or anyone active when it is a company project."""
    cur.execute("SELECT is_active FROM orion_ods.app_user WHERE id = %s", (user_id,))
    found = cur.fetchone()
    if not found or not found[0]:
        return False
    cur.execute("SELECT role FROM orion_ods.task_member WHERE project_id = %s AND user_id = %s", (project["project_id"], user_id))
    member = cur.fetchone()
    if member:
        return member[0] != "Viewer"
    return project["visibility"] == "Company"


def can_see_project_id(cur, project: dict[str, Any], user_id: int) -> bool:
    cur.execute("SELECT is_active, role FROM orion_ods.app_user WHERE id = %s", (user_id,))
    found = cur.fetchone()
    if not found or not found[0]:
        return False
    if found[1] == "admin" or project["visibility"] == "Company":
        return True
    cur.execute("SELECT 1 FROM orion_ods.task_member WHERE project_id = %s AND user_id = %s", (project["project_id"], user_id))
    return cur.fetchone() is not None


# ----------------------------------------------------------------------------------------------------------------------------------- history


def log(cur, project_id: int, task_id: int | None, user_id: int | None, action: str, **detail: Any) -> None:
    """One line of history. It is never changed or deleted (a trigger holds it)."""
    cur.execute(
        "INSERT INTO orion_ods.task_activity (task_id, project_id, user_id, action, detail) VALUES (%s, %s, %s, %s, %s::jsonb)",
        (task_id, project_id, user_id, action, json.dumps(detail, default=str)),
    )


def load_task(cur, key: str, user: dict[str, Any], *, level: str = "view", lock: bool = False) -> tuple[dict[str, Any], dict[str, Any], str]:
    """The task, its project and the person's role in it, or an error: 404 when it does not exist (or the project is not theirs to see), 403 when the
    role is not enough. ``level`` is what the caller wants to do: view, comment, edit or manage."""
    cur.execute(
        f"""
        SELECT t.*, s.category AS status_category, s.name AS status_name FROM orion_ods.task t
          JOIN orion_ods.task_status s ON s.status_id = t.status_id
         WHERE t.task_key = %s AND NOT t.is_deleted{' FOR UPDATE OF t' if lock else ''}
        """,
        (str(key or "").strip().upper(),),
    )
    task = one(cur)
    if not task:
        raise NotFound("That task does not exist.")
    cur.execute("SELECT * FROM orion_ods.task_project WHERE project_id = %s", (task["project_id"],))
    project = one(cur)
    if level == "view":
        role = need_view(cur, project, user)
    elif level == "comment":
        role = need_view(cur, project, user)
        if project["state"] == "Archived" and role != "Manager":
            raise Forbidden("This project is archived.")
    elif level == "edit":
        role = need_edit(cur, project, user)
    elif level == "manage":
        role = need_manage(cur, project, user)
    else:  # pragma: no cover - a programming error
        raise ValueError(level)
    return task, project, role
