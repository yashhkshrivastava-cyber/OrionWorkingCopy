"""The one place a feature of the application asks a model for help.

Letters, payment reminders, document details, form filling, messages and the like each need a model to write or read a
little text. They do not each get their own idea of when text may leave this computer. They describe the job here and this
module decides, with the same rules the AI Copilot uses (``routing/policy.py``):

  * a model running on this computer is used when there is one, and nothing leaves the machine;
  * otherwise a cloud model is used only when every check passes: cloud models are switched on, the organisation's policy
    allows it, the person has allowed it, the budget and rate have room, and the provider is responding;
  * and, because these jobs hand over what the person is working on (a letter, a document, a conversation), the person
    is asked first, for each request. Their yes is the permission for that one request and is never remembered.

What a job returns is text or fields for the person to read and edit. Nothing here changes anything in the application.
What was sent and what came back is never logged; only that a job ran (which kind, which model, how long, how many tokens).
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any

from app import auth
from app.ai import config, providers, store
from app.ai.providers.base import ProviderError
from app.ai.routing import guards, policy

log = logging.getLogger(__name__)

DEFAULT_TOKENS = 700

_BLOCKED = {
    "environment": "No AI model is set up for this.",
    "policy": "Your organisation does not allow cloud AI.",
    "budget": "The cloud AI budget has been used.",
    "daily_limit": "You have used today's cloud AI allowance.",
    "provider": "The AI service is not responding. Try again in a moment.",
    "rate": "The AI service is busy. Try again in a moment.",
}


@dataclass(frozen=True)
class Job:
    """What to ask for. ``system`` is fixed text written by the feature; ``prompt`` carries the task and the person's material."""

    kind: str
    system: str
    prompt: str
    max_tokens: int = DEFAULT_TOKENS
    #: Finishes "To do this, ___ would be sent to <provider>" when there is no model on this computer.
    what: str = "what you are working on"
    #: When given, the answer must be JSON fitting this schema and comes back as ``data``.
    schema: dict[str, Any] | None = None
    #: False when the prompt holds none of the application's data (only wording), so even a policy that sends no
    #: application data to a cloud model allows it.
    needs_data: bool = True


_hits: dict[int, deque[float]] = defaultdict(deque)
PER_MINUTE = 20


def _allowed(user_id: int) -> bool:
    """At most ``PER_MINUTE`` jobs a minute for one person, whichever feature they come from."""
    now = time.monotonic()
    hits = _hits[user_id]
    while hits and now - hits[0] > 60:
        hits.popleft()
    if len(hits) >= PER_MINUTE:
        return False
    hits.append(now)
    return True


def reset_limits() -> None:
    _hits.clear()


def _unavailable(message: str, **extra: Any) -> dict[str, Any]:
    return {"status": "unavailable", "message": message, **extra}


def run(user: dict[str, Any], job: Job, *, allow_cloud_once: bool = False) -> dict[str, Any]:
    """Runs a job for a person. Returns ``{"status": "ok", ...}``, ``needs_consent`` or ``unavailable`` with a message to show."""
    user_id = user["id"]
    if not auth.can_access_ai(user):
        return _unavailable("The AI assistant is not turned on for your account.")
    if not _allowed(user_id):
        return _unavailable("You are asking for AI help very quickly. Wait a moment and try again.")
    settings = store.get_settings(user_id)
    if not settings.get("enabled", True):
        return _unavailable("The AI Copilot is switched off in your settings.")

    local = providers.local_provider()
    health = local.health() if local is not None else None
    use_local = bool(local is not None and health is not None and health.ok)

    if not use_local:
        pol = store.get_policy()
        decision = policy.decide(
            mode=pol["cloud_mode"],
            switched_on=config.cloud_switched_on(),
            ready=config.cloud_ready(),
            user_allows=bool(settings.get("allow_cloud")),
            consent_once=allow_cloud_once,
            sensitive=False,
            needs_data=job.needs_data,
            reason="unavailable",
            spend_month=store.cloud_spend_this_month() if config.cloud_ready() else 0.0,
            budget_month=config.cloud_monthly_budget(),
            estimate=guards.estimate_before(len(job.prompt) + len(job.system), job.max_tokens),
            user_answers_today=store.cloud_answers_today(user_id) if config.cloud_ready() else 0,
            user_daily_limit=config.cloud_user_daily(),
            breaker_open=guards.cloud_breaker.is_open,
            rate_ok=guards.cloud_rate.room(),
        )
        if not decision.allowed:
            # Not having allowed cloud AI in general is not a "no": a yes for this one request is the permission.
            if decision.blocked_by in ("consent", "person"):
                label = config.cloud_provider_name().capitalize()
                return {
                    "status": "needs_consent",
                    "message": (
                        f"No AI model is running on this computer. To do this, {job.what} would be sent to {label}, "
                        "a cloud AI service, for this one request."
                    ),
                }
            return _unavailable(_BLOCKED.get(decision.blocked_by or "", "AI help is not available right now."))

    started = time.monotonic()
    where = "local" if use_local else "cloud"
    try:
        if use_local:
            provider, model = local, local.model or config.local_model()
        else:
            if not guards.cloud_rate.take():
                return _unavailable("The AI service is busy. Try again in a moment.")
            provider = providers.cloud_provider()
            model = provider.model or config.cloud_model()
        data: Any = None
        if job.schema is not None:
            data, turn = provider.structured(model=model, system=job.system, prompt=job.prompt, schema=job.schema, max_tokens=job.max_tokens)
        else:
            turn = provider.complete(
                model=model, system=job.system, messages=[{"role": "user", "content": job.prompt}], tools=[], max_tokens=job.max_tokens, allow_tools=False
            )
    except ProviderError as exc:
        if not use_local:
            guards.cloud_breaker.failure()
        log.warning("AI help (%s) failed (%s): %s", job.kind, exc.kind, exc.technical)
        if exc.kind == "invalid":
            return _unavailable("The AI did not answer in a usable form. Try again.")
        return _unavailable("The AI could not help just now. Try again in a moment.")
    if not use_local:
        guards.cloud_breaker.success()
    store.log_route(
        user_id, None, category=f"assist_{job.kind}"[:40], path=where, provider=provider.name, model=model, reasons=[f"assist:{job.kind}"],
        escalated_from=None, attempts=1, latency_ms=int((time.monotonic() - started) * 1000), tokens_in=turn.usage.input_tokens,
        tokens_out=turn.usage.output_tokens,
        est_cost_usd=guards.estimate_cost(turn.usage.input_tokens, turn.usage.output_tokens) if where == "cloud" else 0.0,
        outcome="ok", cloud_blocked=None,
    )
    return {"status": "ok", "where": where, "provider": provider.name, "text": (turn.text or "").strip(), "data": data}
