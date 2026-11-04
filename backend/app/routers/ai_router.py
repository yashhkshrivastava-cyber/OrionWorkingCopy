"""The AI Copilot API. Every route needs a signed-in person whose AI access is on; the assistant then does only what that
person's other permissions allow, tool by tool (see app/ai/tools)."""

from __future__ import annotations

import json
import logging
from typing import Any, Iterator, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.ai import config, insights, orchestrator, providers, safety, store
from app.ai.routing import policy as routing_policy
from app.ai.tools import core
from app.dependencies import require_admin, require_ai

router = APIRouter(prefix="/ai", tags=["ai"])
log = logging.getLogger(__name__)


# -------------------------------------------------------------------------------------------------------- status


def _routing_status(user: dict[str, Any], settings: dict[str, Any]) -> dict[str, Any]:
    """How questions are answered here: the application itself, the model on this machine, and (if at all) a cloud model."""
    from app.ai.routing import engine as routing_engine

    health = routing_engine.local_health()
    policy = store.get_policy()
    cloud_on = config.cloud_switched_on()
    usable_by_you = cloud_on and config.cloud_ready() and policy["cloud_mode"] != "local_only" and settings["allow_cloud"] and config.cloud_monthly_budget() > 0
    admin = user.get("role") == "admin"
    out: dict[str, Any] = {
        "local": {
            "provider": config.local_provider_name(), "state": health.state, "model": health.model,
            "detail": health.detail if admin else "", "installed": health.models if admin else [],
        },
        "cloud": {
            "switched_on": cloud_on, "ready": config.cloud_ready(), "provider": config.cloud_provider_name() if cloud_on else "none",
            "policy": policy["cloud_mode"], "you_allow": settings["allow_cloud"], "usable_by_you": usable_by_you,
        },
        "policies": [{"id": key, "label": text} for key, text in routing_policy.MODES.items()],
    }
    if admin:
        out["cloud"].update({"model": config.cloud_model() if cloud_on else "", "key_present": bool(config.api_key()), "budget_usd": config.cloud_monthly_budget(),
                             "spent_usd": round(store.cloud_spend_this_month(), 4), "user_daily": config.cloud_user_daily()})
    return out


@router.get("/status")
def get_status(user=Depends(require_ai)):
    settings = store.get_settings(user["id"])
    used = store.usage_today(user["id"])
    out: dict[str, Any] = {
        # The application answers common questions itself, so the Copilot is available whenever it is switched on.
        "available": config.available() and settings["enabled"],
        "switched_on": config.switched_on(),
        "settings": settings,
        "usage_today": {"requests": used["requests"], "limit": config.daily_requests()},
        "routing": _routing_status(user, settings),
    }
    if user.get("role") == "admin":
        out["admin"] = {"usage": store.usage_overview(7), "routes": store.route_overview(7)}
    return out


@router.get("/health")
def get_health(user=Depends(require_ai)):
    """A live check of the model on this machine (and, for an administrator, of the cloud provider if one is switched on)."""
    from app.ai.routing import engine as routing_engine

    local = routing_engine.local_health(force=True)
    out: dict[str, Any] = {"local": {"state": local.state, "model": local.model, "latency_ms": local.latency_ms, "detail": local.detail if user.get("role") == "admin" else "", "installed": local.models if user.get("role") == "admin" else []}}
    if user.get("role") == "admin" and config.cloud_ready():
        try:
            remote = providers.cloud_provider().health()
            out["cloud"] = {"state": remote.state, "model": remote.model, "detail": remote.detail}
        except Exception as exc:  # noqa: BLE001 - the check is for looking, not for failing
            out["cloud"] = {"state": "error", "model": "", "detail": str(exc)[:200]}
    return out


class SettingsBody(BaseModel):
    enabled: Optional[bool] = None
    keep_history: Optional[bool] = None
    show_insights: Optional[bool] = None
    allow_cloud: Optional[bool] = None


@router.put("/settings")
def put_settings(body: SettingsBody, user=Depends(require_ai)):
    saved = store.save_settings(user["id"], body.model_dump(exclude_none=True))
    insights.forget(user["id"])
    return saved


class PolicyBody(BaseModel):
    cloud_mode: str


@router.put("/policy", dependencies=[Depends(require_admin)])
def put_policy(body: PolicyBody, user=Depends(require_ai)):
    """The organisation's rule for cloud models. Only an administrator sets it; everyone else's choices can only be stricter."""
    try:
        saved = store.save_policy(body.cloud_mode, user["id"])
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    store.audit(user["id"], None, "set_cloud_policy", "write", "ok", summary=f"Cloud policy set to {saved['cloud_mode']}", confirmation_required=False)
    return saved


class ExplainBody(BaseModel):
    message: str
    context: Optional[dict] = None


