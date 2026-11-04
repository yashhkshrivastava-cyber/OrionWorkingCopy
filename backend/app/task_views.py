"""The ways of looking at tasks: a person's own work, a project's board, the calendar, the reports and saved filters.

Everything here reads, within what the person may see, except the saved filters, which this module writes (``task_saved_filter``).
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any

from app import task_common as common
from app import task_notify as notify
from app import tasks
from app.database import db_cursor

DONE_COLUMN_DAYS = 30
BOARD_LIMIT = 500


def mine(user: dict[str, Any]) -> dict[str, Any]:
    """The page a person starts the day on: what is late or due, what waits for their review, what is theirs, what they raised and what they follow."""
    today = date.today()
    base = {"sort": "due", "limit": 100}
    assigned = tasks.list_tasks(user, {**base, "assignee": "me", "open": True})
    review = tasks.list_tasks(user, {"reviewer": "me", "category": "review", "limit": 50})
    raised = tasks.list_tasks(user, {"reporter": "me", "open": True, "sort": "updated", "dir": "desc", "limit": 50})
    watching = tasks.list_tasks(user, {"watching": True, "open": True, "sort": "updated", "dir": "desc", "limit": 50})
    recent = tasks.list_tasks(user, {"assignee": "me", "done": True, "sort": "updated", "dir": "desc", "limit": 15})
    mine_keys = {t["key"] for t in assigned["tasks"]}
    raised_by_me = [t for t in raised["tasks"] if t["key"] not in mine_keys]
    following = [t for t in watching["tasks"] if t["key"] not in mine_keys and (t["reporter"] or {}).get("id") != user["id"]]
    buckets = {"overdue": [], "today": [], "week": [], "later": [], "no_date": []}
    for t in assigned["tasks"]:
        due = date.fromisoformat(t["due_date"]) if t["due_date"] else None
        if due is None:
            buckets["no_date"].append(t)
        elif due < today:
            buckets["overdue"].append(t)
        elif due == today:
            buckets["today"].append(t)
        elif due <= today + timedelta(days=7):
            buckets["week"].append(t)
        else:
            buckets["later"].append(t)
    return {
        "buckets": buckets, "to_review": review["tasks"], "raised": raised_by_me, "watching": following, "recently_done": recent["tasks"],
        "counts": {"assigned": assigned["total"], "overdue": len(buckets["overdue"]), "today": len(buckets["today"]), "to_review": len(review["tasks"]), "unread": notify.unread_count(user["id"])},
        "today": today.isoformat(),
    }


def board(user: dict[str, Any], key: str, filters: dict[str, Any] | None = None) -> dict[str, Any]:
    """A project's columns, each with its tasks in rank order. Done tasks older than a month are left to the list view (and counted)."""
    f = {**(filters or {}), "project": key, "limit": BOARD_LIMIT, "sort": "rank", "include_archived": True}
    f.pop("open", None)
    f.pop("done", None)
    f.pop("category", None)
    project = tasks.get_project(user, key)
    found = tasks.list_tasks(user, f)
    cutoff = date.today() - timedelta(days=DONE_COLUMN_DAYS)
    columns = []
    hidden = 0
    for status in project["statuses"]:
        cards = [t for t in found["tasks"] if t["status"]["id"] == status["id"]]
        if status["category"] == "done":
            fresh = [t for t in cards if not t["resolved"] or date.fromisoformat(t["resolved"][:10]) >= cutoff]
            hidden += len(cards) - len(fresh)
            cards = fresh
        columns.append({**status, "tasks": cards, "count": len(cards)})
    return {"project": {k: project[k] for k in ("key", "name", "state", "require_review", "visibility", "role", "lead")}, "columns": columns, "hidden_done": hidden, "total": found["total"]}


def calendar(user: dict[str, Any], start: Any, end: Any, filters: dict[str, Any] | None = None) -> dict[str, Any]:
    first, last = common.clean_date(start, "The start"), common.clean_date(end, "The end")
    if not first or not last or last < first:
        raise common.TaskError("Give the first and last day to show.")
    if (last - first).days > 62:
        raise common.TaskError("Show at most two months at a time.")
    found = tasks.list_tasks(user, {**(filters or {}), "due_from": first, "due_to": last, "limit": common.MAX_PAGE, "sort": "due", "include_archived": False})
    days: dict[str, list[dict[str, Any]]] = {}
    for t in found["tasks"]:
        days.setdefault(t["due_date"], []).append(t)
    return {"start": first.isoformat(), "end": last.isoformat(), "days": days, "total": found["total"]}


