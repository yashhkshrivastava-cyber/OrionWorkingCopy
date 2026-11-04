"""Answering one request by the cheapest way that works, and escalating only when it has to and may.

    1. The application itself: a request the rules recognise is answered from the tools with no model at all.
    2. The local model: anything else goes to the model on this machine, with a trimmed set of tools. Its answer is checked
       (it must be grounded in a tool result, its figures must match, it must not be empty); a failed answer is retried a
       bounded number of times.
    3. A cloud model: only if the local one could not do it, the policy allows it (``policy.decide``), the person has agreed
       and there is budget. It is given the minimum: the question, and retrieved figures with names replaced.

Each step is explained in the events sent to the screen and recorded, without the content, in the route log.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Generator, Iterator

from app.ai import config, prompt, safety, store
from app.ai import providers
from app.ai.providers.base import AIProvider, Health, ProviderError
from app.ai.routing import classifier, compose, guards, intents, interpret, names, policy, pseudonym, sensitivity
from app.ai.tools import core

log = logging.getLogger(__name__)

# What a local answer is checked for, in the words a person (and a retry instruction) can read.
ISSUE_TEXT = {
    "no_lookup": "it asked a question or answered without looking anything up, when the figures can be looked up with the tools",
    "empty_answer": "it gave no answer",
    "ungrounded": "it stated figures without looking anything up",
    "unverified_figures": "some figures did not match what the tools returned",
    "tool_failures": "several of its tool calls were invalid",
}

MAX_LOCAL_TOOLS = 10
LOCAL_HISTORY_CHARS = 6000


# -------------------------------------------------------------------------------------------------------- state


@dataclass
class Request:
    user: dict[str, Any]
    text: str
    history: list[dict[str, Any]]
    summary: str
    page: dict[str, Any]
    conversation_id: int | None
    settings: dict[str, Any]
    cloud_once: bool = False


@dataclass
class Turn:
    """What has been written so far for the answer being made, which the caller saves when it is done."""

    parts: list[dict[str, Any]] = field(default_factory=list)
    answer: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    tools: set[str] = field(default_factory=set)
    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    model: str = ""
    path: str = "none"
    category: str = "A"
    cloud_cost: float = 0.0
    cloud_blocked: str | None = None
    escalated_from: str | None = None
    attempts: int = 0
    latency_ms: int = 0
    reasons: list[str] = field(default_factory=list)
    outcome: str = "ok"

    def reset(self) -> None:
        self.parts.clear()
        self.answer = ""
        self.tools.clear()
        self.calls.clear()


@dataclass
class PassResult:
    tools_ok: int = 0
    tools_bad: int = 0
    awaiting_confirmation: bool = False
    error: ProviderError | None = None
    step_limit: bool = False
    offered_tools: bool = False
    ctx: core.ToolContext | None = None


def _text(turn: Turn, delta: str) -> dict[str, Any]:
    if turn.parts and turn.parts[-1]["type"] == "text":
        turn.parts[-1]["text"] += delta
    else:
        turn.parts.append({"type": "text", "text": delta})
    turn.answer += delta
    return {"type": "text", "delta": delta}


def _emit_text(turn: Turn, ctx: core.ToolContext, shown: set[str], marker: safety.MarkerFilter, delta: str, final: bool = False) -> Iterator[dict[str, Any]]:
    pieces = marker.feed(delta) if delta else []
    if final:
        pieces += marker.flush()
    for kind, value in pieces:
        if kind == "text":
            yield _text(turn, value)
        elif value in ctx.blocks and value not in shown:
            shown.add(value)
            block = ctx.blocks[value]
            turn.parts.append({"type": "block", "block": block})
            yield {"type": "block", "block": block}


def _route_event(path: str, provider: AIProvider | None, model: str, cls: classifier.Classification, reason: str, *, blocked: str | None = None, escalated: bool = False) -> dict[str, Any]:
    label = {"app": "Orion", "local": "Local AI", "cloud": f"Cloud AI · {config.PROVIDER_LABELS.get(provider.name, provider.name) if provider else 'cloud'}"}.get(path, "")
    return {
        "type": "route", "path": path, "label": label, "provider": provider.name if provider else "orion", "model": model,
        "category": cls.category, "category_label": cls.label, "reason": reason, "cloud_blocked": blocked, "escalated": escalated,
    }


# ----------------------------------------------------------------------------------------------- the local model

_health: tuple[float, Health] | None = None


def local_health(force: bool = False) -> Health:
    """Whether the local model can answer, remembered for a few seconds so every question does not ask."""
    global _health
    provider = providers.local_provider()
    if provider is None:
        return Health("unreachable", "No local model is configured (ORION_AI_LOCAL_PROVIDER is none).")
    if not force and _health and time.monotonic() - _health[0] < 20:
        return _health[1]
    found = provider.health()
    _health = (time.monotonic(), found)
    return found


def forget_health() -> None:
    global _health
    _health = None


def select_tools(specs: list[dict[str, Any]], cls: classifier.Classification, text: str) -> list[dict[str, Any]]:
    """A small model cannot weigh thirty tools: it is given the dozen or fewer that suit the request, with short descriptions."""
    lowered = text.lower()
    groups = {
        "figures": ["get_forecast", "get_business_summary", "get_metric", "compare_periods", "explain_change", "get_top_items", "get_trend", "find_anomalies", "get_receivables", "find_inactive_clients"],
        "records": ["search_records", "get_record", "count_records", "list_bills", "search_documents", "get_document_alerts", "get_bills_to_raise", "get_records_behind_figures"],
        "bank": ["get_bank_balance", "get_bank_forecast", "search_bank_ledger"],
        "actions": ["get_record_fields", "create_record", "update_record", "delete_record", "create_reminder_or_task", "get_reminders", "export_data", "generate_report", "open_page", "set_appearance", "email_file"],
    }
    wanted = ["calculate"]
    if cls.category in ("B", "D", "E", "F") or any(w in lowered for w in ("revenue", "billed", "collect", "payroll", "margin", "trend", "dashboard", "top ", "owe", "overdue")):
        wanted += groups["figures"]
    if cls.category in ("C", "F", "G") or any(w in lowered for w in ("find", "search", "list", "which", "how many", "document", "bill ")):
        wanted += groups["records"]
    if any(w in lowered for w in ("bank", "cash", "balance", "interest", "forecast", "reconcil", "statement")):
        wanted += groups["bank"]
    if cls.category == "I" or any(w in lowered for w in ("create", "delete", "update", "remind", "export", "report", "open ", "send", "email", "switch")):
        wanted += groups["actions"]
    if len(wanted) == 1:
        wanted += groups["figures"][:4] + groups["records"][:3]
    order = {name: i for i, name in enumerate(dict.fromkeys(wanted))}
    chosen = sorted((s for s in specs if s["name"] in order), key=lambda s: order[s["name"]])[:MAX_LOCAL_TOOLS]
    return [_compact(s) for s in chosen]


def _compact(spec: dict[str, Any]) -> dict[str, Any]:
    """The same tool with a one-sentence description and no per-field prose, so it costs a fraction of the context."""
    first = spec["description"].split(". ")[0].strip()
    schema = _strip_descriptions(spec["input_schema"])
    return {"name": spec["name"], "description": first[:220], "input_schema": schema}


def _strip_descriptions(node: Any) -> Any:
    if isinstance(node, dict):
        return {k: _strip_descriptions(v) for k, v in node.items() if k != "description"}
    if isinstance(node, list):
        return [_strip_descriptions(v) for v in node]
    return node


def _fit_history(messages: list[dict[str, Any]], budget: int = LOCAL_HISTORY_CHARS) -> list[dict[str, Any]]:
    """The newest turns that fit, always ending with the person's latest message."""
    kept: list[dict[str, Any]] = []
    used = 0
    for message in reversed(messages):
        size = len(message["content"]) if isinstance(message["content"], str) else 200
        if kept and used + size > budget:
            break
        kept.append(message)
        used += size
    kept.reverse()
    while kept and kept[0]["role"] != "user":
        kept.pop(0)
    return kept or messages[-1:]


