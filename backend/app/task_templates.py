"""Templates for tasks, and tasks that come back by themselves (the monthly PF and ESI payment, the GST return, a licence renewal).

A template holds what a new task starts with: title, description, type, priority, who does it and who reviews it, labels, a checklist and how many days after it is made
it is due. With a schedule (daily, weekly, monthly or yearly) it makes the task itself, once for each period, even if the server was off for some of them (the latest one
is made, not a pile of missed ones). This is the only writer of ``task_template``.
"""

from __future__ import annotations

import calendar
import json
import logging
import threading
from datetime import date, timedelta
from typing import Any

from app import task_common as common
from app import tasks
from app.database import db_cursor

log = logging.getLogger(__name__)

FREQUENCIES = ("daily", "weekly", "monthly", "yearly")
MAX_TEMPLATES = 100
TICK_SECONDS = 3600


# ---------------------------------------------------------------------------------------------------------------------------- the schedule


def _clamp(year: int, month: int, day: int) -> date:
    """The day in that month, or the last day of a month that is too short (the 31st in April is the 30th)."""
    return date(year, month, min(day, calendar.monthrange(year, month)[1]))


def _add_months(year: int, month: int, months: int) -> tuple[int, int]:
    index = year * 12 + (month - 1) + months
    return index // 12, index % 12 + 1


def first_run(spec: dict[str, Any], today: date) -> date:
    """The first day on or after ``today`` that fits the schedule."""
    frequency = spec["frequency"]
    if frequency == "daily":
        return today
    if frequency == "weekly":
        weekday = spec["weekday"] if spec.get("weekday") is not None else today.weekday()
        return today + timedelta(days=(weekday - today.weekday()) % 7)
    day = spec.get("day_of_month") or today.day
    if frequency == "monthly":
        here = _clamp(today.year, today.month, day)
        if here >= today:
            return here
        year, month = _add_months(today.year, today.month, 1)
        return _clamp(year, month, day)
    month = spec.get("month_of_year") or today.month
    here = _clamp(today.year, month, day)
    return here if here >= today else _clamp(today.year + 1, month, day)


def following(spec: dict[str, Any], after: date) -> date:
    """The next day after ``after`` the schedule falls on (``after`` is itself a day it fell on)."""
    frequency, step = spec["frequency"], max(int(spec.get("interval_count") or 1), 1)
    if frequency == "daily":
        return after + timedelta(days=step)
    if frequency == "weekly":
        return after + timedelta(days=7 * step)
    if frequency == "monthly":
        year, month = _add_months(after.year, after.month, step)
        return _clamp(year, month, spec.get("day_of_month") or after.day)
    return _clamp(after.year + step, spec.get("month_of_year") or after.month, spec.get("day_of_month") or after.day)


def describe(spec: dict[str, Any]) -> str:
    """The schedule in words, for the page."""
    if not spec.get("frequency"):
        return "Not scheduled"
    step = int(spec.get("interval_count") or 1)
    unit = {"daily": "day", "weekly": "week", "monthly": "month", "yearly": "year"}[spec["frequency"]]
    every = f"Every {unit}" if step == 1 else f"Every {step} {unit}s"
    if spec["frequency"] == "weekly" and spec.get("weekday") is not None:
        every += " on " + calendar.day_name[spec["weekday"]]
    if spec["frequency"] == "monthly" and spec.get("day_of_month"):
        every += f" on day {spec['day_of_month']}"
    if spec["frequency"] == "yearly" and spec.get("month_of_year"):
        every += f" in {calendar.month_name[spec['month_of_year']]}" + (f" on day {spec['day_of_month']}" if spec.get("day_of_month") else "")
    return every


# ----------------------------------------------------------------------------------------------------------------------------- templates


def _json(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["template_id"], "name": row["name"], "title": row["title"], "description": row["description"], "type": row["task_type"], "priority": row["priority"],
        "assignee": common.person(row, "assignee"), "reviewer": common.person(row, "reviewer"), "labels": list(row["labels"] or []), "checklist": list(row["checklist"] or []),
        "due_offset_days": row["due_offset_days"], "estimate_minutes": row["estimate_minutes"], "frequency": row["frequency"], "interval_count": row["interval_count"],
        "weekday": row["weekday"], "day_of_month": row["day_of_month"], "month_of_year": row["month_of_year"], "next_run": common.iso(row["next_run"]),
        "end_date": common.iso(row["end_date"]), "last_run": common.iso(row["last_run"]), "schedule": describe(row), "active": row["active"],
    }


def list_templates(user: dict[str, Any], key: str) -> list[dict[str, Any]]:
    with db_cursor() as cur:
        project = common.project_row(cur, key)
        common.need_view(cur, project, user)
        cur.execute(
            f"""
            SELECT t.*, {common.person_columns('au', 'assignee')}, {common.person_columns('vu', 'reviewer')}
              FROM orion_ods.task_template t LEFT JOIN orion_ods.app_user au ON au.id = t.assignee_id LEFT JOIN orion_ods.app_user vu ON vu.id = t.reviewer_id
             WHERE t.project_id = %s AND t.active ORDER BY (t.frequency IS NULL), lower(t.name)
            """,
            (project["project_id"],),
        )
        return [_json(r) for r in common.rows(cur)]


