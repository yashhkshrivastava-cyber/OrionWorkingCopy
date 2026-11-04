"""Tasks: projects, their members and workflow, the tasks in them, how they move, and review.

A project has a key (OPS) and a workflow of statuses, each with a category (todo, doing, review, done) that says what it means. A task is named by the
key and a running number (OPS-12). The rules that matter are held here, whatever page or tool asks:

* who may see a project (a company project is open to all; a private one to its members; an admin sees all) and who may change it (a Manager or
  Member; a Viewer reads and comments); an archived project is read-only except to a manager;
* a task is **sent for review** by moving it into a review status: it needs a reviewer other than the person who does the work; the reviewer approves it
  (it is done) or asks for changes (back to work, with a reason). A project can require that every task is reviewed before it is done;
* a task is **done** only when nothing blocks it and its sub-tasks are done; it then has a resolution and the time it was resolved;
* a task is never deleted for good: it is hidden, with who and when, and everything that happened to it stays in its history.

This is the only writer of ``task_project``, ``task_member``, ``task_status``, ``task`` and ``task_review``. The people, comments, files and the rest of what
hangs off a task are written by their own modules.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any

from app import task_common as common
from app import task_items as items
from app import task_notify as notify
from app.database import db_cursor
from app.idempotency import Idempotency

MAX_STATUSES = 12
MAX_PROJECTS_SHOWN = 300
SORTS = {
    "key": "t.task_no", "title": "lower(t.title)", "priority": "CASE t.priority WHEN 'Critical' THEN 1 WHEN 'High' THEN 2 WHEN 'Medium' THEN 3 ELSE 4 END",
    "due": "t.due_date", "updated": "t.updated_timestamp", "created": "t.created_timestamp", "rank": "t.rank", "status": "s.position",
    "assignee": "lower(au.display_name)", "project": "p.project_key",
}

TASK_COLUMNS = f"""
    t.task_id, t.task_key, t.task_no, t.project_id, p.project_key, p.name AS project_name, p.require_review, p.state AS project_state, p.visibility,
    t.title, t.description, t.task_type, t.priority, t.status_id, s.name AS status_name, s.category AS status_category, s.position AS status_position,
    t.assignee_id, t.reporter_id, t.reviewer_id, t.parent_id, pt.task_key AS parent_key, pt.title AS parent_title, pt.task_type AS parent_type,
    t.sprint_id, sp.name AS sprint_name, sp.state AS sprint_state, t.template_id, t.start_date, t.due_date, t.estimate_minutes, t.spent_minutes, t.story_points,
    t.labels, t.rank, t.resolution, t.resolved_timestamp, t.created_timestamp, t.updated_timestamp,
    {common.person_columns('au', 'assignee')}, {common.person_columns('ru', 'reporter')}, {common.person_columns('vu', 'reviewer')},
    (SELECT COUNT(*) FROM orion_ods.task c WHERE c.parent_id = t.task_id AND NOT c.is_deleted) AS sub_count,
    (SELECT COUNT(*) FROM orion_ods.task c JOIN orion_ods.task_status cs ON cs.status_id = c.status_id WHERE c.parent_id = t.task_id AND NOT c.is_deleted AND cs.category = 'done') AS sub_done,
    (SELECT COUNT(*) FROM orion_ods.task_checklist_item i WHERE i.task_id = t.task_id) AS check_count,
    (SELECT COUNT(*) FROM orion_ods.task_checklist_item i WHERE i.task_id = t.task_id AND i.done) AS check_done,
    (SELECT COUNT(*) FROM orion_ods.task_comment c WHERE c.task_id = t.task_id AND NOT c.is_deleted) AS comment_count,
    (SELECT COUNT(*) FROM orion_ods.task_attachment a WHERE a.task_id = t.task_id AND NOT a.is_deleted) AS attachment_count,
    (SELECT COALESCE(array_agg(b.task_key ORDER BY b.task_no), '{{}}') FROM orion_ods.task_link l JOIN orion_ods.task b ON b.task_id = l.from_task_id
       JOIN orion_ods.task_status bs ON bs.status_id = b.status_id WHERE l.to_task_id = t.task_id AND l.kind = 'blocks' AND NOT b.is_deleted AND bs.category <> 'done') AS blockers
"""
TASK_FROM = """
    FROM orion_ods.task t
    JOIN orion_ods.task_project p ON p.project_id = t.project_id
    JOIN orion_ods.task_status s ON s.status_id = t.status_id
    LEFT JOIN orion_ods.task pt ON pt.task_id = t.parent_id
    LEFT JOIN orion_ods.task_sprint sp ON sp.sprint_id = t.sprint_id
    LEFT JOIN orion_ods.app_user au ON au.id = t.assignee_id
    LEFT JOIN orion_ods.app_user ru ON ru.id = t.reporter_id
    LEFT JOIN orion_ods.app_user vu ON vu.id = t.reviewer_id