# --------------------------------------------------------------------------------------------- running one tool


def _run_tool(ctx: core.ToolContext, turn: Turn, call_id: str, name: str, args: Any) -> Generator[dict[str, Any], None, core.Outcome]:
    found = core.REGISTRY.get(name)
    label = found.label if found else "Working"
    yield {"type": "tool", "id": call_id, "label": label, "status": "running"}
    outcome = core.execute(ctx, name, args)
    turn.tools.add(name)
    turn.calls.append((name, args if isinstance(args, dict) else {}))
    status = "denied" if outcome.refused else "done" if outcome.ok else "error"
    step = {"id": call_id, "label": label, "status": status, "summary": outcome.summary}
    turn.parts.append({**step, "type": "tool"})
    yield {"type": "tool", **step}
    for action in ctx.ui_actions:
        turn.parts.append({"type": "ui", "action": action})
        yield {"type": "ui", "action": action}
    ctx.ui_actions.clear()
    if outcome.pending:
        card = {**outcome.pending, "status": "pending"}
        turn.parts.append({"type": "confirm", "action": card})
        yield {"type": "confirm", "action": card}
    return outcome


def _finish_answer(turn: Turn, ctx: core.ToolContext) -> Iterator[dict[str, Any]]:
    """What goes after any answer: figures that cannot be matched to the data, and where the data came from."""
    bad = safety.unverified_figures(turn.answer, ctx.known_numbers)
    if bad:
        notice = {"type": "notice", "kind": "unverified", "figures": bad}
        turn.parts.append(notice)
        yield notice
        log.warning("An answer states figures not found in retrieved data: %s", bad)
    if ctx.sources:
        turn.parts.append({"type": "sources", "sources": ctx.sources[:6]})
        yield {"type": "sources", "sources": ctx.sources[:6]}