def _clean(cur, project: dict[str, Any], data: dict[str, Any], today: date) -> dict[str, Any]:
    name = common.clean_text(data.get("name"), 80, "The name of the template", required=True)
    title = common.clean_text(data.get("title"), common.MAX_TITLE, "The title", required=True)
    task_type = data.get("type") or data.get("task_type") or "Task"
    priority = data.get("priority") or "Medium"
    if task_type not in common.TYPES or task_type == "Sub-task":
        raise common.TaskError("Choose the type of task from the list.")
    if priority not in common.PRIORITIES:
        raise common.TaskError("Choose the priority from the list.")
    frequency = data.get("frequency") or None
    if frequency is not None and frequency not in FREQUENCIES:
        raise common.TaskError("Choose how often it comes back: daily, weekly, monthly or yearly.")
    assignee = tasks._check_person(cur, project, data.get("assignee_id"), "The assignee", works=True)
    reviewer = tasks._check_person(cur, project, data.get("reviewer_id"), "The reviewer", works=False)
    if reviewer is not None and reviewer == assignee:
        raise common.TaskError("The reviewer must be someone other than the person doing the work.")
    checklist = [common.clean_text(t, 300, "A checklist item", required=True) for t in (data.get("checklist") or []) if str(t).strip()][: common.MAX_CHECKLIST]
    spec = {
        "frequency": frequency, "interval_count": int(data.get("interval_count") or 1), "weekday": data.get("weekday"), "day_of_month": data.get("day_of_month"),
        "month_of_year": data.get("month_of_year"),
    }
    for field, low, high in (("interval_count", 1, 52), ("weekday", 0, 6), ("day_of_month", 1, 31), ("month_of_year", 1, 12)):
        value = spec[field]
        if value in (None, ""):
            spec[field] = None
            continue
        try:
            spec[field] = int(value)
        except (TypeError, ValueError):
            raise common.TaskError("The schedule has a number that is not valid.") from None
        if not low <= spec[field] <= high:
            raise common.TaskError(f"That part of the schedule must be between {low} and {high}.")
    end = common.clean_date(data.get("end_date"), "The end date")
    next_run = common.clean_date(data.get("next_run"), "The first day") if frequency else None
    if frequency and next_run is None:
        next_run = first_run(spec, today)
    if frequency and assignee is None:
        raise common.TaskError("A task that comes back by itself needs someone to give it to.")
    if end and next_run and end < next_run:
        raise common.TaskError("The schedule ends before it starts.")
    return {
        "name": name, "title": title, "description": common.clean_text(data.get("description"), common.MAX_TEXT, "The description", multiline=True), "task_type": task_type,
        "priority": priority, "assignee_id": assignee, "reviewer_id": reviewer, "labels": common.clean_labels(data.get("labels")), "checklist": checklist,
        "due_offset_days": int(data.get("due_offset_days") or 0), "estimate_minutes": common.clean_minutes(data.get("estimate_minutes"), "The estimate"),
        "end_date": end, "next_run": next_run, "active": data.get("active", True) is not False, **spec,
    }


def save_template(user: dict[str, Any], key: str, data: dict[str, Any], template_id: int | None = None) -> list[dict[str, Any]]:
    with db_cursor(commit=True) as cur:
        project = common.project_row(cur, key, lock=True)
        common.need_edit(cur, project, user)
        values = _clean(cur, project, data, date.today())
        if not 0 <= values["due_offset_days"] <= 366:
            raise common.TaskError("The due date can be 0 to 366 days after the task is made.")
        columns = ["name", "title", "description", "task_type", "priority", "assignee_id", "reviewer_id", "labels", "due_offset_days", "estimate_minutes", "frequency",
                   "interval_count", "weekday", "day_of_month", "month_of_year", "next_run", "end_date", "active"]
        args = [values[c] for c in columns]
        if template_id is None:
            cur.execute("SELECT COUNT(*) FROM orion_ods.task_template WHERE project_id = %s AND active", (project["project_id"],))
            if cur.fetchone()[0] >= MAX_TEMPLATES:
                raise common.TaskError(f"A project can have at most {MAX_TEMPLATES} templates.")
            cur.execute(
                f"INSERT INTO orion_ods.task_template (project_id, checklist, created_by, {', '.join(columns)}) VALUES (%s, %s::jsonb, %s, {', '.join(['%s'] * len(columns))}) RETURNING template_id",
                (project["project_id"], json.dumps(values["checklist"]), user["id"], *args),
            )
            template_id = cur.fetchone()[0]
            common.log(cur, project["project_id"], None, user["id"], "template_created", name=values["name"])
        else:
            cur.execute("SELECT 1 FROM orion_ods.task_template WHERE template_id = %s AND project_id = %s", (template_id, project["project_id"]))
            if not cur.fetchone():
                raise common.NotFound("That template does not exist.")
            cur.execute(
                f"UPDATE orion_ods.task_template SET checklist = %s::jsonb, {', '.join(f'{c} = %s' for c in columns)} WHERE template_id = %s",
                (json.dumps(values["checklist"]), *args, template_id),
            )
            common.log(cur, project["project_id"], None, user["id"], "template_changed", name=values["name"])
    return list_templates(user, key)


