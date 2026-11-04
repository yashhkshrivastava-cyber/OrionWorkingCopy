"""Sprints: a short stretch of work with a goal. Plan tasks into it from the backlog, start it, and complete it (what was not finished goes back to the backlog or on to
the next sprint). A project has one active sprint at a time. This is the only writer of ``task_sprint``, and of ``task.sprint_id`` when a sprint is completed.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from app import task_common as common
from app.database import db_cursor

DEFAULT_LENGTH_DAYS = 14


def _json(row: dict[str, Any]) -> dict[str, Any]:
    total = int(row.get("tasks") or 0)
    done = int(row.get("done") or 0)
    return {
        "id": row["sprint_id"], "name": row["name"], "goal": row["goal"], "state": row["state"], "start_date": common.iso(row["start_date"]), "end_date": common.iso(row["end_date"]),
        "started": common.iso(row["started_timestamp"]), "completed": common.iso(row["completed_timestamp"]), "tasks": total, "done": done,
        "points": float(row.get("points") or 0), "points_done": float(row.get("points_done") or 0),
        "days_left": (row["end_date"] - date.today()).days if row["state"] == "Active" and row["end_date"] else None,
    }


def list_sprints(user: dict[str, Any], key: str) -> list[dict[str, Any]]:
    with db_cursor() as cur:
        project = common.project_row(cur, key)
        common.need_view(cur, project, user)
        cur.execute(
            """
            SELECT sp.*, COUNT(t.task_id) AS tasks, COUNT(t.task_id) FILTER (WHERE s.category = 'done') AS done,
                   COALESCE(SUM(t.story_points), 0) AS points, COALESCE(SUM(t.story_points) FILTER (WHERE s.category = 'done'), 0) AS points_done
              FROM orion_ods.task_sprint sp
              LEFT JOIN orion_ods.task t ON t.sprint_id = sp.sprint_id AND NOT t.is_deleted
              LEFT JOIN orion_ods.task_status s ON s.status_id = t.status_id
             WHERE sp.project_id = %s GROUP BY sp.sprint_id
             ORDER BY CASE sp.state WHEN 'Active' THEN 1 WHEN 'Planned' THEN 2 ELSE 3 END, sp.start_date NULLS LAST, sp.sprint_id DESC
            """,
            (project["project_id"],),
        )
        return [_json(r) for r in common.rows(cur)]


def _sprint(cur, project: dict[str, Any], sprint_id: int, *, lock: bool = False) -> dict[str, Any]:
    cur.execute(f"SELECT * FROM orion_ods.task_sprint WHERE sprint_id = %s AND project_id = %s{' FOR UPDATE' if lock else ''}", (sprint_id, project["project_id"]))
    found = common.one(cur)
    if not found:
        raise common.NotFound("That sprint does not exist.")
    return found


def create_sprint(user: dict[str, Any], key: str, data: dict[str, Any]) -> list[dict[str, Any]]:
    name = common.clean_text(data.get("name"), 80, "The name of the sprint", required=True)
    start, end = common.clean_date(data.get("start_date"), "The start date"), common.clean_date(data.get("end_date"), "The end date")
    if start and end and end < start:
        raise common.TaskError("The end date cannot be before the start date.")
    with db_cursor(commit=True) as cur:
        project = common.project_row(cur, key, lock=True)
        common.need_manage(cur, project, user)
        cur.execute(
            "INSERT INTO orion_ods.task_sprint (project_id, name, goal, start_date, end_date, created_by) VALUES (%s, %s, %s, %s, %s, %s) RETURNING sprint_id",
            (project["project_id"], name, common.clean_text(data.get("goal"), 500, "The goal", multiline=True), start, end, user["id"]),
        )
        common.log(cur, project["project_id"], None, user["id"], "sprint_created", name=name)
    return list_sprints(user, key)


def update_sprint(user: dict[str, Any], key: str, sprint_id: int, data: dict[str, Any]) -> list[dict[str, Any]]:
    with db_cursor(commit=True) as cur:
        project = common.project_row(cur, key, lock=True)
        common.need_manage(cur, project, user)
        sprint = _sprint(cur, project, sprint_id, lock=True)
        if sprint["state"] == "Completed":
            raise common.TaskError("A finished sprint cannot be changed.")
        name = common.clean_text(data["name"], 80, "The name of the sprint", required=True) if "name" in data else sprint["name"]
        goal = common.clean_text(data["goal"], 500, "The goal", multiline=True) if "goal" in data else sprint["goal"]
        start = common.clean_date(data["start_date"], "The start date") if "start_date" in data else sprint["start_date"]
        end = common.clean_date(data["end_date"], "The end date") if "end_date" in data else sprint["end_date"]
        if start and end and end < start:
            raise common.TaskError("The end date cannot be before the start date.")
        cur.execute("UPDATE orion_ods.task_sprint SET name = %s, goal = %s, start_date = %s, end_date = %s WHERE sprint_id = %s", (name, goal, start, end, sprint_id))
        common.log(cur, project["project_id"], None, user["id"], "sprint_changed", name=name)
    return list_sprints(user, key)


def start_sprint(user: dict[str, Any], key: str, sprint_id: int) -> list[dict[str, Any]]:
    with db_cursor(commit=True) as cur:
        project = common.project_row(cur, key, lock=True)
        common.need_manage(cur, project, user)
        sprint = _sprint(cur, project, sprint_id, lock=True)
        if sprint["state"] != "Planned":
            raise common.TaskError("Only a planned sprint can be started.")
        cur.execute("SELECT name FROM orion_ods.task_sprint WHERE project_id = %s AND state = 'Active'", (project["project_id"],))
        active = cur.fetchone()
        if active:
            raise common.TaskError(f"{active[0]} is still active. Complete it before starting another sprint.")
        start = sprint["start_date"] or date.today()
        end = sprint["end_date"] or start + timedelta(days=DEFAULT_LENGTH_DAYS)
        cur.execute("UPDATE orion_ods.task_sprint SET state = 'Active', start_date = %s, end_date = %s, started_timestamp = CURRENT_TIMESTAMP WHERE sprint_id = %s", (start, end, sprint_id))
        common.log(cur, project["project_id"], None, user["id"], "sprint_started", name=sprint["name"])
    return list_sprints(user, key)


def complete_sprint(user: dict[str, Any], key: str, sprint_id: int, move_to: Any = None) -> dict[str, Any]:
    """Finish the sprint. What is not done goes to the backlog (``move_to`` empty) or to another planned sprint."""
    with db_cursor(commit=True) as cur:
        project = common.project_row(cur, key, lock=True)
        common.need_manage(cur, project, user)
        sprint = _sprint(cur, project, sprint_id, lock=True)
        if sprint["state"] != "Active":
            raise common.TaskError("Only the active sprint can be completed.")
        target = None
        if move_to not in (None, "", "backlog"):
            target = _sprint(cur, project, int(move_to), lock=True)
            if target["state"] != "Planned" or target["sprint_id"] == sprint_id:
                raise common.TaskError("Unfinished work can move to the backlog or to a planned sprint.")
        cur.execute(
            """
            SELECT COUNT(*) FILTER (WHERE s.category = 'done'), COUNT(*) FILTER (WHERE s.category <> 'done'),
                   COALESCE(SUM(t.story_points) FILTER (WHERE s.category = 'done'), 0)
              FROM orion_ods.task t JOIN orion_ods.task_status s ON s.status_id = t.status_id WHERE t.sprint_id = %s AND NOT t.is_deleted
            """,
            (sprint_id,),
        )
        done, unfinished, points = cur.fetchone()
        cur.execute(
            "UPDATE orion_ods.task t SET sprint_id = %s, updated_timestamp = clock_timestamp(), updated_by = %s FROM orion_ods.task_status s "
            "WHERE s.status_id = t.status_id AND t.sprint_id = %s AND NOT t.is_deleted AND s.category <> 'done'",
            (target["sprint_id"] if target else None, user["id"], sprint_id),
        )
        cur.execute("UPDATE orion_ods.task_sprint SET state = 'Completed', completed_timestamp = CURRENT_TIMESTAMP WHERE sprint_id = %s", (sprint_id,))
        common.log(cur, project["project_id"], None, user["id"], "sprint_completed", name=sprint["name"], done=done, unfinished=unfinished)
    return {"sprints": list_sprints(user, key), "summary": {"done": done, "unfinished": unfinished, "points_done": float(points), "moved_to": target["name"] if target else "the backlog"}}


def burndown(user: dict[str, Any], key: str, sprint_id: int) -> dict[str, Any]:
    """Work left each day of the sprint (in story points where tasks have them, else in tasks), against the straight line to nothing."""
    with db_cursor() as cur:
        project = common.project_row(cur, key)
        common.need_view(cur, project, user)
        sprint = _sprint(cur, project, sprint_id)
        cur.execute(
            """
            SELECT COALESCE(t.story_points, 1) AS weight, (t.resolved_timestamp AT TIME ZONE 'UTC')::date AS resolved, s.category
              FROM orion_ods.task t JOIN orion_ods.task_status s ON s.status_id = t.status_id WHERE t.sprint_id = %s AND NOT t.is_deleted
            """,
            (sprint_id,),
        )
        found = cur.fetchall()
    start = sprint["start_date"] or (sprint["started_timestamp"].date() if sprint["started_timestamp"] else date.today())
    end = sprint["end_date"] or start + timedelta(days=DEFAULT_LENGTH_DAYS)
    last = min(end, date.today()) if sprint["state"] == "Active" else (sprint["completed_timestamp"].date() if sprint["completed_timestamp"] else end)
    total = sum(float(w) for w, _r, _c in found)
    days = max((end - start).days, 1)
    out, day = [], start
    while day <= max(end, last):
        gone = sum(float(w) for w, r, c in found if c == "done" and r is not None and r <= day)
        out.append({"date": day.isoformat(), "ideal": round(max(total * (1 - (day - start).days / days), 0), 2), "left": round(total - gone, 2) if day <= last else None})
        day += timedelta(days=1)
    return {"sprint": _json({**sprint, "tasks": len(found), "done": sum(1 for _w, _r, c in found if c == "done"), "points": total, "points_done": 0}), "points": total, "days": out}