"""


def task_json(row: dict[str, Any], today: date | None = None) -> dict[str, Any]:
    """A task as a list or a board card shows it."""
    today = today or date.today()
    due = row["due_date"]
    done = row["status_category"] == "done"
    return {
        "id": row["task_id"], "key": row["task_key"], "project_key": row["project_key"], "project_name": row["project_name"], "title": row["title"], "type": row["task_type"],
        "priority": row["priority"], "status": {"id": row["status_id"], "name": row["status_name"], "category": row["status_category"]},
        "assignee": common.person(row, "assignee"), "reporter": common.person(row, "reporter"), "reviewer": common.person(row, "reviewer"),
        "parent": {"key": row["parent_key"], "title": row["parent_title"], "type": row["parent_type"]} if row["parent_key"] else None,
        "sprint": {"id": row["sprint_id"], "name": row["sprint_name"], "state": row["sprint_state"]} if row["sprint_id"] else None,
        "start_date": common.iso(row["start_date"]), "due_date": common.iso(due), "overdue": bool(due and due < today and not done),
        "estimate_minutes": row["estimate_minutes"], "spent_minutes": row["spent_minutes"], "story_points": float(row["story_points"]) if row["story_points"] is not None else None,
        "labels": list(row["labels"] or []), "rank": row["rank"], "resolution": row["resolution"], "resolved": common.iso(row["resolved_timestamp"]),
        "created": common.iso(row["created_timestamp"]), "updated": common.iso(row["updated_timestamp"]),
        "subtasks": {"total": row["sub_count"], "done": row["sub_done"]}, "checklist": {"total": row["check_count"], "done": row["check_done"]},
        "comments": row["comment_count"], "attachments": row["attachment_count"], "blocked_by": list(row["blockers"] or []), "recurring": row["template_id"] is not None,
    }


# ----------------------------------------------------------------------------------------------------------------------------- people


def people(user: dict[str, Any], project_key: str | None = None) -> list[dict[str, Any]]:
    """The people who can be chosen as an assignee or reviewer or mentioned: everyone active, or for a private project its members and the admins."""
    with db_cursor() as cur:
        if project_key:
            project = common.project_row(cur, project_key)
            common.need_view(cur, project, user)
            cur.execute(
                f"""
                SELECT {common.person_columns('u', 'p')}, u.username, u.role FROM orion_ods.app_user u
                 WHERE u.is_active AND (u.role = 'admin' OR %s = 'Company' OR EXISTS (SELECT 1 FROM orion_ods.task_member m WHERE m.project_id = %s AND m.user_id = u.id))
                 ORDER BY lower(u.display_name)
                """,
                (project["visibility"], project["project_id"]),
            )
        else:
            cur.execute(f"SELECT {common.person_columns('u', 'p')}, u.username, u.role FROM orion_ods.app_user u WHERE u.is_active ORDER BY lower(u.display_name)")
        return [{**common.person(r, "p"), "username": r["username"], "role": r["role"]} for r in common.rows(cur)]


# --------------------------------------------------------------------------------------------------------------------------- projects


def _project_json(row: dict[str, Any], role: str | None) -> dict[str, Any]:
    return {
        "key": row["project_key"], "name": row["name"], "description": row["description"], "visibility": row["visibility"], "state": row["state"],
        "require_review": row["require_review"], "color": row["color"], "lead": common.person(row, "lead"), "role": role, "created": common.iso(row["created_timestamp"]),
    }


def list_projects(user: dict[str, Any], *, include_archived: bool = False) -> list[dict[str, Any]]:
    condition, params = common.visible_sql(user)
    with db_cursor() as cur:
        cur.execute(
            f"""
            SELECT p.*, {common.person_columns('lu', 'lead')}, m.role AS my_role,
                   (SELECT COUNT(*) FROM orion_ods.task t JOIN orion_ods.task_status s ON s.status_id = t.status_id WHERE t.project_id = p.project_id AND NOT t.is_deleted AND s.category <> 'done') AS open_tasks,
                   (SELECT COUNT(*) FROM orion_ods.task t JOIN orion_ods.task_status s ON s.status_id = t.status_id WHERE t.project_id = p.project_id AND NOT t.is_deleted AND s.category = 'done') AS done_tasks,
                   (SELECT COUNT(*) FROM orion_ods.task t JOIN orion_ods.task_status s ON s.status_id = t.status_id WHERE t.project_id = p.project_id AND NOT t.is_deleted AND s.category <> 'done' AND t.due_date < CURRENT_DATE) AS overdue_tasks,
                   (SELECT COUNT(*) FROM orion_ods.task t JOIN orion_ods.task_status s ON s.status_id = t.status_id WHERE t.project_id = p.project_id AND NOT t.is_deleted AND s.category <> 'done' AND t.assignee_id = %s) AS my_open_tasks,
                   (SELECT MAX(a.at) FROM orion_ods.task_activity a WHERE a.project_id = p.project_id) AS last_activity,
                   (SELECT COUNT(*) FROM orion_ods.task_member mm WHERE mm.project_id = p.project_id) AS member_count
              FROM orion_ods.task_project p
              LEFT JOIN orion_ods.app_user lu ON lu.id = p.lead_id
              LEFT JOIN orion_ods.task_member m ON m.project_id = p.project_id AND m.user_id = %s
             WHERE {condition}{'' if include_archived else " AND p.state = 'Active'"}
             ORDER BY (m.user_id IS NOT NULL) DESC, lower(p.name) LIMIT {MAX_PROJECTS_SHOWN}
            """,
            (user["id"], user["id"], *params),
        )
        out = []
        for row in common.rows(cur):
            role = "Manager" if common.is_admin(user) else row["my_role"] or ("Member" if row["visibility"] == "Company" else None)
            out.append({**_project_json(row, role), "open_tasks": row["open_tasks"], "done_tasks": row["done_tasks"], "overdue_tasks": row["overdue_tasks"], "my_open_tasks": row["my_open_tasks"],
                        "members": row["member_count"], "last_activity": common.iso(row["last_activity"])})
        return out


def _statuses(cur, project_id: int) -> list[dict[str, Any]]:
    cur.execute(
        """
        SELECT s.status_id AS id, s.name, s.category, s.position, s.wip_limit,
               (SELECT COUNT(*) FROM orion_ods.task t WHERE t.status_id = s.status_id AND NOT t.is_deleted) AS tasks
          FROM orion_ods.task_status s WHERE s.project_id = %s ORDER BY s.position, s.status_id
        """,
        (project_id,),
    )
    return common.rows(cur)


def _members(cur, project_id: int) -> list[dict[str, Any]]:
    cur.execute(
        f"SELECT {common.person_columns('u', 'm')}, m.role FROM orion_ods.task_member m JOIN orion_ods.app_user u ON u.id = m.user_id WHERE m.project_id = %s ORDER BY (m.role = 'Manager') DESC, lower(u.display_name)",
        (project_id,),
    )
    return [{**common.person(r, "m"), "role": r["role"]} for r in common.rows(cur)]


def get_project(user: dict[str, Any], key: str) -> dict[str, Any]:
    with db_cursor() as cur:
        project = common.project_row(cur, key)
        role = common.need_view(cur, project, user)
        cur.execute(f"SELECT {common.person_columns('lu', 'lead')} FROM orion_ods.app_user lu WHERE lu.id = %s", (project["lead_id"],))
        lead = common.one(cur) or {}
        return {**_project_json({**project, **lead}, role), "statuses": _statuses(cur, project["project_id"]), "members": _members(cur, project["project_id"])}


def create_project(user: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    key = str(data.get("key") or "").strip().upper()
    if not re.fullmatch(r"[A-Z][A-Z0-9]{1,9}", key):
        raise common.TaskError("The key is 2 to 10 capital letters or digits, starting with a letter, for example OPS.")
    name = common.clean_text(data.get("name"), 120, "The name", required=True)
    description = common.clean_text(data.get("description"), 4000, "The description", multiline=True)
    visibility = data.get("visibility") or "Company"
    if visibility not in common.VISIBILITIES:
        raise common.TaskError("A project is open to the company or private to its members.")
    with db_cursor(commit=True) as cur:
        cur.execute("SELECT 1 FROM orion_ods.task_project WHERE project_key = %s", (key,))
        if cur.fetchone():
            raise common.TaskError(f"The key {key} is already used by another project.")
        cur.execute(
            """
            INSERT INTO orion_ods.task_project (project_key, name, description, lead_id, visibility, require_review, color, created_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING project_id
            """,
            (key, name, description, user["id"], visibility, bool(data.get("require_review")), common.clean_text(data.get("color"), 20, "The colour"), user["id"]),
        )
        project_id = cur.fetchone()[0]
        for position, (status_name, category) in enumerate(common.DEFAULT_STATUSES, start=1):
            cur.execute("INSERT INTO orion_ods.task_status (project_id, name, category, position) VALUES (%s, %s, %s, %s)", (project_id, status_name, category, position))
        cur.execute("INSERT INTO orion_ods.task_member (project_id, user_id, role, added_by) VALUES (%s, %s, 'Manager', %s)", (project_id, user["id"], user["id"]))
        common.log(cur, project_id, None, user["id"], "project_created", name=name)
    return get_project(user, key)


def update_project(user: dict[str, Any], key: str, data: dict[str, Any]) -> dict[str, Any]:
    with db_cursor(commit=True) as cur:
        project = common.project_row(cur, key, lock=True)
        common.need_manage(cur, project, user)
        sets, params, changed = [], [], {}
        if "name" in data:
            name = common.clean_text(data["name"], 120, "The name", required=True)
            sets.append("name = %s"), params.append(name)
            changed["name"] = name
        if "description" in data:
            sets.append("description = %s"), params.append(common.clean_text(data["description"], 4000, "The description", multiline=True))
        if "visibility" in data:
            if data["visibility"] not in common.VISIBILITIES:
                raise common.TaskError("A project is open to the company or private to its members.")
            sets.append("visibility = %s"), params.append(data["visibility"])
            changed["visibility"] = data["visibility"]
        if "require_review" in data:
            sets.append("require_review = %s"), params.append(bool(data["require_review"]))
            changed["require_review"] = bool(data["require_review"])
        if "color" in data:
            sets.append("color = %s"), params.append(common.clean_text(data["color"], 20, "The colour"))
        if "lead_id" in data:
            lead = int(data["lead_id"]) if data["lead_id"] not in (None, "") else None
            if lead is not None and not common.can_see_project_id(cur, project, lead):
                raise common.TaskError("The lead must be someone who can see the project.")
            sets.append("lead_id = %s"), params.append(lead)
            changed["lead"] = lead
        if sets:
            cur.execute(f"UPDATE orion_ods.task_project SET {', '.join(sets)}, updated_timestamp = clock_timestamp() WHERE project_id = %s", (*params, project["project_id"]))
            common.log(cur, project["project_id"], None, user["id"], "project_changed", **changed)
    return get_project(user, key)


def set_archived(user: dict[str, Any], key: str, archived: bool) -> dict[str, Any]:
    with db_cursor(commit=True) as cur:
        project = common.project_row(cur, key, lock=True)
        common.need_manage(cur, project, user)
        cur.execute("UPDATE orion_ods.task_project SET state = %s, updated_timestamp = clock_timestamp() WHERE project_id = %s", ("Archived" if archived else "Active", project["project_id"]))
        common.log(cur, project["project_id"], None, user["id"], "project_archived" if archived else "project_restored")
    return get_project(user, key)


def set_member(user: dict[str, Any], key: str, member_id: int, role: str | None) -> list[dict[str, Any]]:
    """Add a person to the project, change their role, or (role empty) take them out. A project always keeps a manager."""
    if role not in (None, *common.ROLES):
        raise common.TaskError("A member is a Manager, a Member or a Viewer.")
    with db_cursor(commit=True) as cur:
        project = common.project_row(cur, key, lock=True)
        common.need_manage(cur, project, user)
        cur.execute("SELECT is_active FROM orion_ods.app_user WHERE id = %s", (member_id,))
        found = cur.fetchone()
        if not found or not found[0]:
            raise common.TaskError("That person is not an active user.")
        cur.execute("SELECT role FROM orion_ods.task_member WHERE project_id = %s AND user_id = %s", (project["project_id"], member_id))
        before = cur.fetchone()
        if role is None:
            if before and before[0] == "Manager":
                cur.execute("SELECT COUNT(*) FROM orion_ods.task_member WHERE project_id = %s AND role = 'Manager'", (project["project_id"],))
                if cur.fetchone()[0] <= 1:
                    raise common.TaskError("A project needs at least one manager. Make someone else a manager first.")
            cur.execute("DELETE FROM orion_ods.task_member WHERE project_id = %s AND user_id = %s", (project["project_id"], member_id))
            common.log(cur, project["project_id"], None, user["id"], "member_removed", user=member_id)
        else:
            if before and before[0] == "Manager" and role != "Manager":
                cur.execute("SELECT COUNT(*) FROM orion_ods.task_member WHERE project_id = %s AND role = 'Manager'", (project["project_id"],))
                if cur.fetchone()[0] <= 1:
                    raise common.TaskError("A project needs at least one manager. Make someone else a manager first.")
            cur.execute(
                "INSERT INTO orion_ods.task_member (project_id, user_id, role, added_by) VALUES (%s, %s, %s, %s) ON CONFLICT (project_id, user_id) DO UPDATE SET role = EXCLUDED.role",
                (project["project_id"], member_id, role, user["id"]),
            )
            common.log(cur, project["project_id"], None, user["id"], "member_set", user=member_id, role=role)
            if not before:
                cur.execute("SELECT display_name FROM orion_ods.app_user WHERE id = %s", (user["id"],))
                notify.notify(cur, project, None, "added_to_project", user["id"], [member_id], f"{cur.fetchone()[0]} added you to the project {project['name']} ({project['project_key']}) as {role}")
        return _members(cur, project["project_id"])


def add_status(user: dict[str, Any], key: str, name: Any, category: str) -> list[dict[str, Any]]:
    label = common.clean_text(name, 40, "The name of the status", required=True)
    if category not in common.CATEGORIES:
        raise common.TaskError("Say what kind of status it is: to do, doing, review or done.")
    with db_cursor(commit=True) as cur:
        project = common.project_row(cur, key, lock=True)
        common.need_manage(cur, project, user)
        existing = _statuses(cur, project["project_id"])
        if len(existing) >= MAX_STATUSES:
            raise common.TaskError(f"A project can have at most {MAX_STATUSES} statuses.")
        if any(s["name"].lower() == label.lower() for s in existing):
            raise common.TaskError(f"There is already a status called {label}.")
        # it goes at the end of its kind, so the columns stay in the order of the work
        order = ["todo", "doing", "review", "done"]
        position = 1 + max([s["position"] for s in existing if order.index(s["category"]) <= order.index(category)] or [0])
        cur.execute("UPDATE orion_ods.task_status SET position = position + 1 WHERE project_id = %s AND position >= %s", (project["project_id"], position))
        cur.execute("INSERT INTO orion_ods.task_status (project_id, name, category, position) VALUES (%s, %s, %s, %s)", (project["project_id"], label, category, position))
        common.log(cur, project["project_id"], None, user["id"], "status_added", name=label, category=category)
        return _statuses(cur, project["project_id"])


def update_status(user: dict[str, Any], key: str, status_id: int, changes: dict[str, Any]) -> list[dict[str, Any]]:
    with db_cursor(commit=True) as cur:
        project = common.project_row(cur, key, lock=True)
        common.need_manage(cur, project, user)
        statuses = _statuses(cur, project["project_id"])
        current = next((s for s in statuses if s["id"] == status_id), None)
        if not current:
            raise common.NotFound("That status does not exist in this project.")
        sets, params = [], []
        if "name" in changes:
            label = common.clean_text(changes["name"], 40, "The name of the status", required=True)
            if any(s["name"].lower() == label.lower() and s["id"] != status_id for s in statuses):
                raise common.TaskError(f"There is already a status called {label}.")
            sets.append("name = %s"), params.append(label)
        if "category" in changes and changes["category"] != current["category"]:
            if changes["category"] not in common.CATEGORIES:
                raise common.TaskError("Say what kind of status it is: to do, doing, review or done.")
            if (current["category"] == "done") != (changes["category"] == "done") and current["tasks"]:
                raise common.TaskError("Tasks are in that status. Move them first: a task is done or not depending on its status.")
            others = [s for s in statuses if s["id"] != status_id]
            for needed in ("todo", "done"):
                if current["category"] == needed and not any(s["category"] == needed for s in others):
                    raise common.TaskError(f"A project needs a {needed} status.")
            sets.append("category = %s"), params.append(changes["category"])
        if "wip_limit" in changes:
            limit = changes["wip_limit"]
            sets.append("wip_limit = %s"), params.append(int(limit) if limit not in (None, "", 0) else None)
        if sets:
            cur.execute(f"UPDATE orion_ods.task_status SET {', '.join(sets)} WHERE status_id = %s", (*params, status_id))
            common.log(cur, project["project_id"], None, user["id"], "status_changed", status=current["name"], changes={k: v for k, v in changes.items()})
        return _statuses(cur, project["project_id"])


def reorder_statuses(user: dict[str, Any], key: str, ids: list[int]) -> list[dict[str, Any]]:
    with db_cursor(commit=True) as cur:
        project = common.project_row(cur, key, lock=True)
        common.need_manage(cur, project, user)
        existing = {s["id"] for s in _statuses(cur, project["project_id"])}
        if set(ids) != existing or len(ids) != len(existing):
            raise common.TaskError("Give every status of the project once.")
        for position, status_id in enumerate(ids, start=1):
            cur.execute("UPDATE orion_ods.task_status SET position = %s WHERE status_id = %s", (position, status_id))
        common.log(cur, project["project_id"], None, user["id"], "statuses_reordered")
        return _statuses(cur, project["project_id"])


def delete_status(user: dict[str, Any], key: str, status_id: int, move_to: int | None) -> list[dict[str, Any]]:
    with db_cursor(commit=True) as cur:
        project = common.project_row(cur, key, lock=True)
        common.need_manage(cur, project, user)
        statuses = _statuses(cur, project["project_id"])
        current = next((s for s in statuses if s["id"] == status_id), None)
        if not current:
            raise common.NotFound("That status does not exist in this project.")
        others = [s for s in statuses if s["id"] != status_id]
        for needed in ("todo", "done"):
            if current["category"] == needed and not any(s["category"] == needed for s in others):
                raise common.TaskError(f"A project needs a {needed} status, so the last one cannot be deleted.")
        if current["tasks"]:
            target = next((s for s in others if s["id"] == move_to), None)
            if not target:
                raise common.TaskError("Tasks are in that status. Say which status to move them to.")
            if (target["category"] == "done") != (current["category"] == "done"):
                raise common.TaskError("Move the tasks to a status of the same kind (done or not done).")
            cur.execute("UPDATE orion_ods.task SET status_id = %s WHERE status_id = %s", (target["id"], status_id))
        cur.execute("DELETE FROM orion_ods.task_status WHERE status_id = %s", (status_id,))
        common.log(cur, project["project_id"], None, user["id"], "status_deleted", name=current["name"])
        return _statuses(cur, project["project_id"])


# ------------------------------------------------------------------------------------------------------------------------------ reading


def _task_row(cur, key: str, user: dict[str, Any]) -> dict[str, Any]:
    task, _project, _role = common.load_task(cur, key, user)
    cur.execute(f"SELECT {TASK_COLUMNS} {TASK_FROM} WHERE t.task_id = %s", (task["task_id"],))
    return common.one(cur)


def _reviews(cur, task_id: int) -> list[dict[str, Any]]:
    cur.execute(
        f"""
        SELECT r.review_id AS id, r.status, r.request_note, r.decision_note, r.requested_timestamp, r.decided_timestamp,
               {common.person_columns('qu', 'requester')}, {common.person_columns('ru', 'reviewer')}
          FROM orion_ods.task_review r LEFT JOIN orion_ods.app_user qu ON qu.id = r.requested_by LEFT JOIN orion_ods.app_user ru ON ru.id = r.reviewer_id
         WHERE r.task_id = %s ORDER BY r.review_id DESC LIMIT 20
        """,
        (task_id,),
    )
    return [
        {"id": r["id"], "status": r["status"], "request_note": r["request_note"], "decision_note": r["decision_note"], "requested": common.iso(r["requested_timestamp"]),
         "decided": common.iso(r["decided_timestamp"]), "requester": common.person(r, "requester"), "reviewer": common.person(r, "reviewer")}
        for r in common.rows(cur)
    ]


def get_task(user: dict[str, Any], key: str) -> dict[str, Any]:
    """Everything the task page shows, except the comments, the history and the files' contents (those are read on their own)."""
    with db_cursor() as cur:
        task, project, role = common.load_task(cur, key, user)
        cur.execute(f"SELECT {TASK_COLUMNS} {TASK_FROM} WHERE t.task_id = %s", (task["task_id"],))
        row = common.one(cur)
        out = task_json(row)
        cur.execute(
            f"SELECT {TASK_COLUMNS} {TASK_FROM} WHERE t.parent_id = %s AND NOT t.is_deleted ORDER BY t.rank, t.task_no",
            (task["task_id"],),
        )
        subtasks = [task_json(r) for r in common.rows(cur)]
        reviews = _reviews(cur, task["task_id"])
        pending = next((r for r in reviews if r["status"] == "Pending"), None)
        can_change = role in ("Manager", "Member") and (project["state"] == "Active" or role == "Manager")
        cur.execute("SELECT COUNT(*) FROM orion_ods.task_watcher WHERE task_id = %s AND user_id = %s", (task["task_id"], user["id"]))
        watching = cur.fetchone()[0] > 0
        out.update(
            {
                "description": row["description"], "project": {"key": project["project_key"], "name": project["name"], "state": project["state"], "require_review": project["require_review"],
                                                               "visibility": project["visibility"]},
                "statuses": _statuses(cur, project["project_id"]), "subtask_list": subtasks, "checklist_items": items.list_checklist(cur, task["task_id"]),
                "links": items.list_links(cur, task["task_id"]), "records": items.list_record_links(cur, task["task_id"], user), "watchers": items.list_watchers(cur, task["task_id"]),
                "time": items.list_time(cur, task["task_id"], user, role), "reviews": reviews, "pending_review": pending,
                "permissions": {
                    "role": role, "can_edit": can_change, "can_manage": role == "Manager", "can_comment": project["state"] == "Active" or role == "Manager",
                    "can_decide_review": bool(pending and (pending["reviewer"] and pending["reviewer"]["id"] == user["id"] or role == "Manager")),
                    "can_delete": role == "Manager" or task["reporter_id"] == user["id"],
                },
                "watching": watching,
            }
        )
        return out


def list_tasks(user: dict[str, Any], filters: dict[str, Any] | None = None) -> dict[str, Any]:
    """Tasks the person may see, narrowed by ``filters`` (projects, people, statuses, priority, labels, dates, text) and sorted. Every value is a parameter
    and every column is chosen from a fixed list, so what is sent can never become SQL."""
    f = filters or {}
    today = date.today()
    condition, params = common.visible_sql(user)
    where = ["NOT t.is_deleted", condition]

    def many(name: str) -> list[str]:
        value = f.get(name)
        if value in (None, ""):
            return []
        return [str(v) for v in (value if isinstance(value, (list, tuple)) else str(value).split(",")) if str(v) != ""]

    def people_filter(column: str, name: str) -> None:
        wanted = many(name)
        if not wanted:
            return
        ids = [user["id"] if w == "me" else int(w) for w in wanted if w not in ("none",) and (w == "me" or w.lstrip("-").isdigit())]
        parts, args = [], []
        if ids:
            parts.append(f"{column} = ANY(%s)")
            args.append(ids)
        if "none" in wanted:
            parts.append(f"{column} IS NULL")
        if parts:
            where.append("(" + " OR ".join(parts) + ")")
            params.extend(args)

    if many("project"):
        where.append("p.project_key = ANY(%s)")
        params.append([k.upper() for k in many("project")])
    elif not f.get("include_archived"):
        where.append("p.state = 'Active'")
    people_filter("t.assignee_id", "assignee")
    people_filter("t.reporter_id", "reporter")
    people_filter("t.reviewer_id", "reviewer")
    if many("status_id"):
        where.append("t.status_id = ANY(%s)")
        params.append([int(v) for v in many("status_id") if v.isdigit()])
    if many("category"):
        where.append("s.category = ANY(%s)")
        params.append([c for c in many("category") if c in common.CATEGORIES])
    if f.get("open") in (True, "true", "1", 1):
        where.append("s.category <> 'done'")
    if f.get("done") in (True, "true", "1", 1):
        where.append("s.category = 'done'")
    if many("priority"):
        where.append("t.priority = ANY(%s)")
        params.append([v for v in many("priority") if v in common.PRIORITIES])
    if many("type"):
        where.append("t.task_type = ANY(%s)")
        params.append([v for v in many("type") if v in common.TYPES])
    if many("label"):
        where.append("t.labels && %s::text[]")
        params.append([v.lower() for v in many("label")])
    if f.get("q"):
        text = str(f["q"]).strip()[:100]
        like = "%" + text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        where.append("(t.title ILIKE %s OR t.task_key ILIKE %s OR t.description ILIKE %s)")
        params.extend([like, like, like])
    due = f.get("due")
    if due == "overdue":
        where.append("t.due_date < %s AND s.category <> 'done'")
        params.append(today)
    elif due == "today":
        where.append("t.due_date = %s")
        params.append(today)
    elif due == "week":
        where.append("t.due_date BETWEEN %s AND %s")
        params.extend([today, today + timedelta(days=7)])
    elif due == "none":
        where.append("t.due_date IS NULL")
    elif due == "any":
        where.append("t.due_date IS NOT NULL")
    if f.get("due_from"):
        where.append("t.due_date >= %s")
        params.append(common.clean_date(f["due_from"], "The date"))
    if f.get("due_to"):
        where.append("t.due_date <= %s")
        params.append(common.clean_date(f["due_to"], "The date"))
    sprint = f.get("sprint")
    if sprint == "none":
        where.append("t.sprint_id IS NULL")
    elif sprint == "active":
        where.append("sp.state = 'Active'")
    elif sprint not in (None, "") and str(sprint).isdigit():
        where.append("t.sprint_id = %s")
        params.append(int(sprint))
    if f.get("parent"):
        where.append("pt.task_key = %s")
        params.append(str(f["parent"]).upper())
    if f.get("no_parent") in (True, "true", "1", 1):
        where.append("t.parent_id IS NULL")
    if f.get("watching") in (True, "true", "1", 1):
        where.append("EXISTS (SELECT 1 FROM orion_ods.task_watcher w WHERE w.task_id = t.task_id AND w.user_id = %s)")
        params.append(user["id"])
    if f.get("involves_me") in (True, "true", "1", 1):
        where.append("(t.assignee_id = %s OR t.reporter_id = %s OR t.reviewer_id = %s)")
        params.extend([user["id"]] * 3)
    if f.get("record_type") and f.get("record_ref"):
        where.append("EXISTS (SELECT 1 FROM orion_ods.task_record_link rl WHERE rl.task_id = t.task_id AND rl.record_type = %s AND rl.record_ref = %s)")
        params.extend([str(f["record_type"]), str(f["record_ref"])])
    sort = SORTS.get(str(f.get("sort") or "rank"), SORTS["rank"])
    direction = "DESC" if str(f.get("dir") or "").lower() == "desc" else "ASC"
    nulls = " NULLS LAST" if "due_date" in sort else ""
    limit = max(1, min(int(f.get("limit") or 200), common.MAX_PAGE))
    offset = max(0, int(f.get("offset") or 0))
    with db_cursor() as cur:
        cur.execute(f"SELECT COUNT(*) {TASK_FROM} WHERE {' AND '.join(where)}", params)
        total = cur.fetchone()[0]
        cur.execute(
            f"SELECT {TASK_COLUMNS} {TASK_FROM} WHERE {' AND '.join(where)} ORDER BY {sort} {direction}{nulls}, t.task_id LIMIT %s OFFSET %s",
            (*params, limit, offset),
        )
        return {"tasks": [task_json(r, today) for r in common.rows(cur)], "total": total, "limit": limit, "offset": offset}


# ------------------------------------------------------------------------------------------------------------------------------ writing


def _status_of(cur, project_id: int, status_id: int | None, category: str | None = None) -> dict[str, Any]:
    if status_id is not None:
        cur.execute("SELECT * FROM orion_ods.task_status WHERE status_id = %s AND project_id = %s", (status_id, project_id))
    else:
        cur.execute("SELECT * FROM orion_ods.task_status WHERE project_id = %s AND category = %s ORDER BY position, status_id LIMIT 1", (project_id, category))
    found = common.one(cur)
    if not found:
        raise common.TaskError("That status does not exist in this project." if status_id is not None else f"This project has no {category} status.")
    return found


def _bottom_rank(cur, project_id: int, status_id: int) -> float:
    cur.execute("SELECT COALESCE(MAX(rank), 0) FROM orion_ods.task WHERE project_id = %s AND status_id = %s AND NOT is_deleted", (project_id, status_id))
    return float(cur.fetchone()[0]) + common.RANK_STEP


def _check_person(cur, project: dict[str, Any], uid: Any, label: str, *, works: bool) -> int | None:
    if uid in (None, "", 0):
        return None
    uid = int(uid)
    ok = common.can_work_in(cur, project, uid) if works else common.can_see_project_id(cur, project, uid)
    if not ok:
        raise common.TaskError(f"{label} must be an active person who {'can work in' if works else 'can see'} this project.")
    return uid


def _check_parent(cur, project: dict[str, Any], parent_key: Any, task_type: str, task_id: int | None) -> int | None:
    if parent_key in (None, ""):
        return None
    cur.execute("SELECT task_id, project_id, task_type, parent_id FROM orion_ods.task WHERE task_key = %s AND NOT is_deleted", (str(parent_key).upper(),))
    found = cur.fetchone()
    if not found or found[1] != project["project_id"]:
        raise common.TaskError("The parent must be a task of the same project.")
    if task_type == "Epic":
        raise common.TaskError("An epic stands on its own: it cannot belong to another task.")
    if found[2] == "Sub-task":
        raise common.TaskError("A sub-task cannot have sub-tasks of its own.")
    if task_id is not None:
        ancestor = found[0]
        for _ in range(20):
            if ancestor == task_id:
                raise common.TaskError("A task cannot be under itself or under one of its own sub-tasks.")
            cur.execute("SELECT parent_id FROM orion_ods.task WHERE task_id = %s", (ancestor,))
            nxt = cur.fetchone()
            if not nxt or nxt[0] is None:
                break
            ancestor = nxt[0]
    return found[0]


def _check_sprint(cur, project: dict[str, Any], sprint_id: Any) -> int | None:
    if sprint_id in (None, "", 0):
        return None
    cur.execute("SELECT project_id, state FROM orion_ods.task_sprint WHERE sprint_id = %s", (int(sprint_id),))
    found = cur.fetchone()
    if not found or found[0] != project["project_id"]:
        raise common.TaskError("That sprint does not belong to this project.")
    if found[1] == "Completed":
        raise common.TaskError("That sprint is finished: choose one that is planned or active.")
    return int(sprint_id)


def insert_task(cur, project: dict[str, Any], reporter_id: int | None, data: dict[str, Any], *, template_id: int | None = None) -> dict[str, Any]:
    """Make a task in the project (the caller has checked the person may). Returns the stored row."""
    title = common.clean_text(data.get("title"), common.MAX_TITLE, "The title", required=True)
    description = common.clean_text(data.get("description"), common.MAX_TEXT, "The description", multiline=True)
    task_type = data.get("type") or data.get("task_type") or "Task"
    if task_type not in common.TYPES:
        raise common.TaskError("Choose the type of task from the list.")
    priority = data.get("priority") or "Medium"
    if priority not in common.PRIORITIES:
        raise common.TaskError("Choose the priority from the list.")
    status = _status_of(cur, project["project_id"], int(data["status_id"]), None) if data.get("status_id") else _status_of(cur, project["project_id"], None, "todo")
    assignee = _check_person(cur, project, data.get("assignee_id"), "The assignee", works=True)
    reviewer = _check_person(cur, project, data.get("reviewer_id"), "The reviewer", works=False)
    if reviewer is not None and reviewer == assignee:
        raise common.TaskError("The reviewer must be someone other than the person doing the work.")
    parent = _check_parent(cur, project, data.get("parent_key") or data.get("parent"), "Sub-task" if task_type == "Sub-task" else task_type, None)
    if task_type == "Sub-task" and parent is None:
        raise common.TaskError("A sub-task belongs to a task: say which one.")
    sprint = _check_sprint(cur, project, data.get("sprint_id"))
    start, due = common.clean_date(data.get("start_date"), "The start date"), common.clean_date(data.get("due_date"), "The due date")
    if start and due and due < start:
        raise common.TaskError("The due date cannot be before the start date.")
    points = data.get("story_points")
    cur.execute("UPDATE orion_ods.task_project SET next_no = next_no + 1 WHERE project_id = %s RETURNING next_no - 1", (project["project_id"],))
    number = cur.fetchone()[0]
    key = f"{project['project_key']}-{number}"
    cur.execute(
        """
        INSERT INTO orion_ods.task (project_id, task_no, task_key, title, description, task_type, priority, status_id, assignee_id, reporter_id, reviewer_id, parent_id, sprint_id,
                                    template_id, start_date, due_date, estimate_minutes, story_points, labels, rank, updated_by)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING task_id
        """,
        (project["project_id"], number, key, title, description, task_type, priority, status["status_id"], assignee, reporter_id, reviewer, parent, sprint, template_id, start, due,
         common.clean_minutes(data.get("estimate_minutes"), "The estimate"), float(points) if points not in (None, "") else None, common.clean_labels(data.get("labels")),
         _bottom_rank(cur, project["project_id"], status["status_id"]), reporter_id),
    )
    task_id = cur.fetchone()[0]
    for position, text in enumerate([t for t in (data.get("checklist") or []) if str(t).strip()][: common.MAX_CHECKLIST], start=1):
        cur.execute("INSERT INTO orion_ods.task_checklist_item (task_id, text, position) VALUES (%s, %s, %s)", (task_id, common.clean_text(text, 300, "A checklist item", required=True), position))
    items.auto_watch(cur, task_id, reporter_id, assignee, reviewer)
    common.log(cur, project["project_id"], task_id, reporter_id, "created", title=title)
    cur.execute("SELECT * FROM orion_ods.task WHERE task_id = %s", (task_id,))
    row = common.one(cur)
    who = None
    if reporter_id is not None:
        cur.execute("SELECT display_name FROM orion_ods.app_user WHERE id = %s", (reporter_id,))
        who = (cur.fetchone() or [None])[0]
    if assignee and assignee != reporter_id:
        notify.notify(cur, project, row, "assigned", reporter_id, [assignee], f"{who or 'The system'} assigned {key} to you: {title}")
    mentions = [uid for uid in common.mentioned_ids(description) if common.can_see_project_id(cur, project, uid)]
    items.auto_watch(cur, task_id, *mentions)
    notify.notify(cur, project, row, "mentioned", reporter_id, mentions, f"{who or 'Someone'} mentioned you on {key}")
    return row


def create_task(user: dict[str, Any], project_key: str, data: dict[str, Any], idem: Idempotency | None = None) -> dict[str, Any]:
    with db_cursor(commit=True) as cur:
        if idem is not None:
            prior = idem.claim(cur)
            if prior is not None:
                return get_task(user, prior["key"])
        project = common.project_row(cur, project_key, lock=True)
        common.need_edit(cur, project, user)
        row = insert_task(cur, project, user["id"], data)
        for record in data.get("records") or []:  # links to Orion's records, when a page makes a task about one
            if isinstance(record, dict):
                items.add_record_link_in(cur, user, row, project, str(record.get("type")), str(record.get("ref")))
        if idem is not None:
            idem.remember(cur, {"key": row["task_key"]})
        key = row["task_key"]
    return get_task(user, key)


_EDITABLE = ("title", "description", "task_type", "priority", "assignee_id", "reviewer_id", "parent_key", "sprint_id", "start_date", "due_date", "estimate_minutes", "story_points", "labels")


def _name(cur, uid: int | None) -> str | None:
    if uid is None:
        return None
    cur.execute("SELECT display_name FROM orion_ods.app_user WHERE id = %s", (uid,))
    found = cur.fetchone()
    return found[0] if found else f"user {uid}"


def update_task(user: dict[str, Any], key: str, changes: dict[str, Any], expected_updated: str | None = None) -> dict[str, Any]:
    """Change fields of a task. With ``expected_updated`` (when the person opened it) nothing is written if someone else saved since."""
    unknown = [name for name in changes if name not in _EDITABLE and name != "type"]
    if unknown:
        raise common.TaskError(f"Cannot change {', '.join(unknown)} here.")
    if "type" in changes:
        changes = {**{k: v for k, v in changes.items() if k != "type"}, "task_type": changes["type"]}
    with db_cursor(commit=True) as cur:
        task, project, _role = common.load_task(cur, key, user, level="edit", lock=True)
        if expected_updated and common.iso(task["updated_timestamp"]) != expected_updated:
            raise common.Conflict("Someone else changed this task while you had it open. Reload it to see their change, then make yours again.")
        sets: list[str] = []
        params: list[Any] = []
        diff: dict[str, dict[str, Any]] = {}

        def put(column: str, label: str, new: Any, old: Any, show_new: Any = None, show_old: Any = None) -> None:
            if new == old:
                return
            sets.append(f"{column} = %s")
            params.append(new)
            diff[label] = {"from": show_old if show_old is not None else old, "to": show_new if show_new is not None else new}

        if "title" in changes:
            put("title", "title", common.clean_text(changes["title"], common.MAX_TITLE, "The title", required=True), task["title"])
        if "description" in changes:
            new = common.clean_text(changes["description"], common.MAX_TEXT, "The description", multiline=True)
            put("description", "description", new, task["description"], "…", "…")
        task_type = task["task_type"]
        if "task_type" in changes:
            if changes["task_type"] not in common.TYPES:
                raise common.TaskError("Choose the type of task from the list.")
            task_type = changes["task_type"]
            put("task_type", "task_type", task_type, task["task_type"])
        if "priority" in changes:
            if changes["priority"] not in common.PRIORITIES:
                raise common.TaskError("Choose the priority from the list.")
            put("priority", "priority", changes["priority"], task["priority"])
        if "assignee_id" in changes:
            new = _check_person(cur, project, changes["assignee_id"], "The assignee", works=True)
            if new is not None and new == task["reviewer_id"] and "reviewer_id" not in changes:
                raise common.TaskError("The assignee cannot also be the reviewer. Choose another reviewer first.")
            put("assignee_id", "assignee", new, task["assignee_id"], _name(cur, new), _name(cur, task["assignee_id"]))
        if "reviewer_id" in changes:
            new = _check_person(cur, project, changes["reviewer_id"], "The reviewer", works=False)
            assignee_after = _check_person(cur, project, changes["assignee_id"], "The assignee", works=True) if "assignee_id" in changes else task["assignee_id"]
            if new is not None and new == assignee_after:
                raise common.TaskError("The reviewer must be someone other than the person doing the work.")
            if new is None and task["status_category"] == "review":
                raise common.TaskError("This task is in review: it needs a reviewer.")
            put("reviewer_id", "reviewer", new, task["reviewer_id"], _name(cur, new), _name(cur, task["reviewer_id"]))
        if "parent_key" in changes or "task_type" in changes:
            parent_key = changes.get("parent_key")
            if "parent_key" not in changes:
                parent_key = None
                if task["parent_id"]:
                    cur.execute("SELECT task_key FROM orion_ods.task WHERE task_id = %s", (task["parent_id"],))
                    parent_key = cur.fetchone()[0]
            new = _check_parent(cur, project, parent_key, task_type, task["task_id"])
            if task_type == "Sub-task" and new is None:
                raise common.TaskError("A sub-task belongs to a task: say which one.")
            if "parent_key" in changes:
                put("parent_id", "parent", new, task["parent_id"], str(parent_key).upper() if parent_key else None)
        if "sprint_id" in changes:
            new = _check_sprint(cur, project, changes["sprint_id"])
            cur.execute("SELECT name FROM orion_ods.task_sprint WHERE sprint_id = %s", (new,))
            new_name = (cur.fetchone() or [None])[0]
            cur.execute("SELECT name FROM orion_ods.task_sprint WHERE sprint_id = %s", (task["sprint_id"],))
            put("sprint_id", "sprint", new, task["sprint_id"], new_name, (cur.fetchone() or [None])[0])
        start = common.clean_date(changes["start_date"], "The start date") if "start_date" in changes else task["start_date"]
        due = common.clean_date(changes["due_date"], "The due date") if "due_date" in changes else task["due_date"]
        if start and due and due < start:
            raise common.TaskError("The due date cannot be before the start date.")
        if "start_date" in changes:
            put("start_date", "start_date", start, task["start_date"], start.isoformat() if start else None, task["start_date"].isoformat() if task["start_date"] else None)
        if "due_date" in changes:
            put("due_date", "due_date", due, task["due_date"], due.isoformat() if due else None, task["due_date"].isoformat() if task["due_date"] else None)
        if "estimate_minutes" in changes:
            put("estimate_minutes", "estimate_minutes", common.clean_minutes(changes["estimate_minutes"], "The estimate"), task["estimate_minutes"])
        if "story_points" in changes:
            raw = changes["story_points"]
            put("story_points", "story_points", float(raw) if raw not in (None, "") else None, float(task["story_points"]) if task["story_points"] is not None else None)
        if "labels" in changes:
            new = common.clean_labels(changes["labels"])
            put("labels", "labels", new, list(task["labels"] or []), ", ".join(new), ", ".join(task["labels"] or []))
        if not sets:
            return get_task(user, key)
        cur.execute(f"UPDATE orion_ods.task SET {', '.join(sets)}, updated_timestamp = clock_timestamp(), updated_by = %s WHERE task_id = %s", (*params, user["id"], task["task_id"]))
        common.log(cur, project["project_id"], task["task_id"], user["id"], "changed", fields=diff)
        who = _name(cur, user["id"])
        if "assignee" in diff and diff["assignee"]["to"]:
            new_assignee = [params[sets.index("assignee_id = %s")]][0]
            items.auto_watch(cur, task["task_id"], new_assignee)
            notify.notify(cur, project, task, "assigned", user["id"], [new_assignee], f"{who} assigned {task['task_key']} to you: {task['title']}")
        if "reviewer" in diff:
            items.auto_watch(cur, task["task_id"], params[sets.index("reviewer_id = %s")])
        new_text = changes.get("description")
        if new_text is not None:
            mentions = [u for u in common.mentioned_ids(new_text) if u not in common.mentioned_ids(task["description"]) and common.can_see_project_id(cur, project, u)]
            items.auto_watch(cur, task["task_id"], *mentions)
            notify.notify(cur, project, task, "mentioned", user["id"], mentions, f"{who} mentioned you on {task['task_key']}")
        cur.execute("SELECT * FROM orion_ods.task WHERE task_id = %s", (task["task_id"],))
        fresh = common.one(cur)
        names = ", ".join(sorted(diff))
        told = [uid for uid in items._interested(cur, fresh) if not (("assignee" in diff) and uid == fresh["assignee_id"])]
        notify.notify(cur, project, task, "updated", user["id"], told, f"{who} changed {names} on {task['task_key']}: {task['title']}")
    return get_task(user, key)


# --------------------------------------------------------------------------------------------------------------------- moving and review


def _blockers(cur, task_id: int) -> list[str]:
    cur.execute(
        """
        SELECT b.task_key FROM orion_ods.task_link l JOIN orion_ods.task b ON b.task_id = l.from_task_id JOIN orion_ods.task_status bs ON bs.status_id = b.status_id
         WHERE l.to_task_id = %s AND l.kind = 'blocks' AND NOT b.is_deleted AND bs.category <> 'done' ORDER BY b.task_no
        """,
        (task_id,),
    )
    return [r[0] for r in cur.fetchall()]


def _open_subtasks(cur, task_id: int) -> list[str]:
    cur.execute(
        "SELECT c.task_key FROM orion_ods.task c JOIN orion_ods.task_status cs ON cs.status_id = c.status_id WHERE c.parent_id = %s AND NOT c.is_deleted AND cs.category <> 'done' ORDER BY c.task_no",
        (task_id,),
    )
    return [r[0] for r in cur.fetchall()]


def _pending_review(cur, task_id: int, lock: bool = False) -> dict[str, Any] | None:
    cur.execute(f"SELECT * FROM orion_ods.task_review WHERE task_id = %s AND status = 'Pending'{' FOR UPDATE' if lock else ''}", (task_id,))
    return common.one(cur)


def _midpoint_rank(cur, project_id: int, status_id: int, task_id: int, before_key: str | None, after_key: str | None) -> float:
    """A rank that puts the task just above ``before_key`` or just below ``after_key`` in the column, or at the bottom of it. Renumbers the column if the gap is gone."""
    def rank_of(key: str | None) -> float | None:
        if not key:
            return None
        cur.execute("SELECT rank FROM orion_ods.task WHERE task_key = %s AND project_id = %s AND status_id = %s AND task_id <> %s AND NOT is_deleted", (str(key).upper(), project_id, status_id, task_id))
        found = cur.fetchone()
        return float(found[0]) if found else None

    upper, lower = rank_of(before_key), rank_of(after_key)
    if upper is None and lower is None:
        return _bottom_rank(cur, project_id, status_id)
    if upper is not None:  # above the task named in before_key
        cur.execute("SELECT COALESCE(MAX(rank), 0) FROM orion_ods.task WHERE project_id = %s AND status_id = %s AND task_id <> %s AND NOT is_deleted AND rank < %s", (project_id, status_id, task_id, upper))
        below = float(cur.fetchone()[0])
        if upper - below < 1e-6:
            _renumber(cur, project_id, status_id, task_id)
            return _midpoint_rank(cur, project_id, status_id, task_id, before_key, None)
        return (upper + below) / 2 if below else upper - common.RANK_STEP / 2
    cur.execute("SELECT MIN(rank) FROM orion_ods.task WHERE project_id = %s AND status_id = %s AND task_id <> %s AND NOT is_deleted AND rank > %s", (project_id, status_id, task_id, lower))
    above = cur.fetchone()[0]
    if above is None:
        return lower + common.RANK_STEP
    if float(above) - lower < 1e-6:
        _renumber(cur, project_id, status_id, task_id)
        return _midpoint_rank(cur, project_id, status_id, task_id, None, after_key)
    return (lower + float(above)) / 2


def _renumber(cur, project_id: int, status_id: int, except_task_id: int) -> None:
    cur.execute("SELECT task_id FROM orion_ods.task WHERE project_id = %s AND status_id = %s AND task_id <> %s AND NOT is_deleted ORDER BY rank, task_id", (project_id, status_id, except_task_id))
    for position, (tid,) in enumerate(cur.fetchall(), start=1):
        cur.execute("UPDATE orion_ods.task SET rank = %s WHERE task_id = %s", (position * common.RANK_STEP, tid))


def transition(
    user: dict[str, Any], key: str, status_id: int, *, note: Any = None, resolution: str | None = None, reviewer_id: Any = None,
    before_key: str | None = None, after_key: str | None = None,
) -> dict[str, Any]:
    """Move a task to another status (and, with before_key / after_key, to a place in its column). The rules for review and for done are applied here."""
    why = common.clean_text(note, 1000, "The note", multiline=True)
    with db_cursor(commit=True) as cur:
        task, project, role = common.load_task(cur, key, user, level="edit", lock=True)
        target = _status_of(cur, project["project_id"], int(status_id))
        current = _status_of(cur, project["project_id"], task["status_id"])
        reorder_only = target["status_id"] == current["status_id"]
        who = _name(cur, user["id"])
        resolved_value, resolved_at = task["resolution"], task["resolved_timestamp"]
        reviewer = task["reviewer_id"]
        pending = _pending_review(cur, task["task_id"], lock=True)
        if not reorder_only:
            if target["wip_limit"] and role != "Manager":
                cur.execute("SELECT COUNT(*) FROM orion_ods.task WHERE status_id = %s AND NOT is_deleted", (target["status_id"],))
                if cur.fetchone()[0] >= target["wip_limit"]:
                    raise common.TaskError(f"{target['name']} is full: it can hold {target['wip_limit']} tasks. Finish one first, or ask a manager.")
            if target["category"] == "review":
                new_reviewer = _check_person(cur, project, reviewer_id, "The reviewer", works=False) if reviewer_id not in (None, "") else reviewer
                if new_reviewer is None:
                    raise common.TaskError("Choose who should review this task.")
                if new_reviewer == task["assignee_id"]:
                    raise common.TaskError("The reviewer must be someone other than the person doing the work.")
                reviewer = new_reviewer
                if pending is not None:
                    cur.execute("UPDATE orion_ods.task_review SET status = 'Withdrawn', decided_timestamp = CURRENT_TIMESTAMP, decision_note = 'Sent for review again' WHERE review_id = %s", (pending["review_id"],))
                cur.execute("INSERT INTO orion_ods.task_review (task_id, requested_by, reviewer_id, request_note) VALUES (%s, %s, %s, %s)", (task["task_id"], user["id"], reviewer, why))
                items.auto_watch(cur, task["task_id"], reviewer)
            elif pending is not None and current["category"] == "review":
                # moved out of review by someone else than a decision: the request is withdrawn
                cur.execute("UPDATE orion_ods.task_review SET status = 'Withdrawn', decided_timestamp = CURRENT_TIMESTAMP, decision_note = %s WHERE review_id = %s", (why or "Moved out of review", pending["review_id"]))
                common.log(cur, project["project_id"], task["task_id"], user["id"], "review_withdrawn")
            if target["category"] == "done":
                is_reviewer = pending is not None and pending["reviewer_id"] == user["id"]
                if project["require_review"] and not is_reviewer and role != "Manager":
                    raise common.TaskError("This project needs a review before a task is done: send it for review, and the reviewer will finish it.")
                blockers = _blockers(cur, task["task_id"])
                if blockers:
                    raise common.TaskError(f"This task is blocked by {', '.join(blockers)}. Finish those first.")
                open_subs = _open_subtasks(cur, task["task_id"])
                if open_subs:
                    raise common.TaskError(f"These sub-tasks are not done yet: {', '.join(open_subs)}.")
                resolved_value = resolution or "Done"
                if resolved_value not in common.RESOLUTIONS:
                    raise common.TaskError("Choose how it was resolved.")
                if resolved_value != "Done" and not why:
                    raise common.TaskError("Say why it is closed without being done.")
                resolved_at = datetime.now().astimezone()
                if pending is not None and is_reviewer:
                    cur.execute("UPDATE orion_ods.task_review SET status = 'Approved', decided_timestamp = CURRENT_TIMESTAMP, decision_note = %s WHERE review_id = %s", (why, pending["review_id"]))
            elif current["category"] == "done":
                resolved_value, resolved_at = None, None
        rank = _midpoint_rank(cur, project["project_id"], target["status_id"], task["task_id"], before_key, after_key)
        if reorder_only and not (before_key or after_key):
            return get_task(user, key)
        cur.execute(
            """
            UPDATE orion_ods.task SET status_id = %s, reviewer_id = %s, resolution = %s, resolved_timestamp = %s, rank = %s,
                   updated_timestamp = clock_timestamp(), updated_by = %s WHERE task_id = %s
            """,
            (target["status_id"], reviewer, resolved_value, resolved_at, rank, user["id"], task["task_id"]),
        )
        if not reorder_only:
            common.log(cur, project["project_id"], task["task_id"], user["id"], "status", **{"from": current["name"], "to": target["name"], "resolution": resolved_value if target["category"] == "done" else None, "note": why})
            if target["category"] == "review":
                common.log(cur, project["project_id"], task["task_id"], user["id"], "review_requested", reviewer=_name(cur, reviewer), note=why)
                notify.notify(cur, project, task, "review_requested", user["id"], [reviewer], f"{who} asked you to review {task['task_key']}: {task['title']}")
            cur.execute("SELECT * FROM orion_ods.task WHERE task_id = %s", (task["task_id"],))
            fresh = common.one(cur)
            others = [u for u in items._interested(cur, fresh) if not (target["category"] == "review" and u == reviewer)]
            notify.notify(cur, project, task, "status", user["id"], others, f"{who} moved {task['task_key']} to {target['name']}: {task['title']}")
    return get_task(user, key)


def request_review(user: dict[str, Any], key: str, reviewer_id: Any, note: Any = None) -> dict[str, Any]:
    with db_cursor() as cur:
        task, project, _role = common.load_task(cur, key, user, level="edit")
        review_status = _status_of(cur, project["project_id"], None, "review")
    return transition(user, key, review_status["status_id"], note=note, reviewer_id=reviewer_id)


def decide_review(user: dict[str, Any], key: str, decision: str, note: Any = None) -> dict[str, Any]:
    """The reviewer approves (the task is done) or asks for changes (it goes back to work, and the reason is needed). A manager may decide for the reviewer."""
    if decision not in ("approve", "changes"):
        raise common.TaskError("A review is approved, or changes are asked for.")
    why = common.clean_text(note, 1000, "The note", multiline=True)
    if decision == "changes" and not why:
        raise common.TaskError("Say what needs to change.")
    with db_cursor(commit=True) as cur:
        task, project, role = common.load_task(cur, key, user, level="comment", lock=True)
        pending = _pending_review(cur, task["task_id"], lock=True)
        if pending is None:
            raise common.TaskError("Nobody has asked for a review of this task, or it was already decided.")
        if pending["reviewer_id"] != user["id"] and role != "Manager":
            raise common.Forbidden("Only the reviewer, or a manager, can decide this review.")
        blockers = _blockers(cur, task["task_id"]) if decision == "approve" else []
        if blockers:
            raise common.TaskError(f"This task is blocked by {', '.join(blockers)}. Finish those first.")
        if decision == "approve":
            open_subs = _open_subtasks(cur, task["task_id"])
            if open_subs:
                raise common.TaskError(f"These sub-tasks are not done yet: {', '.join(open_subs)}.")
            target = _status_of(cur, project["project_id"], None, "done")
            cur.execute("UPDATE orion_ods.task_review SET status = 'Approved', decided_timestamp = CURRENT_TIMESTAMP, decision_note = %s WHERE review_id = %s", (why, pending["review_id"]))
            cur.execute(
                "UPDATE orion_ods.task SET status_id = %s, resolution = 'Done', resolved_timestamp = CURRENT_TIMESTAMP, rank = %s, updated_timestamp = clock_timestamp(), updated_by = %s WHERE task_id = %s",
                (target["status_id"], _bottom_rank(cur, project["project_id"], target["status_id"]), user["id"], task["task_id"]),
            )
            common.log(cur, project["project_id"], task["task_id"], user["id"], "review_approved", note=why)
            common.log(cur, project["project_id"], task["task_id"], user["id"], "status", **{"from": task["status_name"], "to": target["name"], "resolution": "Done", "note": None})
            kind, text = "review_approved", f"{_name(cur, user['id'])} approved {task['task_key']}: {task['title']}"
        else:
            target = _status_of(cur, project["project_id"], None, "doing") if any(s["category"] == "doing" for s in _statuses(cur, project["project_id"])) else _status_of(cur, project["project_id"], None, "todo")
            cur.execute("UPDATE orion_ods.task_review SET status = 'Changes requested', decided_timestamp = CURRENT_TIMESTAMP, decision_note = %s WHERE review_id = %s", (why, pending["review_id"]))
            cur.execute(
                "UPDATE orion_ods.task SET status_id = %s, rank = %s, updated_timestamp = clock_timestamp(), updated_by = %s WHERE task_id = %s",
                (target["status_id"], _bottom_rank(cur, project["project_id"], target["status_id"]), user["id"], task["task_id"]),
            )
            common.log(cur, project["project_id"], task["task_id"], user["id"], "review_changes", note=why)
            common.log(cur, project["project_id"], task["task_id"], user["id"], "status", **{"from": task["status_name"], "to": target["name"], "resolution": None, "note": why})
            kind, text = "review_changes", f"{_name(cur, user['id'])} asked for changes on {task['task_key']}: {why}"
        cur.execute("SELECT * FROM orion_ods.task WHERE task_id = %s", (task["task_id"],))
        fresh = common.one(cur)
        notify.notify(cur, project, task, kind, user["id"], [fresh["assignee_id"], fresh["reporter_id"], pending["requested_by"], *items._interested(cur, fresh)], text)
    return get_task(user, key)


def withdraw_review(user: dict[str, Any], key: str) -> dict[str, Any]:
    with db_cursor(commit=True) as cur:
        task, project, _role = common.load_task(cur, key, user, level="edit", lock=True)
        pending = _pending_review(cur, task["task_id"], lock=True)
        if pending is None:
            raise common.TaskError("There is no review waiting.")
        back = _status_of(cur, project["project_id"], None, "doing") if any(s["category"] == "doing" for s in _statuses(cur, project["project_id"])) else _status_of(cur, project["project_id"], None, "todo")
        cur.execute("UPDATE orion_ods.task_review SET status = 'Withdrawn', decided_timestamp = CURRENT_TIMESTAMP, decision_note = 'Withdrawn' WHERE review_id = %s", (pending["review_id"],))
        cur.execute("UPDATE orion_ods.task SET status_id = %s, updated_timestamp = clock_timestamp(), updated_by = %s WHERE task_id = %s AND status_id = %s", (back["status_id"], user["id"], task["task_id"], task["status_id"]))
        common.log(cur, project["project_id"], task["task_id"], user["id"], "review_withdrawn")
        notify.notify(cur, project, task, "review_withdrawn", user["id"], [pending["reviewer_id"]], f"{_name(cur, user['id'])} withdrew the review request for {task['task_key']}")
    return get_task(user, key)


# ---------------------------------------------------------------------------------------------------------------------- deleting and bulk


def delete_task(user: dict[str, Any], key: str) -> dict[str, Any]:
    """Hide a task (and its sub-tasks). Its manager or the person who raised it can; nothing is erased, and it can be restored."""
    with db_cursor(commit=True) as cur:
        task, project, role = common.load_task(cur, key, user, level="edit", lock=True)
        if role != "Manager" and task["reporter_id"] != user["id"]:
            raise common.Forbidden("Only a manager, or the person who raised the task, can delete it.")
        cur.execute("UPDATE orion_ods.task SET is_deleted = TRUE, deleted_by = %s, deleted_timestamp = CURRENT_TIMESTAMP WHERE (task_id = %s OR parent_id = %s) AND NOT is_deleted", (user["id"], task["task_id"], task["task_id"]))
        common.log(cur, project["project_id"], task["task_id"], user["id"], "deleted")
    return {"ok": True}


def restore_task(user: dict[str, Any], key: str) -> dict[str, Any]:
    with db_cursor(commit=True) as cur:
        cur.execute("SELECT t.*, s.category AS status_category, s.name AS status_name FROM orion_ods.task t JOIN orion_ods.task_status s ON s.status_id = t.status_id WHERE t.task_key = %s AND t.is_deleted FOR UPDATE OF t", (str(key).upper(),))
        task = common.one(cur)
        if not task:
            raise common.NotFound("That task is not among the deleted ones.")
        project = common.project_row(cur, key.split("-")[0], lock=True)
        common.need_manage(cur, project, user)
        cur.execute("UPDATE orion_ods.task SET is_deleted = FALSE, deleted_by = NULL, deleted_timestamp = NULL, updated_timestamp = clock_timestamp() WHERE task_id = %s OR (parent_id = %s AND deleted_by = %s)", (task["task_id"], task["task_id"], task["deleted_by"]))
        common.log(cur, project["project_id"], task["task_id"], user["id"], "restored")
    return get_task(user, key)


def bulk_update(user: dict[str, Any], keys: list[str], changes: dict[str, Any]) -> dict[str, Any]:
    """Apply the same change to several tasks (at most 200), each as if it were done by hand: the ones that cannot be changed are listed with the reason."""
    if not keys:
        raise common.TaskError("Choose the tasks to change.")
    if len(keys) > common.MAX_BULK:
        raise common.TaskError(f"Change at most {common.MAX_BULK} tasks at a time.")
    if not changes:
        raise common.TaskError("Say what to change.")
    done, failed = [], []
    for key in dict.fromkeys(str(k).upper() for k in keys):
        try:
            step = {k: v for k, v in changes.items() if k in ("priority", "assignee_id", "sprint_id", "due_date", "reviewer_id")}
            if step:
                update_task(user, key, step)
            if "labels_add" in changes or "labels_remove" in changes:
                current = get_task(user, key)["labels"]
                add = common.clean_labels(changes.get("labels_add"))
                remove = set(common.clean_labels(changes.get("labels_remove")))
                update_task(user, key, {"labels": [lab for lab in current if lab not in remove] + [lab for lab in add if lab not in current]})
            if changes.get("status_id"):
                transition(user, key, int(changes["status_id"]), note=changes.get("note"), resolution=changes.get("resolution"), reviewer_id=changes.get("reviewer_id"))
            done.append(key)
        except common.TaskError as exc:
            failed.append({"key": key, "reason": str(exc)})
    return {"changed": done, "failed": failed}