def _new_context(req: Request) -> core.ToolContext:
    return core.ToolContext(user=req.user, conversation_id=req.conversation_id, page=req.page, today=date.today())


# ----------------------------------------------------------------------------------------- 1. the application itself


def _answer_with_rules(req: Request, turn: Turn, plan: intents.Plan, cls: classifier.Classification, route: dict[str, Any] | None = None) -> Iterator[dict[str, Any]]:
    """Runs a plan's tools and writes the answer from their results. ``route`` says who is credited: by default Orion itself."""
    turn.path = "app" if route is None else route["path"]
    yield route or _route_event("app", None, "", cls, "Answered directly from your data: no AI model was needed.")
    ctx = _new_context(req)
    outcomes: list[core.Outcome] = []
    if plan.clarify or plan.reply:
        marker, shown = safety.MarkerFilter(), set()
        yield from _emit_text(turn, ctx, shown, marker, plan.clarify or plan.reply or "", final=True)
        return
    for index, (name, args) in enumerate(plan.calls, 1):
        outcome = yield from _run_tool(ctx, turn, f"app_{index}", name, args)
        outcomes.append(outcome)
        if outcome.pending:
            break
    text = compose.answer(outcomes, plan.notes if plan.intent not in ("reminder", "delete", "appearance", "open_page", "calculate") else None)
    marker, shown = safety.MarkerFilter(), set()
    yield from _emit_text(turn, ctx, shown, marker, text, final=True)
    yield from _finish_answer(turn, ctx)


# ------------------------------------------------------------------------------------------ 2 and 3. a model


