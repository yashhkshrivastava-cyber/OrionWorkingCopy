"""The API of the task workspace. Every route needs a signed-in person; what they may do in a project is decided where the work is done (``task_common``): a
private project is not even admitted to exist to someone outside it."""

import logging
from typing import Any, Callable, Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Path, Query, Request, Response, UploadFile, status
from pydantic import BaseModel, Field

from app import documents, idempotency, task_files, task_items, task_notify, task_sprints, task_templates, task_todo, task_views, tasks
from app import task_common as common
from app.dependencies import get_current_user
from app.idempotency import Idempotency

log = logging.getLogger(__name__)

router = APIRouter(prefix="/tasks", tags=["tasks"])

KEY = Path(pattern=r"^[A-Za-z][A-Za-z0-9]{1,9}-[0-9]{1,9}$", description="A task key such as OPS-12")
PROJECT = Path(pattern=r"^[A-Za-z][A-Za-z0-9]{1,9}$", description="A project key such as OPS")

FILTER_NAMES = (
    "project", "assignee", "reporter", "reviewer", "status_id", "category", "priority", "type", "label", "q", "due", "due_from", "due_to", "sprint", "parent", "no_parent",
    "watching", "involves_me", "open", "done", "sort", "dir", "limit", "offset", "include_archived", "record_type", "record_ref",
)


def _problem(exc: Exception) -> HTTPException:
    """The status a refusal is answered with, from what kind of refusal it is."""
    if isinstance(exc, common.NotFound):
        code = status.HTTP_404_NOT_FOUND
    elif isinstance(exc, common.Forbidden):
        code = status.HTTP_403_FORBIDDEN
    elif isinstance(exc, common.Conflict):
        code = status.HTTP_409_CONFLICT
    else:
        code = status.HTTP_400_BAD_REQUEST
    return HTTPException(code, str(exc))