def reports(user: dict[str, Any], project_key: str | None = None, days: int = 30) -> dict[str, Any]:
    """Counts for a project, or for every project the person can see: what is open and where, who has how much, what is late, what is being created and finished, and
    time logged. Cycle time is from the day a task was raised to the day it was resolved, for what was finished in the last 90 days."""
    days = max(7, min(int(days or 30), 180))
    condition, params = common.visible_sql(user)
    where = f"NOT t.is_deleted AND {condition}"
    args: list[Any] = list(params)
    if project_key:
        where += " AND p.project_key = %s"
        args.append(project_key.upper())
    base = "FROM orion_ods.task t JOIN orion_ods.task_project p ON p.project_id = t.project_id JOIN orion_ods.task_status s ON s.status_id = t.status_id"
    with db_cursor() as cur:
        if project_key:
            common.need_view(cur, common.project_row(cur, project_key), user)
        cur.execute(f"SELECT s.name, s.category, COUNT(*) {base} WHERE {where} AND p.state = 'Active' GROUP BY s.name, s.category, s.position ORDER BY MIN(s.position)", args)
        status = [{"name": r[0], "category": r[1], "count": r[2]} for r in cur.fetchall()]
        cur.execute(f"SELECT t.priority, COUNT(*) {base} WHERE {where} AND s.category <> 'done' GROUP BY t.priority", args)
        order = {p: i for i, p in enumerate(common.PRIORITIES)}
        priority = sorted(({"priority": r[0], "count": r[1]} for r in cur.fetchall()), key=lambda r: order[r["priority"]])
        cur.execute(f"SELECT t.task_type, COUNT(*) {base} WHERE {where} AND s.category <> 'done' GROUP BY t.task_type ORDER BY COUNT(*) DESC", args)
        types = [{"type": r[0], "count": r[1]} for r in cur.fetchall()]
        cur.execute(
            f"""
            SELECT au.id, au.display_name, COUNT(*) FILTER (WHERE s.category <> 'done') AS open_tasks,
                   COUNT(*) FILTER (WHERE s.category <> 'done' AND t.due_date < CURRENT_DATE) AS overdue,
                   COUNT(*) FILTER (WHERE s.category = 'done' AND t.resolved_timestamp >= CURRENT_TIMESTAMP - make_interval(days => %s)) AS finished,
                   COALESCE(SUM(t.estimate_minutes) FILTER (WHERE s.category <> 'done'), 0) AS estimate_minutes
              {base} LEFT JOIN orion_ods.app_user au ON au.id = t.assignee_id
             WHERE {where} AND p.state = 'Active' GROUP BY au.id, au.display_name ORDER BY open_tasks DESC, au.display_name LIMIT 60
            """,
            (days, *args),
        )
        people = [{"id": r[0], "name": r[1] or "Nobody", "open": r[2], "overdue": r[3], "finished": r[4], "estimate_minutes": r[5]} for r in cur.fetchall()]
        cur.execute(
            f"""
            WITH weeks AS (SELECT generate_series(date_trunc('week', CURRENT_DATE) - interval '11 weeks', date_trunc('week', CURRENT_DATE), interval '1 week')::date AS week)
            SELECT w.week,
                   (SELECT COUNT(*) {base} WHERE {where} AND t.created_timestamp >= w.week AND t.created_timestamp < w.week + interval '1 week') AS created,
                   (SELECT COUNT(*) {base} WHERE {where} AND s.category = 'done' AND t.resolved_timestamp >= w.week AND t.resolved_timestamp < w.week + interval '1 week') AS resolved
              FROM weeks w ORDER BY w.week
            """,
            (*args, *args),
        )
        flow = [{"week": r[0].isoformat(), "created": r[1], "resolved": r[2]} for r in cur.fetchall()]
        cur.execute(
            f"""
            SELECT t.task_key, t.title, t.due_date, t.priority, au.display_name {base} LEFT JOIN orion_ods.app_user au ON au.id = t.assignee_id
             WHERE {where} AND p.state = 'Active' AND s.category <> 'done' AND t.due_date < CURRENT_DATE ORDER BY t.due_date, t.task_no LIMIT 25
            """,
            args,
        )
        overdue = [{"key": r[0], "title": r[1], "due_date": common.iso(r[2]), "priority": r[3], "assignee": r[4], "days_late": (date.today() - r[2]).days} for r in cur.fetchall()]
        cur.execute(
            f"""
            SELECT COUNT(*), COALESCE(AVG(EXTRACT(EPOCH FROM (t.resolved_timestamp - t.created_timestamp)) / 86400), 0)
              {base} WHERE {where} AND s.category = 'done' AND t.resolved_timestamp >= CURRENT_TIMESTAMP - interval '90 days'
            """,
            args,
        )
        finished90, cycle_days = cur.fetchone()
        cur.execute(
            f"""
            SELECT u.display_name, COALESCE(SUM(l.minutes), 0) FROM orion_ods.task_time_log l JOIN orion_ods.task t ON t.task_id = l.task_id
              JOIN orion_ods.task_project p ON p.project_id = t.project_id JOIN orion_ods.task_status s ON s.status_id = t.status_id
              JOIN orion_ods.app_user u ON u.id = l.user_id
             WHERE NOT l.is_deleted AND {where} AND l.work_date >= CURRENT_DATE - %s GROUP BY u.display_name ORDER BY SUM(l.minutes) DESC LIMIT 30
            """,
            (*args, days),
        )
        time_by_person = [{"name": r[0], "minutes": r[1]} for r in cur.fetchall()]
        cur.execute(
            f"SELECT COUNT(*) {base} WHERE {where} AND p.state = 'Active' AND s.category <> 'done'", args,
        )
        open_total = cur.fetchone()[0]
        cur.execute(f"SELECT COUNT(*) {base} WHERE {where} AND p.state = 'Active' AND s.category <> 'done' AND t.assignee_id IS NULL", args)
        unassigned = cur.fetchone()[0]
    return {
        "days": days, "open": open_total, "unassigned": unassigned, "by_status": status, "by_priority": priority, "by_type": types, "people": people, "flow": flow, "overdue": overdue,
        "finished_90": finished90, "cycle_days": round(float(cycle_days), 1), "time_by_person": time_by_person,
    }