@router.post("/route/explain")
def explain_route(body: ExplainBody, user=Depends(require_ai)):
    """How a request would be handled (its category, who would answer it, whether cloud AI could be used and why not), without running it."""
    from app.ai.routing import engine as routing_engine

    text = safety.clean_text(body.message, config.MAX_MESSAGE_CHARS)
    return routing_engine.explain(user, text, safety.sanitize_context(body.context or {}), store.get_settings(user["id"]), store.get_policy())


@router.delete("/history")
def clear_history(user=Depends(require_ai)):
    return {"deleted": store.delete_all_conversations(user["id"])}


# --------------------------------------------------------------------------------------------------- conversations


@router.get("/conversations")
def list_conversations(q: str = Query("", max_length=100), category: str = Query("", max_length=20), user=Depends(require_ai)):
    return {"conversations": store.list_conversations(user["id"], q, category)}


class ConversationBody(BaseModel):
    title: Optional[str] = None
    category: Optional[str] = None


@router.post("/conversations", status_code=status.HTTP_201_CREATED)
def create_conversation(body: ConversationBody, user=Depends(require_ai)):
    return store.create_conversation(user["id"], (body.title or "New conversation")[:120], body.category or "general")


@router.get("/conversations/{conversation_id}")
def get_conversation(conversation_id: int, user=Depends(require_ai)):
    conversation = store.get_conversation(user["id"], conversation_id)
    messages = store.list_messages(user["id"], conversation_id)
    if conversation is None or messages is None:
        raise HTTPException(status_code=404, detail="That conversation does not exist.")
    return {"conversation": {k: v for k, v in conversation.items() if k not in ("summary", "summarized_upto")}, "messages": messages}


@router.patch("/conversations/{conversation_id}")
def update_conversation(conversation_id: int, body: ConversationBody, user=Depends(require_ai)):
    if not store.rename_conversation(user["id"], conversation_id, body.title, body.category):
        raise HTTPException(status_code=404, detail="That conversation does not exist.")
    return {"ok": True}


@router.delete("/conversations/{conversation_id}")
def delete_conversation(conversation_id: int, user=Depends(require_ai)):
    if not store.delete_conversation(user["id"], conversation_id):
        raise HTTPException(status_code=404, detail="That conversation does not exist.")
    return {"ok": True}


# -------------------------------------------------------------------------------------------------------- chatting


class ChatBody(BaseModel):
    message: str = ""
    conversation_id: Optional[int] = None
    context: Optional[dict] = None
    regenerate: bool = False
    # The person chose cloud AI for this one question (offered when the local model is not running). The policy still has the last word.
    cloud_once: bool = False
    # When history is not kept on the server, the browser sends the earlier turns itself.
    history: Optional[list[dict]] = None


def _ephemeral(history: list[dict] | None) -> list[dict[str, str]] | None:
    if history is None:
        return None
    out = []
    for item in history[-config.RECENT_MESSAGES:]:
        role, text = item.get("role"), safety.clean_text(item.get("text"), 6000)
        if role in ("user", "assistant") and text:
            out.append({"role": role, "text": text})
    return out


def _sse(events: Iterator[dict[str, Any]]) -> Iterator[str]:
    try:
        for event in events:
            yield "data: " + json.dumps(event, default=str, separators=(",", ":")) + "\n\n"
    except GeneratorExit:
        events.close()  # type: ignore[attr-defined]
        raise