def _quality(res: PassResult, turn: Turn, cls: classifier.Classification, *, strict: bool = False) -> list[str]:
    """Objective checks on an answer. The model's own confidence is never used.

    ``strict`` is for an attempt that can still be retried: a model that did not look anything up is then sent back once, because a
    small model often asks a question it could have answered itself. On the last attempt a question back to the person is accepted.
    """
    issues: list[str] = []
    body = turn.answer.strip()
    if res.awaiting_confirmation:
        return issues
    if not body and not turn.parts:
        issues.append("empty_answer")
    needs_data = bool(cls.signals.get("needs_tools"))
    has_figures = any(ch.isdigit() for ch in body)
    asks_back = body.endswith("?") and len(body) < 320
    if needs_data and res.tools_ok == 0 and has_figures and not asks_back:
        issues.append("ungrounded")
    if res.ctx is not None and safety.unverified_figures(body, res.ctx.known_numbers):
        issues.append("unverified_figures")
    if res.tools_bad >= 2 and res.tools_ok == 0:
        issues.append("tool_failures")
    if needs_data and res.tools_ok == 0 and res.tools_bad == 0 and res.offered_tools and not issues and (strict or not asks_back):
        # It looked nothing up. On a try that can be repeated that is sent back; on the last, only a short question to the person is accepted
        # ("I'll look at the revenue for last month..." is a plan, not an answer).
        issues.append("no_lookup")
    return issues


def _llm_pass(
    req: Request,
    turn: Turn,
    provider: AIProvider,
    model: str,
    system: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    scrub: pseudonym.Pseudonymiser | None = None,
    max_steps: int | None = None,
) -> Generator[dict[str, Any], None, PassResult]:
    """One conversation with one model: it asks for tools, they run, it writes the answer."""
    res = PassResult(ctx=_new_context(req), offered_tools=bool(tools))
    ctx = res.ctx
    assert ctx is not None
    shown: set[str] = set()
    steps = max_steps or config.MAX_TOOL_STEPS
    messages = list(messages)
    for step in range(steps + 1):
        may_use_tools = not (res.awaiting_confirmation or step >= steps)
        marker = safety.MarkerFilter()
        step_text, turn_result = "", None
        try:
            for kind, value in provider.stream(model=model, system=system, messages=messages, tools=tools, max_tokens=config.MAX_OUTPUT_TOKENS, allow_tools=may_use_tools):
                if kind == "text":
                    step_text += value
                    if scrub is None:
                        yield from _emit_text(turn, ctx, shown, marker, value)
                elif kind == "turn":
                    turn_result = value
        except ProviderError as exc:
            res.error = exc
            return res
        if scrub is not None and step_text:
            # Names went out as labels; they come back as names. Done once the whole step is in, so a label cut in two is not missed.
            yield from _emit_text(turn, ctx, shown, marker, scrub.restore(step_text))
        yield from _emit_text(turn, ctx, shown, marker, "", final=True)
        if turn_result is None:
            res.error = ProviderError("The provider returned no answer", kind="invalid")
            return res
        turn.tokens_in += turn_result.usage.input_tokens
        turn.tokens_out += turn_result.usage.output_tokens
        if not turn_result.tool_calls:
            return res

        content: list[dict[str, Any]] = []
        if step_text.strip():
            content.append({"type": "text", "text": step_text})
        content += [{"type": "tool_use", "id": c.id, "name": c.name, "input": c.input} for c in turn_result.tool_calls]
        messages.append({"role": "assistant", "content": content})
        results = []
        for call in turn_result.tool_calls:
            outcome = yield from _run_tool(ctx, turn, call.id, call.name, call.input)
            if outcome.ok:
                res.tools_ok += 1
            else:
                res.tools_bad += 1
            sent = outcome.for_model
            if scrub is not None and outcome.ok and outcome.data is not None:
                sent = sensitivity.redact(safety.wrap_untrusted(scrub.scrub(outcome.data)))
            results.append({"type": "tool_result", "tool_use_id": call.id, "content": sent, "is_error": not outcome.ok})
            if outcome.pending:
                res.awaiting_confirmation = True
        store.add_usage(req.user["id"], tool_calls=len(turn_result.tool_calls))
        messages.append({"role": "user", "content": results})
    res.step_limit = True
    note = "I stopped after several lookups. Ask me to continue, or narrow the question."
    turn.parts.append({"type": "notice", "kind": "limit", "text": note})
    yield {"type": "notice", "kind": "limit", "text": note}
    return res