def search(user: dict[str, Any], q: str) -> dict[str, Any]:
    """A few tasks and projects that match what was typed (for the quick finder)."""
    text = (q or "").strip()[:60]
    if not text:
        return {"tasks": [], "projects": []}
    found = tasks.list_tasks(user, {"q": text, "limit": 8, "sort": "updated", "dir": "desc", "include_archived": True})
    like = text.lower()
    projects = [p for p in tasks.list_projects(user, include_archived=True) if like in p["key"].lower() or like in p["name"].lower()][:5]
    return {"tasks": found["tasks"], "projects": projects}


# ----------------------------------------------------------------------------------------------------------------------- saved filters


def list_filters(user: dict[str, Any], project_key: str | None = None) -> list[dict[str, Any]]:
    condition, params = common.visible_sql(user)
    with db_cursor() as cur:
        cur.execute(
            f"""
            SELECT f.filter_id AS id, f.name, f.definition, f.shared, f.user_id, p.project_key
              FROM orion_ods.task_saved_filter f LEFT JOIN orion_ods.task_project p ON p.project_id = f.project_id
             WHERE (f.user_id = %s OR (f.shared AND (f.project_id IS NULL OR {condition})))
               AND (%s::text IS NULL OR p.project_key = %s OR f.project_id IS NULL)
             ORDER BY lower(f.name)
            """,
            (user["id"], *params, project_key.upper() if project_key else None, project_key.upper() if project_key else None),
        )
        return [{"id": r["id"], "name": r["name"], "definition": r["definition"], "shared": r["shared"], "mine": r["user_id"] == user["id"], "project_key": r["project_key"]} for r in common.rows(cur)]


_FILTER_KEYS = ("project", "assignee", "reporter", "reviewer", "status_id", "category", "priority", "type", "label", "q", "due", "due_from", "due_to", "sprint", "watching", "involves_me", "open", "done", "sort", "dir", "view", "group")


def save_filter(user: dict[str, Any], name: Any, definition: dict[str, Any], *, project_key: str | None = None, shared: bool = False) -> list[dict[str, Any]]:
    label = common.clean_text(name, 60, "The name", required=True)
    clean = {k: v for k, v in (definition or {}).items() if k in _FILTER_KEYS and v not in (None, "", [])}
    with db_cursor(commit=True) as cur:
        project_id = None
        if project_key:
            project = common.project_row(cur, project_key)
            common.need_view(cur, project, user)
            project_id = project["project_id"]
        cur.execute("SELECT COUNT(*) FROM orion_ods.task_saved_filter WHERE user_id = %s", (user["id"],))
        if cur.fetchone()[0] >= 100:
            raise common.TaskError("You can keep at most 100 saved filters.")
        cur.execute("INSERT INTO orion_ods.task_saved_filter (user_id, project_id, name, definition, shared) VALUES (%s, %s, %s, %s::jsonb, %s)", (user["id"], project_id, label, json.dumps(clean), bool(shared)))
    return list_filters(user, project_key)


def delete_filter(user: dict[str, Any], filter_id: int) -> list[dict[str, Any]]:
    with db_cursor(commit=True) as cur:
        cur.execute("DELETE FROM orion_ods.task_saved_filter WHERE filter_id = %s AND user_id = %s", (filter_id, user["id"]))
        if not cur.rowcount:
            raise common.NotFound("That filter does not exist, or it is not yours.")
    return list_filters(user)