@router.post("/chat")
def chat(body: ChatBody, user=Depends(require_ai)):
    events = orchestrator.run_turn(
        user, body.message, conversation_id=body.conversation_id, page=body.context, ephemeral=_ephemeral(body.history), regenerate=body.regenerate, cloud_once=body.cloud_once,
    )
    return StreamingResponse(_sse(events), media_type="text/event-stream", headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"})


# ------------------------------------------------------------------------------------- confirming what was prepared


def _record_outcome(claimed: dict[str, Any], user: dict[str, Any], text: str, ok: bool, action_id: str) -> None:
    if claimed.get("conversation_id"):
        title = claimed["preview"].get("title", "")
        store.add_message(claimed["conversation_id"], "assistant", text, [{"type": "action_result", "ok": ok, "title": title, "text": text, "action_id": action_id}])


@router.post("/actions/{action_id}/confirm")
def confirm_action(action_id: str, user=Depends(require_ai)):
    claimed = store.claim_pending(user["id"], action_id)
    if claimed is None:
        raise HTTPException(status_code=409, detail="This has expired or was already handled. Ask me again if you still want it.")
    found = core.REGISTRY.get(claimed["tool"])
    entity = str(claimed["args"].get(found.entity_arg)) if found and found.entity_arg and claimed["args"].get(found.entity_arg) else None
    ctx = core.ToolContext(user=user, conversation_id=claimed["conversation_id"])
    try:
        result = core.run_confirmed(ctx, claimed["tool"], claimed["args"])
    except core.ToolError as exc:
        store.resolve_pending(action_id, "failed", {"error": str(exc)})
        store.audit(user["id"], claimed["conversation_id"], claimed["tool"], "write", "refused", entity=entity, args=safety.trim_strings(claimed["args"], 120), error=str(exc), confirmation_required=True, confirmed_by_user=True)
        _record_outcome(claimed, user, f"That was not done: {exc}", False, action_id)
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        log.exception("Confirmed AI action %s failed", claimed["tool"])
        store.resolve_pending(action_id, "failed", {"error": "failed"})
        store.audit(user["id"], claimed["conversation_id"], claimed["tool"], "write", "error", entity=entity, args=safety.trim_strings(claimed["args"], 120), error=repr(exc), confirmation_required=True, confirmed_by_user=True)
        _record_outcome(claimed, user, "Something went wrong, so that was not done. Please try again.", False, action_id)
        raise HTTPException(status_code=500, detail="Something went wrong, so that was not done. Please try again.") from exc
    store.resolve_pending(action_id, "confirmed", {"summary": result.summary})
    store.audit(user["id"], claimed["conversation_id"], claimed["tool"], "write", "ok", entity=entity, args=safety.trim_strings(claimed["args"], 120), summary=result.summary, confirmation_required=True, confirmed_by_user=True)
    _record_outcome(claimed, user, result.summary, True, action_id)
    insights.forget(user["id"])
    return {"ok": True, "summary": result.summary, "data": result.data}


@router.post("/actions/{action_id}/cancel")
def cancel_action(action_id: str, user=Depends(require_ai)):
    pending = store.get_pending(user["id"], action_id)
    if pending is None or not store.cancel_pending(user["id"], action_id):
        raise HTTPException(status_code=409, detail="This has expired or was already handled.")
    store.audit(user["id"], pending["conversation_id"], pending["tool"], "write", "cancelled", args=safety.trim_strings(pending["args"], 120), summary=pending["preview"].get("title"), confirmation_required=True, confirmed_by_user=False)
    _record_outcome({"conversation_id": pending["conversation_id"], "preview": pending["preview"]}, user, "Cancelled. Nothing was changed.", False, action_id)
    return {"ok": True}


# -------------------------------------------------------------------------------------------------- files, tasks


@router.get("/files/{file_id}")
def download_file(file_id: str, user=Depends(require_ai)):
    found = store.get_file(user["id"], file_id)
    if found is None:
        raise HTTPException(status_code=404, detail="That file has expired or is not yours.")
    from urllib.parse import quote

    store.audit(user["id"], None, "download_file", "read", "ok", summary=found["name"])
    return Response(
        content=found["data"], media_type=found["content_type"],
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(found['name'])}", "X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store"},
    )


@router.get("/tasks")
def list_tasks(state: str = Query("open", pattern="^(open|done|dismissed|all)$"), user=Depends(require_ai)):
    return {"tasks": store.list_tasks(user["id"], state)}


class TaskBody(BaseModel):
    status: str


@router.patch("/tasks/{task_id}")
def update_task(task_id: int, body: TaskBody, user=Depends(require_ai)):
    if not store.update_task(user["id"], task_id, body.status):
        raise HTTPException(status_code=404, detail="That reminder does not exist.")
    insights.forget(user["id"])
    return {"ok": True}


# ------------------------------------------------------------------------------------- insights and suggestions


@router.get("/insights")
def get_insights(fresh: bool = False, user=Depends(require_ai)):
    return {"insights": insights.compute(user, fresh=fresh)}


class DismissBody(BaseModel):
    days: int = 7


@router.post("/insights/{insight_id}/dismiss")
def dismiss_insight(insight_id: str, body: DismissBody, user=Depends(require_ai)):
    if insight_id.startswith("task:"):
        try:
            store.update_task(user["id"], int(insight_id.split(":", 1)[1]), "done")
        except ValueError:
            pass
    else:
        store.hide_insight(user["id"], insight_id, body.days)
    return {"ok": True}


@router.get("/suggestions")
def get_suggestions(path: str = "", area: str = "", view: str = "", user=Depends(require_ai)):
    page = safety.sanitize_context({"path": path, "area": area, "view": view})
    return {"suggestions": insights.suggestions(user, page)}


# --------------------------------------------------------------------------------------------------------- admin


@router.get("/audit")
def get_audit(limit: int = Query(100, ge=1, le=500), mine: bool = False, user=Depends(require_ai)):
    """Everything the assistant ran or was refused. A person sees their own; an admin sees everyone's."""
    if mine or user.get("role") != "admin":
        return {"audit": store.list_audit(user["id"], limit)}
    return {"audit": store.list_audit(None, limit)}


@router.get("/admin/overview", dependencies=[Depends(require_admin)])
def admin_overview():
    return {"usage": store.usage_overview(14), "routes": store.route_overview(14), "cloud_spent_usd": round(store.cloud_spend_this_month(), 4)}
