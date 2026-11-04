"""A deterministic stand-in for a model, for tests and for looking at the screens without an API key.

It reads the person's last message for a few phrases, asks for the matching tools, and then writes an answer that places
the blocks those tools produced. It does no reasoning and states no figures of its own; it exists so that everything
around the model (tools, permissions, confirmation, audit, streaming, the chat screen) can be exercised end to end.
It is refused in production (see ``providers.get_provider``).
"""

from __future__ import annotations

import json
import re
from datetime import date, timedelta
from typing import Any, Iterator

from app.ai.providers.base import AIProvider, Capabilities, Health, ProviderTurn, ToolCall, Usage

_PERIODS = (
    ("last month", "last_month"), ("this month", "this_month"), ("last quarter", "last_quarter"), ("this quarter", "this_quarter"),
    ("last year", "last_fy"), ("this year", "this_fy"), ("financial year", "this_fy"), ("last 12 months", "last_12_months"), ("all time", "all_time"),
)


def _period(text: str, default: str) -> str:
    for phrase, preset in _PERIODS:
        if phrase in text:
            return preset
    return default


def _plan(text: str) -> list[tuple[str, dict[str, Any]]]:
    """The tool calls this message asks for, in order. Empty means just answer."""
    t = text.lower()
    if re.search(r"\b(ignore|disregard)\b.*\b(instruction|rule)s?\b|\bdirectly\b.*\bdatabase\b|\bquery the database\b|\bsql\b", t):
        return []
    if "delete everything" in t or "delete all" in t:
        return []
    if "delete" in t:
        m = re.search(r"delete (?:the )?(client|case|contact|opportunity)\s+(\S+)", t)
        if m:
            return [("delete_record", {"entity": m.group(1).capitalize(), "id": m.group(2).upper()})]
        return []
    if "remind" in t:
        due = (date.today() + timedelta(days=7 if "next week" in t else 1)).isoformat()
        return [("create_reminder_or_task", {"kind": "reminder", "title": re.sub(r"^.*?remind me( to)?", "", text, flags=re.I).strip(" .") or "Follow up", "due_date": due, "link_to_current_page": "this" in t})]
    if "dark mode" in t or "light mode" in t:
        return [("set_appearance", {"mode": "dark" if "dark" in t else "light"})]
    if "export" in t:
        if "bill" in t:
            return [("export_data", {"dataset": "bills", "period": _period(t, "last_12_months")})]
        return [("export_data", {"entity": "Client", "format": "xlsx"})]
    if "report" in t:
        kind = "receivables" if re.search(r"receivable|owe|overdue", t) else "revenue_by_client" if "client" in t or "customer" in t else "monthly_summary"
        return [("generate_report", {"kind": kind, "period": _period(t, "last_month")})]
    if re.search(r"\bwhy\b|responsible|drove|decline|fell|fall\b", t):
        return [("explain_change", {"metric": "revenue", "period_a": {"period": "last_month"}})]
    if re.search(r"compare|versus|\bvs\b|changed", t):
        return [("compare_periods", {"period_a": {"period": _period(t, "last_month")}})]
    if re.search(r"top \d+|top clients|top customers|biggest clients|who owes|owe us", t):
        n = re.search(r"top (\d+)", t)
        owes = bool(re.search(r"owe", t))
        return [("get_top_items", {"by": "client", "metric": "outstanding" if owes else "revenue", "limit": int(n.group(1)) if n else 10, "period": _period(t, "last_12_months")})]
    if re.search(r"trend|over the last|month by month", t):
        return [("get_trend", {"metric": "revenue", "period": _period(t, "last_12_months")})]
    if re.search(r"summar|how are we|focus|problem|dashboard", t):
        return [("get_business_summary", {"period": _period(t, "last_month")})]
    if re.search(r"how many|count", t):
        return [("count_records", {"entity": "Client"})]
    if re.search(r"find|search|look up|show .*client", t):
        return [("search_records", {"entity": "Client", "query": re.sub(r"^.*?(?:find|search|look up|show)( me)?( the)?( client)?", "", text, flags=re.I).strip(" ?.")[:60]})]
    return []


def _tool_data(content: Any) -> dict[str, Any] | None:
    if not isinstance(content, str):
        return None
    m = re.search(r"<tool_data[^>]*>(.*)</tool_data>", content, re.S)
    if not m:
        return None
    try:
        data = json.loads(m.group(1))
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _answer(messages: list[dict[str, Any]]) -> str:
    """Wording for whatever the tools just returned: place their blocks and say what they say about themselves."""
    lines: list[str] = []
    for block in messages[-1]["content"]:
        if block.get("type") != "tool_result":
            continue
        if block.get("is_error"):
            data = _tool_data(block.get("content")) or {}
            lines.append(str(data.get("error") or data.get("message") or "That did not work."))
            continue
        data = _tool_data(block.get("content")) or {}
        if data.get("status") == "awaiting_confirmation":
            lines.append("I've prepared that. It is waiting for your confirmation on screen before anything changes.")
            continue
        if data.get("empty"):
            lines.append("I couldn't find data matching that request.")
            continue
        if data.get("summary"):
            lines.append(str(data["summary"]))
        for shown in data.get("blocks") or []:
            if isinstance(shown, dict) and shown.get("id"):
                lines.append("{{block:%s}}" % shown["id"])
    return "\n\n".join(lines) if lines else "Done."


def _refusal(text: str) -> str:
    t = text.lower()
    if "delete" in t:
        return "I can't delete many things at once. Tell me the one record you want removed and I'll prepare it for your confirmation."
    return "I can't do that. I only work through the tools this application gives me and your own permissions. I can summarise the dashboards, compare periods, list records or prepare reports instead."


class ScriptedProvider(AIProvider):
    name = "scripted"
    location = "local"

    @property
    def model(self) -> str:
        return "scripted"

    def capabilities(self) -> Capabilities:
        return Capabilities(tools=True, streaming=True, structured_output=False, context_tokens=32_000)

    def health(self) -> Health:
        return Health("ok", "", "scripted")

    def stream(self, *, model: str, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]], max_tokens: int, allow_tools: bool = True) -> Iterator[tuple[str, Any]]:
        usage = Usage(input_tokens=max(1, len(system) // 4), output_tokens=40)
        last = messages[-1] if messages else {"role": "user", "content": ""}
        if last["role"] == "user" and isinstance(last["content"], list):
            text = _answer(messages)
            for word in re.findall(r"\S+\s*", text):
                yield "text", word
            yield "turn", ProviderTurn(text=text, usage=usage)
            return
        question = last["content"] if isinstance(last["content"], str) else ""
        if system.startswith("Summarise this conversation"):
            text = "The person asked about the business; figures were looked up from the dashboards."
            yield "text", text
            yield "turn", ProviderTurn(text=text, usage=usage)
            return
        offered = {t["name"] for t in tools} if allow_tools else set()
        plan = [(name, args) for name, args in _plan(question) if name in offered]
        if plan:
            calls = [ToolCall(id=f"toolu_{i}", name=name, input=args) for i, (name, args) in enumerate(plan, 1)]
            lead = "Let me look that up."
            yield "text", lead
            yield "turn", ProviderTurn(text=lead, tool_calls=calls, stop_reason="tool_use", usage=usage)
            return
        planned = _plan(question)
        text = (
            "I don't have a way to do that for your account, so I can't. " if planned
            else _refusal(question)
        )
        for word in re.findall(r"\S+\s*", text):
            yield "text", word
        yield "turn", ProviderTurn(text=text, usage=usage)
