"""One question in, a streamed answer out.

    person's question
      -> checks (switched on? within limits? one answer at a time?)
      -> the conversation is kept (unless the person keeps no history)
      -> the routing engine answers it: the application itself, the local model, or (only if permitted) a cloud model
      -> the answer, how it was made, and its sources are saved; how it was routed is logged without the content

The loop yields plain dicts (events) that the router sends as server-sent events. It never lets a provider or tool error
reach the person as anything but a short, plain message; the detail goes to the log.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Iterator

from app.ai import config, providers, safety, store
from app.ai.routing import engine, guards
from app.database import db_cursor

log = logging.getLogger(__name__)

MESSAGES = {
    "off_everywhere": "The Copilot is switched off on this server.",
    "off_for_me": "The Copilot is turned off for your account.",
    "busy": "I'm still answering your last question. Give me a moment.",
    "daily": "You've reached today's limit for the Copilot. It resets tomorrow.",
    "failed": "Something went wrong while analysing your data. Please try again.",
    "too_long": f"That message is too long. Please keep it under {config.MAX_MESSAGE_CHARS:,} characters.",
    "empty": "Type a question or a request first.",
}


def _error(code: str, message: str | None = None, **extra: Any) -> dict[str, Any]:
    return {"type": "error", "code": code, "message": message or MESSAGES.get(code, MESSAGES["failed"]), **extra}


def gate(user: dict[str, Any], text: str) -> dict[str, Any] | None:
    """The reasons a question is not taken up, as an error event; None when it may go ahead.

    No model has to be set up for the Copilot to answer (the application answers common questions itself), so a missing
    model or key is not a reason to refuse here.
    """
    from app.auth import can_access_ai

    if not config.switched_on():
        return _error("off_everywhere")
    if not can_access_ai(user) or not store.get_settings(user["id"])["enabled"]:
        return _error("off_for_me")
    if not text.strip():
        return _error("empty")
    if len(text) > config.MAX_MESSAGE_CHARS:
        return _error("too_long")
    wait = safety.limiter.check(user["id"], config.rate_per_minute())
    if wait:
        return _error("rate_limited", f"You're asking quickly. Please wait {wait} seconds and try again.", retry_after=wait)
    used = store.usage_today(user["id"])
    if used["requests"] >= config.daily_requests() or used["tokens_out"] >= config.daily_output_tokens():
        return _error("daily")
    return None


# ----------------------------------------------------------------------------------------------- what the model sees


def _history_messages(conversation_id: int | None, summarized_upto: int, ephemeral: list[dict[str, str]] | None) -> list[dict[str, Any]]:
    """Recent turns as plain text, alternating user and assistant, starting with the person."""
    if conversation_id is None:
        rows = [{"id": i, "role": m["role"], "text": m["text"]} for i, m in enumerate(ephemeral or [])]
    else:
        rows = [r for r in store.history_rows(conversation_id) if r["id"] > summarized_upto]
    rows = rows[-config.RECENT_MESSAGES:]
    merged: list[dict[str, Any]] = []
    for row in rows:
        text = safety.clean_text(row["text"], 6000)
        if not text:
            continue
        if merged and merged[-1]["role"] == row["role"]:
            merged[-1]["content"] += "\n\n" + text
        else:
            merged.append({"role": row["role"], "content": text})
    while merged and merged[0]["role"] != "user":
        merged.pop(0)
    return merged


def _digest(calls: list[tuple[str, dict[str, Any]]]) -> str:
    """A one-line note of what was looked up, kept with the answer so a follow-up ("why?") knows the period and filters."""
    bits = []
    for name, args in calls[:6]:
        useful = {k: v for k, v in args.items() if k in ("period", "from", "to", "metric", "by", "view", "filters", "entity", "id", "dataset", "kind", "period_a", "period_b")}
        bits.append(f"{name}({', '.join(f'{k}={v}' for k, v in useful.items())})" if useful else name)
    return "[Looked up this turn: " + "; ".join(bits) + "]" if bits else ""


def _category_for(tools_used: set[str]) -> str:
    if tools_used & {"generate_report", "export_data", "email_file"}:
        return "reports"
    if tools_used & {"create_reminder_or_task"}:
        return "tasks"
    if tools_used & {"create_record", "update_record", "delete_record", "search_records", "get_record", "count_records", "get_record_fields"}:
        return "records"
    if tools_used:
        return "analytics"
    return "general"


# ------------------------------------------------------------------------------------------------------- the loop


def run_turn(
    user: dict[str, Any],
    text: str,
    *,
    conversation_id: int | None,
    page: dict[str, Any] | None = None,
    ephemeral: list[dict[str, str]] | None = None,
    regenerate: bool = False,
    cloud_once: bool = False,
) -> Iterator[dict[str, Any]]:
    """Answers one question, yielding events. ``conversation_id`` None means history is not being kept.

    ``cloud_once`` is the person choosing cloud AI for this one question (after being told the local model is not running).
    It is one of the things the policy checks; it never overrides the organisation's policy or the sensitivity rules.
    """
    text = safety.clean_text(text, config.MAX_MESSAGE_CHARS + 1)
    refusal = gate(user, text or ("regenerate" if regenerate else ""))
    if refusal:
        yield refusal
        return
    if not safety.limiter.begin(user["id"]):
        yield _error("busy")
        return

    started = time.monotonic()
    ctx_page = safety.sanitize_context(page or {})
    conversation = None
    turn = engine.Turn()
    saved = False
    created_conversation = False
    conversation_id_final = conversation_id

    def save_assistant(stopped: bool = False) -> int | None:
        nonlocal saved
        if conversation_id_final is None or saved:
            return None
        saved = True
        body = turn.answer.strip()
        digest = _digest(turn.calls)
        message_id = store.add_message(
            conversation_id_final, "assistant", (body + ("\n\n" + digest if digest else "")).strip(), turn.parts + ([{"type": "stopped"}] if stopped else []),
            context=ctx_page or None, model=turn.model, tokens_in=turn.tokens_in, tokens_out=turn.tokens_out,
        )
        store.touch(conversation_id_final)
        return message_id

    def log_route(outcome: str) -> None:
        store.log_route(
            user["id"], conversation_id_final, category=turn.category, path=turn.path if turn.path in ("app", "local", "cloud") else "none",
            provider=("cloud" if turn.path == "cloud" else "local" if turn.path == "local" else None), model=turn.model or None, reasons=turn.reasons,
            escalated_from=turn.escalated_from if turn.path == "cloud" else None, attempts=max(1, turn.attempts), latency_ms=int((time.monotonic() - started) * 1000),
            tokens_in=turn.tokens_in, tokens_out=turn.tokens_out, est_cost_usd=turn.cloud_cost if turn.path == "cloud" else 0.0,
            outcome=outcome if turn.outcome == "ok" else turn.outcome, cloud_blocked=turn.cloud_blocked,
        )

    try:
        settings = store.get_settings(user["id"])
        if conversation_id is not None:
            conversation = store.get_conversation(user["id"], conversation_id)
            if conversation is None:
                yield _error("failed", "That conversation could not be found.")
                return
        elif settings["keep_history"] and ephemeral is None:
            conversation = store.create_conversation(user["id"], store.title_from(text))
            created_conversation = True
            yield {"type": "conversation", "id": conversation["id"], "title": conversation["title"], "category": conversation["category"], "created": True}
        conversation_id_final = conversation["id"] if conversation else None

        if conversation_id_final is not None:
            if regenerate:
                rows = store.history_rows(conversation_id_final)
                while rows and rows[-1]["role"] == "assistant":
                    store.delete_message(user["id"], conversation_id_final, rows.pop()["id"])
                if not rows:
                    yield _error("empty")
                    return
                text = rows[-1]["text"]
            else:
                store.add_message(conversation_id_final, "user", text, [{"type": "text", "text": text}], context=ctx_page or None)
                if not created_conversation:
                    store.set_title_if_new(conversation_id_final, store.title_from(text))

        summary = conversation["summary"] if conversation else ""
        history = _history_messages(conversation_id_final, conversation["summarized_upto"] if conversation else 0, ephemeral)
        if not history or history[-1]["role"] != "user":
            history.append({"role": "user", "content": text})

        store.add_usage(user["id"], requests=1)
        yield {"type": "start"}
        request = engine.Request(user, text, history, summary, ctx_page, conversation_id_final, settings, cloud_once)
        for event in engine.run(request, turn):
            if event["type"] == "route":
                # What the answer is shown as having been made by is saved with it (and replaced if a retry or escalation changes it).
                turn.parts[:] = [p for p in turn.parts if p.get("type") != "route"]
                turn.parts.insert(0, {k: v for k, v in event.items()})
            yield event

        message_id = save_assistant()
        store.add_usage(user["id"], tokens_in=turn.tokens_in, tokens_out=turn.tokens_out)
        log_route("ok")
        if conversation_id_final is not None:
            store.mark_category(conversation_id_final, _category_for(turn.tools))
            threading.Thread(target=_maybe_summarise, args=(conversation_id_final,), daemon=True).start()
        yield {"type": "done", "message_id": message_id, "conversation_id": conversation_id_final,
               "usage": {"in": turn.tokens_in, "out": turn.tokens_out}, "ms": int((time.monotonic() - started) * 1000), "path": turn.path}
    except GeneratorExit:
        # The person pressed Stop (or closed the page): keep what was written so far.
        save_assistant(stopped=True)
        log_route("stopped")
        raise
    except Exception:  # noqa: BLE001
        log.exception("AI turn failed")
        if turn.parts:
            save_assistant(stopped=True)
        log_route("error")
        yield _error("failed")
    finally:
        safety.limiter.end(user["id"])


# ------------------------------------------------------------------------------------------------ older turns


def _maybe_summarise(conversation_id: int) -> None:
    """When a conversation has grown, boils the older turns down so the model is not sent all of them every time.

    Only the local model is ever asked to do this (a summary is the person's own words, which do not go to a cloud model);
    with none running, a plain digest of the older turns is kept instead.
    """
    try:
        rows = store.history_rows(conversation_id)
        with db_cursor() as cur:
            cur.execute("SELECT summary, summarized_upto FROM orion_ods.ai_conversation WHERE id = %s", (conversation_id,))
            row = cur.fetchone()
        if not row:
            return
        summary, upto = row
        fresh = [r for r in rows if r["id"] > upto]
        if len(fresh) < config.SUMMARISE_AFTER_MESSAGES:
            return
        older = fresh[: len(fresh) - config.RECENT_MESSAGES]
        transcript = "\n".join(f"{r['role'].upper()}: {safety.clean_text(r['text'], 800)}" for r in older)
        instructions = ("Summarise this conversation between a person and the Orion Copilot in at most 160 words, as notes for continuing it. Keep: what was asked, the periods, "
                        "clients and filters used, the exact figures that were stated, conclusions reached and anything left open. No preamble.")
        new_summary = ""
        local = providers.local_provider()
        if local is not None and not guards.local_breaker.is_open and engine.local_health().ok:
            try:
                turn = local.complete(model=local.model, system=instructions, messages=[{"role": "user", "content": (f"Earlier notes: {summary}\n\n" if summary else "") + transcript}], tools=[], max_tokens=420)
                new_summary = turn.text.strip()
            except Exception:  # noqa: BLE001 - a plain digest is better than none
                new_summary = ""
        if not new_summary:
            new_summary = (summary + "\n" if summary else "") + "\n".join(f"- {r['role']}: {safety.clean_text(r['text'], 160)}" for r in older[-8:])
        store.set_summary(conversation_id, new_summary[:3000], older[-1]["id"])
    except Exception:  # noqa: BLE001
        log.exception("Could not summarise a conversation")