def _run(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    try:
        return fn(*args, **kwargs)
    except (common.TaskError, documents.DocumentCenterError) as exc:
        raise _problem(exc) from exc
    except idempotency.IdempotencyConflict as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc


def _once(request: Request, user: dict, operation: str, *parts: Any) -> Optional[Idempotency]:
    """The request's one-time key, if it sent one, so a double click or a retry does not make the task twice."""
    try:
        key = idempotency.clean_key(request.headers.get("Idempotency-Key"))
    except idempotency.IdempotencyError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    if key is None:
        return None
    return Idempotency(user["id"], key, operation, idempotency.fingerprint(operation, user["id"], *parts))


# --------------------------------------------------------------------------------------------------------------------------- bodies


class ProjectIn(BaseModel):
    key: str = Field(max_length=10)
    name: str = Field(max_length=200)
    description: Optional[str] = Field(default=None, max_length=5000)
    visibility: Optional[str] = None
    require_review: bool = False
    color: Optional[str] = Field(default=None, max_length=20)


class ProjectChanges(BaseModel):
    name: Optional[str] = Field(default=None, max_length=200)
    description: Optional[str] = Field(default=None, max_length=5000)
    visibility: Optional[str] = None
    require_review: Optional[bool] = None
    color: Optional[str] = Field(default=None, max_length=20)
    lead_id: Optional[int] = None


class Archive(BaseModel):
    archived: bool


class MemberIn(BaseModel):
    role: Optional[str] = None


class StatusIn(BaseModel):
    name: str = Field(max_length=60)
    category: str


class StatusChanges(BaseModel):
    name: Optional[str] = Field(default=None, max_length=60)
    category: Optional[str] = None
    wip_limit: Optional[int] = Field(default=None, ge=0, le=500)


class TaskIn(BaseModel):
    project: str = Field(max_length=10)
    title: str = Field(max_length=400)
    description: Optional[str] = Field(default=None, max_length=common.MAX_TEXT + 100)
    type: Optional[str] = None
    priority: Optional[str] = None
    status_id: Optional[int] = None
    assignee_id: Optional[int] = None
    reviewer_id: Optional[int] = None
    parent_key: Optional[str] = Field(default=None, max_length=20)
    sprint_id: Optional[int] = None
    start_date: Optional[str] = None
    due_date: Optional[str] = None
    estimate_minutes: Optional[int] = Field(default=None, ge=0)
    story_points: Optional[float] = Field(default=None, ge=0, le=1000)
    labels: Optional[list[str]] = Field(default=None, max_length=30)
    checklist: Optional[list[str]] = Field(default=None, max_length=common.MAX_CHECKLIST)
    records: Optional[list[dict[str, str]]] = Field(default=None, max_length=10)


class TaskChanges(BaseModel):
    """Only what is sent is changed. ``expected_updated`` is the ``updated`` of the task as the person opened it."""

    model_config = {"extra": "forbid"}
    title: Optional[str] = Field(default=None, max_length=400)
    description: Optional[str] = Field(default=None, max_length=common.MAX_TEXT + 100)
    type: Optional[str] = None
    priority: Optional[str] = None
    assignee_id: Optional[int] = None
    reviewer_id: Optional[int] = None
    parent_key: Optional[str] = Field(default=None, max_length=20)
    sprint_id: Optional[int] = None
    start_date: Optional[str] = None
    due_date: Optional[str] = None
    estimate_minutes: Optional[int] = Field(default=None, ge=0)
    story_points: Optional[float] = Field(default=None, ge=0, le=1000)
    labels: Optional[list[str]] = Field(default=None, max_length=30)
    expected_updated: Optional[str] = None


class MoveIn(BaseModel):
    status_id: int
    note: Optional[str] = Field(default=None, max_length=1500)
    resolution: Optional[str] = None
    reviewer_id: Optional[int] = None
    before_key: Optional[str] = Field(default=None, max_length=20)
    after_key: Optional[str] = Field(default=None, max_length=20)


class ReviewRequest(BaseModel):
    reviewer_id: int
    note: Optional[str] = Field(default=None, max_length=1500)


class ReviewDecision(BaseModel):
    decision: str
    note: Optional[str] = Field(default=None, max_length=1500)


class BulkIn(BaseModel):
    keys: list[str] = Field(max_length=common.MAX_BULK)
    changes: dict[str, Any]


class CommentIn(BaseModel):
    body: str = Field(max_length=task_items.MAX_COMMENT + 200)


class WatchIn(BaseModel):
    watching: bool = True
    user_id: Optional[int] = None


class ChecklistIn(BaseModel):
    text: str = Field(max_length=500)


class ChecklistChanges(BaseModel):
    text: Optional[str] = Field(default=None, max_length=500)
    done: Optional[bool] = None
    position: Optional[int] = None


class LinkIn(BaseModel):
    kind: str
    other_key: str = Field(max_length=20)


class RecordIn(BaseModel):
    type: str = Field(max_length=20)
    ref: str = Field(max_length=100)


class TimeIn(BaseModel):
    minutes: int = Field(ge=1, le=1440)
    date: Optional[str] = None
    note: Optional[str] = Field(default=None, max_length=500)


class ReadIn(BaseModel):
    ids: Optional[list[int]] = Field(default=None, max_length=500)


class TodoListIn(BaseModel):
    name: str = Field(max_length=100)


class TodoItemIn(BaseModel):
    text: str = Field(max_length=500)
    notes: Optional[str] = Field(default=None, max_length=3000)
    list_id: Optional[int] = None
    due_date: Optional[str] = None
    my_day: Optional[str] = None


class TodoItemChanges(BaseModel):
    model_config = {"extra": "forbid"}
    text: Optional[str] = Field(default=None, max_length=500)
    notes: Optional[str] = Field(default=None, max_length=3000)
    list_id: Optional[int] = None
    due_date: Optional[str] = None
    my_day: Optional[str] = None
    done: Optional[bool] = None
    position: Optional[int] = None


class TodoToTask(BaseModel):
    project: str = Field(max_length=10)
    assignee_id: Optional[int] = None
    priority: Optional[str] = None
    type: Optional[str] = None


class SprintIn(BaseModel):
    name: str = Field(max_length=120)
    goal: Optional[str] = Field(default=None, max_length=1000)
    start_date: Optional[str] = None
    end_date: Optional[str] = None


class SprintChanges(BaseModel):
    model_config = {"extra": "forbid"}
    name: Optional[str] = Field(default=None, max_length=120)
    goal: Optional[str] = Field(default=None, max_length=1000)
    start_date: Optional[str] = None
    end_date: Optional[str] = None


class SprintComplete(BaseModel):
    move_to: Optional[str] = None


class TemplateIn(BaseModel):
    model_config = {"extra": "forbid"}
    name: str = Field(max_length=160)
    title: str = Field(max_length=400)
    description: Optional[str] = Field(default=None, max_length=common.MAX_TEXT + 100)
    type: Optional[str] = None
    priority: Optional[str] = None
    assignee_id: Optional[int] = None
    reviewer_id: Optional[int] = None
    labels: Optional[list[str]] = Field(default=None, max_length=30)
    checklist: Optional[list[str]] = Field(default=None, max_length=common.MAX_CHECKLIST)
    due_offset_days: Optional[int] = Field(default=0, ge=0, le=366)
    estimate_minutes: Optional[int] = Field(default=None, ge=0)
    frequency: Optional[str] = None
    interval_count: Optional[int] = Field(default=1, ge=1, le=52)
    weekday: Optional[int] = Field(default=None, ge=0, le=6)
    day_of_month: Optional[int] = Field(default=None, ge=1, le=31)
    month_of_year: Optional[int] = Field(default=None, ge=1, le=12)
    next_run: Optional[str] = None
    end_date: Optional[str] = None
    active: bool = True


class FromTemplate(BaseModel):
    title: Optional[str] = Field(default=None, max_length=400)
    due_date: Optional[str] = None
    assignee_id: Optional[int] = None


class FilterIn(BaseModel):
    name: str = Field(max_length=100)
    definition: dict[str, Any]
    project: Optional[str] = Field(default=None, max_length=10)
    shared: bool = False


def _filters(request: Request) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name in FILTER_NAMES:
        values = request.query_params.getlist(name)
        if values:
            out[name] = ",".join(values) if name not in ("q", "parent") else values[0]
    return out


# ------------------------------------------------------------------------------------------------------------ fixed paths first


@router.get("/people")
def people(project: Optional[str] = Query(default=None, max_length=10), user=Depends(get_current_user)):
    return {"people": _run(tasks.people, user, project)}


@router.get("/me")
def me(user=Depends(get_current_user)):
    """What the bell and the navigation need: how many notifications are unread and how many tasks are late or due soon."""
    reminders = task_notify.reminders(user)
    return {"unread": task_notify.unread_count(user["id"]), "overdue": len(reminders["overdue"]), "due_today": len(reminders["today"]), "attention": len(reminders["overdue"]) + len(reminders["today"])}


@router.get("/projects")
def projects(archived: bool = False, user=Depends(get_current_user)):
    return {"projects": _run(tasks.list_projects, user, include_archived=archived)}


@router.post("/projects", status_code=status.HTTP_201_CREATED)
def create_project(body: ProjectIn, user=Depends(get_current_user)):
    return _run(tasks.create_project, user, body.model_dump())


@router.get("/projects/{key}")
def project(key: str = PROJECT, user=Depends(get_current_user)):
    return _run(tasks.get_project, user, key)


@router.put("/projects/{key}")
def update_project(body: ProjectChanges, key: str = PROJECT, user=Depends(get_current_user)):
    return _run(tasks.update_project, user, key, body.model_dump(exclude_unset=True))


@router.post("/projects/{key}/archive")
def archive_project(body: Archive, key: str = PROJECT, user=Depends(get_current_user)):
    return _run(tasks.set_archived, user, key, body.archived)


@router.put("/projects/{key}/members/{member_id}")
def set_member(member_id: int, body: MemberIn, key: str = PROJECT, user=Depends(get_current_user)):
    return {"members": _run(tasks.set_member, user, key, member_id, body.role)}


@router.delete("/projects/{key}/members/{member_id}")
def remove_member(member_id: int, key: str = PROJECT, user=Depends(get_current_user)):
    return {"members": _run(tasks.set_member, user, key, member_id, None)}


@router.post("/projects/{key}/statuses")
def add_status(body: StatusIn, key: str = PROJECT, user=Depends(get_current_user)):
    return {"statuses": _run(tasks.add_status, user, key, body.name, body.category)}


@router.put("/projects/{key}/statuses/order")
def reorder_statuses(body: dict[str, list[int]], key: str = PROJECT, user=Depends(get_current_user)):
    return {"statuses": _run(tasks.reorder_statuses, user, key, body.get("ids") or [])}


@router.put("/projects/{key}/statuses/{status_id}")
def update_status(status_id: int, body: StatusChanges, key: str = PROJECT, user=Depends(get_current_user)):
    return {"statuses": _run(tasks.update_status, user, key, status_id, body.model_dump(exclude_unset=True))}


@router.delete("/projects/{key}/statuses/{status_id}")
def delete_status(status_id: int, move_to: Optional[int] = None, key: str = PROJECT, user=Depends(get_current_user)):
    return {"statuses": _run(tasks.delete_status, user, key, status_id, move_to)}


@router.get("/projects/{key}/board")
def board(request: Request, key: str = PROJECT, user=Depends(get_current_user)):
    return _run(task_views.board, user, key, _filters(request))


@router.get("/projects/{key}/sprints")
def sprints(key: str = PROJECT, user=Depends(get_current_user)):
    return {"sprints": _run(task_sprints.list_sprints, user, key)}


@router.post("/projects/{key}/sprints")
def create_sprint(body: SprintIn, key: str = PROJECT, user=Depends(get_current_user)):
    return {"sprints": _run(task_sprints.create_sprint, user, key, body.model_dump())}


@router.put("/projects/{key}/sprints/{sprint_id}")
def update_sprint(sprint_id: int, body: SprintChanges, key: str = PROJECT, user=Depends(get_current_user)):
    return {"sprints": _run(task_sprints.update_sprint, user, key, sprint_id, body.model_dump(exclude_unset=True))}


@router.post("/projects/{key}/sprints/{sprint_id}/start")
def start_sprint(sprint_id: int, key: str = PROJECT, user=Depends(get_current_user)):
    return {"sprints": _run(task_sprints.start_sprint, user, key, sprint_id)}


@router.post("/projects/{key}/sprints/{sprint_id}/complete")
def complete_sprint(sprint_id: int, body: SprintComplete, key: str = PROJECT, user=Depends(get_current_user)):
    return _run(task_sprints.complete_sprint, user, key, sprint_id, body.move_to)


@router.get("/projects/{key}/sprints/{sprint_id}/burndown")
def burndown(sprint_id: int, key: str = PROJECT, user=Depends(get_current_user)):
    return _run(task_sprints.burndown, user, key, sprint_id)


@router.get("/projects/{key}/templates")
def templates(key: str = PROJECT, user=Depends(get_current_user)):
    return {"templates": _run(task_templates.list_templates, user, key)}


@router.post("/projects/{key}/templates")
def create_template(body: TemplateIn, key: str = PROJECT, user=Depends(get_current_user)):
    return {"templates": _run(task_templates.save_template, user, key, body.model_dump())}


@router.put("/projects/{key}/templates/{template_id}")
def update_template(template_id: int, body: TemplateIn, key: str = PROJECT, user=Depends(get_current_user)):
    return {"templates": _run(task_templates.save_template, user, key, body.model_dump(), template_id)}


@router.delete("/projects/{key}/templates/{template_id}")
def delete_template(template_id: int, key: str = PROJECT, user=Depends(get_current_user)):
    return {"templates": _run(task_templates.delete_template, user, key, template_id)}


@router.post("/projects/{key}/templates/{template_id}/make")
def make_from_template(template_id: int, body: FromTemplate, key: str = PROJECT, user=Depends(get_current_user)):
    return _run(task_templates.make_task, user, key, template_id, body.model_dump(exclude_unset=True))


@router.get("/mine")
def mine(user=Depends(get_current_user)):
    return _run(task_views.mine, user)


@router.get("/calendar")
def calendar(request: Request, start: str, end: str, user=Depends(get_current_user)):
    return _run(task_views.calendar, user, start, end, _filters(request))


@router.get("/reports")
def reports(project: Optional[str] = Query(default=None, max_length=10), days: int = Query(default=30, ge=7, le=180), user=Depends(get_current_user)):
    return _run(task_views.reports, user, project, days)


@router.get("/search")
def search(q: str = Query(default="", max_length=60), user=Depends(get_current_user)):
    return _run(task_views.search, user, q)


@router.get("/filters")
def filters(project: Optional[str] = Query(default=None, max_length=10), user=Depends(get_current_user)):
    return {"filters": _run(task_views.list_filters, user, project)}


@router.post("/filters")
def save_filter(body: FilterIn, user=Depends(get_current_user)):
    return {"filters": _run(task_views.save_filter, user, body.name, body.definition, project_key=body.project, shared=body.shared)}


@router.delete("/filters/{filter_id}")
def delete_filter(filter_id: int, user=Depends(get_current_user)):
    return {"filters": _run(task_views.delete_filter, user, filter_id)}


# ------------------------------------------------------------------------------------------------------------ the inbox


@router.get("/notifications")
def notifications(unread: bool = False, limit: int = Query(default=60, ge=1, le=200), before: Optional[int] = None, user=Depends(get_current_user)):
    return _run(task_notify.inbox, user, unread_only=unread, limit=limit, before_id=before)


@router.post("/notifications/read")
def read_notifications(body: ReadIn, user=Depends(get_current_user)):
    return {"marked": _run(task_notify.mark_read, user, body.ids)}


@router.get("/reminders")
def reminders(user=Depends(get_current_user)):
    return task_notify.reminders(user)


# ------------------------------------------------------------------------------------------------------------ personal to-do


@router.get("/todo")
def todo(user=Depends(get_current_user)):
    return _run(task_todo.overview, user)


@router.post("/todo/lists")
def todo_create_list(body: TodoListIn, user=Depends(get_current_user)):
    return _run(task_todo.create_list, user, body.name)


@router.put("/todo/lists/{list_id}")
def todo_rename_list(list_id: int, body: TodoListIn, user=Depends(get_current_user)):
    return _run(task_todo.rename_list, user, list_id, body.name)


@router.delete("/todo/lists/{list_id}")
def todo_delete_list(list_id: int, user=Depends(get_current_user)):
    return _run(task_todo.delete_list, user, list_id)


@router.post("/todo/items")
def todo_add(body: TodoItemIn, request: Request, user=Depends(get_current_user)):
    return _run(task_todo.add_item, user, body.model_dump(), _once(request, user, "task.todo", body.text, str(body.list_id), body.due_date))


@router.put("/todo/items/{todo_id}")
def todo_update(todo_id: int, body: TodoItemChanges, user=Depends(get_current_user)):
    return _run(task_todo.update_item, user, todo_id, body.model_dump(exclude_unset=True))


@router.delete("/todo/items/{todo_id}")
def todo_delete(todo_id: int, user=Depends(get_current_user)):
    return _run(task_todo.delete_item, user, todo_id)


@router.post("/todo/clear")
def todo_clear(list_id: Optional[str] = None, user=Depends(get_current_user)):
    return _run(task_todo.clear_done, user, list_id)


@router.post("/todo/items/{todo_id}/task")
def todo_to_task(todo_id: int, body: TodoToTask, user=Depends(get_current_user)):
    return _run(task_todo.make_task, user, todo_id, body.project, body.model_dump(exclude={"project"}, exclude_unset=True))


# ------------------------------------------------------------------------------------------------------------ files, comments by id


@router.get("/attachments/{attachment_id}/file")
def attachment_file(attachment_id: int, download: bool = False, user=Depends(get_current_user)):
    found = _run(task_files.get_file, user, attachment_id)
    disposition = "inline" if found["inline"] and not download else "attachment"
    return Response(
        content=found["data"], media_type=found["content_type"],
        headers={"Content-Disposition": f"{disposition}; filename*=UTF-8''{quote(found['name'])}", "X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store"},
    )


@router.delete("/attachments/{attachment_id}")
def attachment_delete(attachment_id: int, user=Depends(get_current_user)):
    return {"attachments": _run(task_files.delete_attachment, user, attachment_id)}


@router.put("/comments/{comment_id}")
def comment_edit(comment_id: int, body: CommentIn, user=Depends(get_current_user)):
    return _run(task_items.edit_comment, user, comment_id, body.body)


@router.delete("/comments/{comment_id}")
def comment_delete(comment_id: int, user=Depends(get_current_user)):
    return _run(task_items.delete_comment, user, comment_id)


@router.put("/checklist/{item_id}")
def checklist_update(item_id: int, body: ChecklistChanges, user=Depends(get_current_user)):
    return {"checklist": _run(task_items.update_checklist_item, user, item_id, **body.model_dump(exclude_unset=True))}


@router.delete("/checklist/{item_id}")
def checklist_delete(item_id: int, user=Depends(get_current_user)):
    return {"checklist": _run(task_items.delete_checklist_item, user, item_id)}


@router.post("/bulk")
def bulk(body: BulkIn, user=Depends(get_current_user)):
    return _run(tasks.bulk_update, user, body.keys, body.changes)


# ------------------------------------------------------------------------------------------------------------ tasks


@router.get("")
def list_tasks(request: Request, user=Depends(get_current_user)):
    return _run(tasks.list_tasks, user, _filters(request))


@router.post("", status_code=status.HTTP_201_CREATED)
def create_task(body: TaskIn, request: Request, user=Depends(get_current_user)):
    data = body.model_dump(exclude={"project"}, exclude_none=True)
    idem = _once(request, user, "task.create", body.project, body.title, body.description, str(body.assignee_id), body.due_date)
    return _run(tasks.create_task, user, body.project, data, idem)


@router.get("/{key}")
def get_task(key: str = KEY, user=Depends(get_current_user)):
    return _run(tasks.get_task, user, key)


@router.put("/{key}")
def update_task(body: TaskChanges, key: str = KEY, user=Depends(get_current_user)):
    changes = body.model_dump(exclude_unset=True)
    expected = changes.pop("expected_updated", None)
    return _run(tasks.update_task, user, key, changes, expected)


@router.delete("/{key}")
def delete_task(key: str = KEY, user=Depends(get_current_user)):
    return _run(tasks.delete_task, user, key)


@router.post("/{key}/restore")
def restore_task(key: str = KEY, user=Depends(get_current_user)):
    return _run(tasks.restore_task, user, key)


@router.post("/{key}/move")
def move_task(body: MoveIn, key: str = KEY, user=Depends(get_current_user)):
    return _run(
        tasks.transition, user, key, body.status_id, note=body.note, resolution=body.resolution, reviewer_id=body.reviewer_id, before_key=body.before_key, after_key=body.after_key,
    )


@router.post("/{key}/review/request")
def review_request(body: ReviewRequest, key: str = KEY, user=Depends(get_current_user)):
    return _run(tasks.request_review, user, key, body.reviewer_id, body.note)


@router.post("/{key}/review/decide")
def review_decide(body: ReviewDecision, key: str = KEY, user=Depends(get_current_user)):
    return _run(tasks.decide_review, user, key, body.decision, body.note)


@router.post("/{key}/review/withdraw")
def review_withdraw(key: str = KEY, user=Depends(get_current_user)):
    return _run(tasks.withdraw_review, user, key)


@router.get("/{key}/comments")
def comments(key: str = KEY, user=Depends(get_current_user)):
    return {"comments": _run(task_items.list_comments, user, key)}


@router.post("/{key}/comments", status_code=status.HTTP_201_CREATED)
def comment_add(body: CommentIn, request: Request, key: str = KEY, user=Depends(get_current_user)):
    return _run(task_items.add_comment, user, key, body.body, _once(request, user, "task.comment", key, body.body))


@router.get("/{key}/activity")
def activity(key: str = KEY, limit: int = Query(default=100, ge=1, le=300), before: Optional[int] = None, user=Depends(get_current_user)):
    return {"activity": _run(task_items.activity, user, key, limit, before)}


@router.post("/{key}/watch")
def watch(body: WatchIn, key: str = KEY, user=Depends(get_current_user)):
    return {"watchers": _run(task_items.set_watching, user, key, body.watching, body.user_id)}


@router.post("/{key}/checklist")
def checklist_add(body: ChecklistIn, key: str = KEY, user=Depends(get_current_user)):
    return {"checklist": _run(task_items.add_checklist_item, user, key, body.text)}


@router.post("/{key}/links")
def link_add(body: LinkIn, key: str = KEY, user=Depends(get_current_user)):
    return {"links": _run(task_items.add_link, user, key, body.kind, body.other_key)}


@router.delete("/{key}/links/{link_id}")
def link_remove(link_id: int, key: str = KEY, user=Depends(get_current_user)):
    return {"links": _run(task_items.remove_link, user, key, link_id)}


@router.post("/{key}/records")
def record_add(body: RecordIn, key: str = KEY, user=Depends(get_current_user)):
    return {"records": _run(task_items.add_record_link, user, key, body.type, body.ref)}


@router.delete("/{key}/records/{link_id}")
def record_remove(link_id: int, key: str = KEY, user=Depends(get_current_user)):
    return {"records": _run(task_items.remove_record_link, user, key, link_id)}


@router.post("/{key}/time")
def time_add(body: TimeIn, key: str = KEY, user=Depends(get_current_user)):
    return _run(task_items.log_time, user, key, body.minutes, body.date, body.note)


@router.delete("/{key}/time/{log_id}")
def time_remove(log_id: int, key: str = KEY, user=Depends(get_current_user)):
    return _run(task_items.delete_time, user, key, log_id)


@router.get("/{key}/attachments")
def attachments(key: str = KEY, user=Depends(get_current_user)):
    return {"attachments": _run(task_files.attachments, user, key)}


@router.post("/{key}/attachments")
def attachment_add(file: UploadFile = File(...), comment_id: Optional[int] = Form(default=None), key: str = KEY, user=Depends(get_current_user)):
    # One byte more than the limit is read, so a file that is too big is refused without reading the rest of it.
    data = file.file.read(documents.MAX_BYTES + 1)
    return {"attachments": _run(task_files.add_attachment, user, key, file.filename, data, comment_id)}