def _local_system(req: Request, summary: str, retry_reasons: list[str]) -> str:
    text = prompt.system_prompt(req.user, safety.describe_context(req.page), summary, date.today())
    text += "\n\nYou are running on a small model on this computer. Be brief. Call a tool for every figure; never state one from memory."
    if retry_reasons:
        text += "\n\nYOUR PREVIOUS ANSWER WAS REJECTED because " + " and ".join(ISSUE_TEXT.get(r, r) for r in retry_reasons) + ". Look it up with the tools and state only what they return."
    return text


def _decide_cloud(req: Request, cls: classifier.Classification, pol: dict[str, Any], *, reason: str, needs_data: bool) -> policy.CloudDecision:
    estimate = guards.estimate_before(len(req.text) + 4000, config.MAX_OUTPUT_TOKENS)
    return policy.decide(
        mode=pol["cloud_mode"],
        switched_on=config.cloud_switched_on(),
        ready=config.cloud_ready(),
        user_allows=bool(req.settings.get("allow_cloud")),
        consent_once=req.cloud_once,
        sensitive=cls.sensitive,
        needs_data=needs_data,
        reason=reason,
        spend_month=store.cloud_spend_this_month() if config.cloud_ready() else 0.0,
        budget_month=config.cloud_monthly_budget(),
        estimate=estimate,
        user_answers_today=store.cloud_answers_today(req.user["id"]) if config.cloud_ready() else 0,
        user_daily_limit=config.cloud_user_daily(),
        breaker_open=guards.cloud_breaker.is_open,
        rate_ok=guards.cloud_rate.room(),
    )


def _cloud_pass(req: Request, turn: Turn, cls: classifier.Classification, decision: policy.CloudDecision, tools: list[dict[str, Any]]) -> Generator[dict[str, Any], None, PassResult | None]:
    """The request, minimised, to the cloud model. Returns None when it could not be made at all."""
    try:
        provider = providers.cloud_provider()
    except ProviderError as exc:
        log.warning("Cloud provider unavailable: %s", exc.technical)
        return None
    model = provider.model or config.cloud_model()
    # The cloud model sees this question and the page, not the conversation so far and not who the person is.
    system = prompt.system_prompt({**req.user, "display_name": "the user"}, safety.describe_context(req.page), "", date.today())
    messages = [{"role": "user", "content": pseudonym.cap(req.text)}]
    scrub = pseudonym.Pseudonymiser() if decision.payload == "minimised" else None
    outcome: PassResult | None = None
    for attempt in range(1 + config.cloud_retries()):
        if not guards.cloud_rate.take():
            return outcome
        turn.reset()
        started = time.monotonic()
        outcome = yield from _llm_pass(req, turn, provider, model, system, messages, tools if decision.payload == "minimised" else [], scrub)
        turn.model = model
        if outcome.error is None:
            guards.cloud_breaker.success()
            turn.cloud_cost = guards.estimate_cost(turn.tokens_in, turn.tokens_out)
            return outcome
        guards.cloud_breaker.failure()
        log.warning("Cloud attempt %d failed (%s) after %.1fs: %s", attempt + 1, outcome.error.kind, time.monotonic() - started, outcome.error.technical)
        if outcome.error.kind not in ("timeout", "rate_limited", "unavailable"):
            break
    return outcome