def delete_template(user: dict[str, Any], key: str, template_id: int) -> list[dict[str, Any]]:
    """A template stops being offered and stops making tasks. The tasks it made stay, and still say where they came from."""
    with db_cursor(commit=True) as cur:
        project = common.project_row(cur, key, lock=True)
        common.need_edit(cur, project, user)
        cur.execute("UPDATE orion_ods.task_template SET active = FALSE, next_run = NULL WHERE template_id = %s AND project_id = %s AND active RETURNING name", (template_id, project["project_id"]))
        found = cur.fetchone()
        if not found:
            raise common.NotFound("That template does not exist.")
        common.log(cur, project["project_id"], None, user["id"], "template_deleted", name=found[0])
    return list_templates(user, key)


def _task_data(template: dict[str, Any], run: date) -> dict[str, Any]:
    return {
        "title": template["title"], "description": template["description"], "type": template["task_type"], "priority": template["priority"], "assignee_id": template["assignee_id"],
        "reviewer_id": template["reviewer_id"], "labels": list(template["labels"] or []), "checklist": list(template["checklist"] or []), "estimate_minutes": template["estimate_minutes"],
        "due_date": run + timedelta(days=template["due_offset_days"]),
    }


def make_task(user: dict[str, Any], key: str, template_id: int, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    """Make a task from a template now, by hand. What is sent in ``overrides`` (a title, a due date) replaces what the template has."""
    with db_cursor(commit=True) as cur:
        project = common.project_row(cur, key, lock=True)
        common.need_edit(cur, project, user)
        cur.execute("SELECT * FROM orion_ods.task_template WHERE template_id = %s AND project_id = %s AND active", (template_id, project["project_id"]))
        template = common.one(cur)
        if not template:
            raise common.NotFound("That template does not exist.")
        data = {**_task_data(template, date.today()), **{k: v for k, v in (overrides or {}).items() if v not in (None, "")}}
        row = tasks.insert_task(cur, project, user["id"], data, template_id=template_id)
        made = row["task_key"]
    return tasks.get_task(user, made)


# ------------------------------------------------------------------------------------------------------------------ the tasks that come back


def run_due(today: date | None = None) -> int:
    """Make the tasks that are due today or before. A schedule that has fallen behind makes the latest one, not all of them. Returns how many were made."""
    today = today or date.today()
    made = 0
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT t.template_id FROM orion_ods.task_template t JOIN orion_ods.task_project p ON p.project_id = t.project_id
             WHERE t.frequency IS NOT NULL AND t.active AND t.next_run IS NOT NULL AND t.next_run <= %s AND p.state = 'Active' ORDER BY t.template_id
            """,
            (today,),
        )
        due = [r[0] for r in cur.fetchall()]
    for template_id in due:
        try:
            with db_cursor(commit=True) as cur:
                cur.execute("SELECT * FROM orion_ods.task_template WHERE template_id = %s AND active AND next_run <= %s FOR UPDATE SKIP LOCKED", (template_id, today))
                template = common.one(cur)
                if not template:
                    continue
                run = template["next_run"]
                while following(template, run) <= today:
                    run = following(template, run)
                after = following(template, run)
                ended = template["end_date"] is not None and after > template["end_date"]
                cur.execute("SELECT * FROM orion_ods.task_project WHERE project_id = %s", (template["project_id"],))
                project = common.one(cur)
                if template["end_date"] is None or run <= template["end_date"]:
                    tasks.insert_task(cur, project, template["created_by"], _task_data(template, run), template_id=template_id)
                    made += 1
                cur.execute(
                    "UPDATE orion_ods.task_template SET last_run = %s, next_run = %s, active = %s WHERE template_id = %s",
                    (run, None if ended else after, not ended, template_id),
                )
        except Exception:  # noqa: BLE001 - one template that cannot be made (its assignee left) must not stop the others; it is logged and tried next time
            log.exception("Could not make the task for template %s", template_id)
    return made


def start(stop: threading.Event) -> None:
    """Look for tasks to make once an hour for as long as the server runs."""

    def loop() -> None:
        wait = 60.0  # the first look is a minute after the server starts, so a schedule that came due while it was off is not left until the next hour
        while not stop.wait(wait):
            wait = float(TICK_SECONDS)
            try:
                run_due()
            except Exception:  # noqa: BLE001 - the job must outlive any single failure; the reason is logged
                log.exception("The recurring tasks job failed")

    threading.Thread(target=loop, name="task-templates", daemon=True).start()