def _answer_with_model(req: Request, turn: Turn, cls: classifier.Classification, pol: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """Local first. Cloud only when the policy allows and the local model could not do it."""
    needs_tools = bool(cls.signals.get("needs_tools"))
    all_tools = core.specs_for(req.user)
    local = providers.local_provider()
    health = local_health() if local is not None else Health("unreachable", "No local model is configured.")
    reasons: list[str] = []
    local_result: PassResult | None = None
    issues: list[str] = []
    down = local is None or not health.ok or guards.local_breaker.is_open  # cannot be asked at all
    incapable = False  # can be asked, but cannot do this
    caps = None

    if not down:
        assert local is not None
        caps = local.capabilities()
        if needs_tools and not caps.tools:
            incapable = True
            reasons.append("local_model_cannot_use_tools")
        if cls.signals["context_tokens"] > caps.context_tokens * 0.7:
            incapable = True
            reasons.append("context_too_large_for_local_model")
    else:
        reasons.append("local_unavailable" if local is None or not health.ok else "local_circuit_open")

    if not down and not incapable:
        assert local is not None and caps is not None
        model = local.model or health.model
        tools = select_tools(all_tools, cls, req.text) if caps.tools else []
        history = _fit_history(req.history)
        # For heavy analysis under the most open policy there is no point retrying a small model: go straight to the decision.
        tries = 1 + config.local_retries()
        if pol["cloud_mode"] == "cloud_eligible" and cls.signals.get("complexity") == "high" and cls.category in ("F", "G") and config.cloud_ready():
            tries = 1
        # A data question the rules did not recognise: have the model read it into a form, and let Orion do the lookup (see interpret.py).
        asks_something = cls.category == "A" and "?" in req.text and len(req.text.split()) >= 3 and not intents.is_definition(req.text)
        if (needs_tools or asks_something) and caps.structured_output and cls.category in ("A", "B", "C", "D", "F", "I") and not guards.local_breaker.is_open:
            try:
                started = time.monotonic()
                plan, tokens_in, tokens_out = interpret.interpret(local, model, req.text, req.page, names.known_names)
                turn.tokens_in += tokens_in
                turn.tokens_out += tokens_out
                guards.local_breaker.success()
            except ProviderError as exc:
                log.warning("Local model could not read the question (%s): %s", exc.kind, exc.technical)
                guards.local_breaker.failure()
                forget_health()
                plan = None
                if exc.kind in ("unavailable", "timeout", "model_missing", "busy"):
                    down = True
                    reasons.append(f"local_{exc.kind}")
            if plan is not None and plan.usable:
                turn.attempts += 1
                turn.model = model
                reasons.append(f"interpreted:{plan.intent}")
                turn.category = classifier.INTENT_CATEGORY.get(plan.intent, turn.category)
                note = "The local AI understood the question; Orion worked out the answer from your data."
                yield from _answer_with_rules(req, turn, plan, cls, _route_event("local", local, model, cls, note))
                return
            reasons.append("not_interpreted")
        retry_reasons: list[str] = []
        for attempt in range(0 if down else tries):
            turn.attempts += 1
            turn.reset()
            turn.path, turn.model = "local", model
            yield _route_event("local", local, model, cls, "Answered by the local AI model on this computer." if not retry_reasons else "Trying again with the local AI model.")
            started = time.monotonic()
            local_result = yield from _llm_pass(req, turn, local, model, _local_system(req, req.summary, retry_reasons), history, tools)
            if local_result.error is not None:
                err = local_result.error
                log.warning("Local model attempt %d failed (%s) after %.1fs: %s", attempt + 1, err.kind, time.monotonic() - started, err.technical)
                guards.local_breaker.failure()
                forget_health()
                reasons.append(f"local_{err.kind}")
                if err.kind in ("unavailable", "timeout", "model_missing", "busy"):
                    down = True
                    break
                issues = ["empty_answer"]
                if attempt < tries - 1:
                    retry_reasons = issues
                    yield {"type": "reset", "reason": "retry"}
                continue
            guards.local_breaker.success()
            issues = _quality(local_result, turn, cls, strict=attempt < tries - 1)
            if not issues:
                yield from _finish_answer(turn, local_result.ctx)  # type: ignore[arg-type]
                return
            reasons += [f"quality:{i}" for i in issues]
            if attempt < tries - 1:
                retry_reasons = issues
                yield {"type": "reset", "reason": "retry"}

    # --------------------------------------------------------------------------- the local model could not do it
    # A model that is configured but not running needs the person's say-so for each question. No model configured at all is a choice, not a
    # failure: the standing permission is enough.
    reason = "unavailable" if (down and local is not None) else "incapable" if (incapable or local is None) else "failed"
    decision = _decide_cloud(req, cls, pol, reason=reason, needs_data=needs_tools)
    turn.escalated_from = "local" if (down or incapable or issues) else None
    if decision.allowed:
        yield {"type": "reset", "reason": "escalate"}
        turn.reset()
        turn.path, turn.model = "cloud", config.cloud_model()
        try:
            cloud = providers.cloud_provider()
        except ProviderError:
            cloud = None
        yield _route_event("cloud", cloud, config.cloud_model(), cls, "Using cloud AI because the local AI could not complete this.", escalated=True)
        result = yield from _cloud_pass(req, turn, cls, decision, select_tools(all_tools, cls, req.text))
        if result is not None and result.error is None:
            if result.awaiting_confirmation or not _quality(result, turn, cls):
                yield from _finish_answer(turn, result.ctx)  # type: ignore[arg-type]
                return
            reasons.append("cloud_quality")
            outcome = "cloud_failed_checks"
        else:
            reasons.append("cloud_failed")
            outcome = "cloud_failed"
        # The cloud attempt failed as well. Say so plainly; what was written is cleared so nothing half-made is shown as an answer.
        yield {"type": "reset", "reason": "failed"}
        turn.reset()
        turn.path, turn.outcome = "none", outcome
        yield _text(turn, "Neither the local AI nor the cloud AI could complete that just now. Please try again in a moment, or ask in a simpler way.")
        return

    # ------------------------------------------------------------------ cloud is not an option: say why, plainly
    turn.cloud_blocked = decision.blocked_by
    unreliable = bool({"empty_answer", "ungrounded", "tool_failures", "no_lookup"} & set(issues))
    if local_result is not None and local_result.error is None and not unreliable and (turn.answer.strip() or turn.parts):
        # A best effort from the local model whose only flaw is figures that did not match: shown, flagged, and with the reason cloud was not used.
        yield from _finish_answer(turn, local_result.ctx)  # type: ignore[arg-type]
        note = _blocked_text(decision.blocked_by)
        turn.parts.append({"type": "notice", "kind": "cloud_blocked", "text": note, "reason": decision.blocked_by})
        yield {"type": "notice", "kind": "cloud_blocked", "text": note, "reason": decision.blocked_by}
        return
    if local_result is not None:
        yield {"type": "reset", "reason": "unreliable"}
        turn.reset()
    yield from _unavailable(turn, cls, health, local, decision, reasons, down)


def _blocked_text(blocked: str | None) -> str:
    why = {
        "environment": "cloud AI is not switched on",
        "policy": "your organisation's policy keeps everything on this computer",
        "policy_data": "your organisation's policy does not allow sending application data to cloud AI",
        "sensitivity": "this request contains private information, which stays on this computer",
        "person": "you have not allowed cloud AI in your settings",
        "consent": "cloud AI is used when the local one is not running only if you choose it for that question",
        "budget": "there is no cloud budget left",
        "daily_limit": "you have used today's cloud allowance",
        "provider": "the cloud service is not responding",
        "rate": "the cloud service is busy",
    }.get(blocked or "", "cloud AI is not available")
    return f"Answered by the local AI only, because {why}. Please check the figures."


def _unavailable(turn: Turn, cls: classifier.Classification, health: Health, local: AIProvider | None, decision: policy.CloudDecision, reasons: list[str], down: bool) -> Iterator[dict[str, Any]]:
    """No model could take the request, and cloud is not allowed (or not chosen). Offer what is possible, without sending anything."""
    turn.path, turn.outcome = "none", "unavailable"
    if local is None:
        why, help_ = "No local AI model is set up", " An administrator can set one up (see Settings > AI Copilot)."
    elif down:
        why, help_ = "The local AI model is not running", " Start it, or see Settings > AI Copilot for how."
    elif "local_model_cannot_use_tools" in reasons:
        why, help_ = "The local AI model can't look things up in your data", " A model that supports tools is needed for this kind of question."
    elif "context_too_large_for_local_model" in reasons:
        why, help_ = "This is too long for the local AI model", " Try a shorter question."
    else:
        why, help_ = "The local AI model could not answer reliably just now", " Please try again, or ask it another way."
    # Offering cloud AI for this one question is only possible when everything except the person's say-so already allows it.
    can_cloud = decision.blocked_by in ("person", "consent") and not cls.sensitive
    text = f"{why}, so I couldn't answer that one."
    if cls.sensitive:
        text += " It contains private information, so it is only ever handled on this computer."
    text += help_ + " Questions I can answer from your data without it (figures, rankings, comparisons, who owes what, reminders) still work."
    notice = {"type": "notice", "kind": "local_unavailable", "text": text, "can_use_cloud": can_cloud, "local_state": health.state}
    turn.parts.append(notice)
    yield notice


# ---------------------------------------------------------------------------------------------------- the entrance


def run(req: Request, turn: Turn) -> Iterator[dict[str, Any]]:
    """Answers the request, yielding events, and fills ``turn`` for the caller to save and log."""
    started = time.monotonic()
    plan = intents.plan(req.text, req.page, names=names.known_names)
    usable = plan is not None and plan.usable
    cls = classifier.classify(req.text, page=req.page, history_chars=sum(len(m["content"]) for m in req.history if isinstance(m["content"], str)), plan_intent=plan.intent if usable else None)
    turn.category = cls.category
    pol = store.get_policy()
    yield {"type": "plan", "category": cls.category, "category_label": cls.label}
    if usable and not cls.sensitive:
        yield from _answer_with_rules(req, turn, plan, cls)  # type: ignore[arg-type]
    else:
        yield from _answer_with_model(req, turn, cls, pol)
    turn.latency_ms = int((time.monotonic() - started) * 1000)
    turn.reasons = _reasons(cls, plan, turn)


def _reasons(cls: classifier.Classification, plan: intents.Plan | None, turn: Turn) -> list[str]:
    out = [f"class:{cls.category}"]
    if plan is not None:
        out.append(f"plan:{plan.intent}")
    if cls.sensitive:
        out.append("sensitive")
    out.append(f"path:{turn.path}")
    return out


def explain(user: dict[str, Any], text: str, page: dict[str, Any], settings: dict[str, Any], pol: dict[str, Any]) -> dict[str, Any]:
    """What would happen to this request, without doing it: the category, how it would be answered and whether cloud could be used."""
    plan = intents.plan(text, page, names=names.known_names)
    usable = plan is not None and plan.usable
    cls = classifier.classify(text, page=page, plan_intent=plan.intent if usable else None)
    req = Request(user, text, [], "", page, None, settings)
    out: dict[str, Any] = {"classification": cls.explain(), "plan": {"intent": plan.intent, "tools": [c[0] for c in plan.calls]} if usable else None}
    if usable and not cls.sensitive:
        out["route"] = "app"
        out["why"] = "The application can answer this from its own data without an AI model."
        return out
    health = local_health()
    out["local"] = {"state": health.state, "model": health.model}
    needs = bool(cls.signals.get("needs_tools"))
    failed = _decide_cloud(req, cls, pol, reason="failed", needs_data=needs)
    down = _decide_cloud(req, cls, pol, reason="unavailable", needs_data=needs)
    out["route"] = "local"
    out["why"] = "A model on this computer answers first." if health.ok else "A model on this computer would answer, but it is not running."
    out["cloud_if_local_fails"] = {"allowed": failed.allowed, "blocked_by": failed.blocked_by, "checks": failed.explain()}
    out["cloud_if_local_is_down"] = {"allowed": down.allowed, "blocked_by": down.blocked_by}
    return out
