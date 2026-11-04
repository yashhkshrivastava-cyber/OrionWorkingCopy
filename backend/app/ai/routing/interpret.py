"""Letting a small model read a question without letting it run anything.

A small model on this computer is poor at free tool calling (it narrates, asks questions back, or calls the wrong tool) but
good at filling in a short form. So when the rules do not recognise a data question, the model is asked one thing: which of a
fixed list of intents is this, and what are its few slots (a metric, a period, a record type, a name)? Its answer is forced
into a JSON schema, checked, and turned into the same tool calls the rules would have made. Orion then looks the data up and
writes the answer itself, so every figure is exact and the model can neither invent one nor call anything outside the list.

    the model interprets the question; the application calculates the answer.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

from app.ai import periods
from app.ai.providers.base import AIProvider, ProviderError
from app.ai.routing import intents
from app.ai.tools.analytics import ALL_METRICS, PERIOD_METRICS

log = logging.getLogger(__name__)

UNSPECIFIED = "unspecified"

# intent: (what it means, in the words the model is shown)
MENU = {
    "summary": "how the business is doing overall, or what needs attention",
    "metric": "one figure for a period (needs metric)",
    "top": "the biggest or smallest clients, cases or domains (needs by and metric)",
    "compare": "one period against another",
    "why": "why a figure rose or fell, and who is behind it (needs metric)",
    "trend": "a figure month by month",
    "count": "how many records of a kind there are (needs entity)",
    "search": "find a record by its name (needs entity and name)",
    "owed": "which clients owe the most",
    "client_owed": "how much one named client owes, or whether it pays on time (needs name)",
    "receivables": "everything owed, by age",
    "bills_to_raise": "which cases still need to be billed",
    "inactive": "clients that have stopped buying",
    "none": "anything else: explanations, advice, drafting, chat, or a request you are not sure about",
}

PROMPT = (
    "You read questions about a security company's business data and pick how to answer them. Choose exactly one intent:\n"
    + "\n".join(f"- {name}: {meaning}" for name, meaning in MENU.items())
    + "\nFill in only the fields the intent needs, and use \"unspecified\" for the rest. Copy a name only if it is written in the question. "
    "Choose \"none\" unless one intent clearly fits."
)


def schema() -> dict[str, Any]:
    from app.ai.tools.records import ENTITY_NAMES

    def options(values) -> dict[str, Any]:
        return {"type": "string", "enum": [*values, UNSPECIFIED]}

    return {
        "type": "object",
        "properties": {
            "intent": {"type": "string", "enum": list(MENU)},
            "metric": options(ALL_METRICS),
            "period": options(periods.PRESETS),
            "by": options(("client", "case", "domain")),
            "entity": options(ENTITY_NAMES),
            "name": {"type": "string", "maxLength": 80},
        },
        "required": ["intent"],
    }


def _clean(value: Any) -> str | None:
    return None if value in (None, "", UNSPECIFIED) else str(value)


# Words a question must contain for the model's reading of it to be believed. A small model sometimes picks the wrong box; an answer to a
# question nobody asked is worse than no answer, so a reading that the question's own words do not support is thrown away.
EVIDENCE = {
    "why": r"\b(why|reason|cause|fell|fall|falling|drop|dropped|declin\w*|decreas\w*|rose|rise|rising|increas\w*|grew|growth|change[ds]?|behind|responsible|drove|down|up)\b",
    "compare": r"\b(compar\w*|versus|vs|against|than|differen\w*|change[ds]?|better|worse|more|less|previous|before)\b",
    "trend": r"\b(trend|over time|monthly|month by month|each month|history|growing|growth|going (up|down)|over the)\b",
    "top": r"\b(top|biggest|largest|best|most|highest|lowest|smallest|worst|least|leading|rank\w*|bring|earn|contribut\w*)\b",
    "count": r"\b(how many|number|count|total|many)\b",
    "client_owed": r"\b(pay|paying|paid|payment|owe|owes|owing|owed|due|dues|late|overdue|outstanding|balance|unpaid|pending|clear\w*)\b",
    "owed": r"\b(owe|owes|owing|owed|unpaid|overdue|outstanding|pending|due|receivables?)\b",
    "receivables": r"\b(owe|owes|owing|owed|unpaid|overdue|outstanding|pending|due|receivables?|ageing|aging)\b",
    "bills_to_raise": r"\b(bill|bills|billed|invoice|invoices|raise)\b",
    "inactive": r"\b(stopped|inactive|quiet|dormant|lapsed|haven'?t|hasn'?t|no longer|not (bought|billed|ordered)|churn\w*|lost|gone)\b",
    "summary": r"\b(how|doing|status|overview|summar\w*|performance|going|attention|health|business|figures|numbers|worr\w*|concerns?|problems?|issues?|wrong|know|happening|new)\b",
}


def supported(intent: str, text: str) -> bool:
    import re

    pattern = EVIDENCE.get(intent)
    return pattern is None or bool(re.search(pattern, text, re.IGNORECASE))


def to_plan(found: dict[str, Any], text: str, page: dict[str, Any] | None, today: date | None = None) -> intents.Plan | None:
    """The tool calls for what the model read, or None when it read nothing usable. Anything it names must be in the question."""
    today = today or date.today()
    intent = found.get("intent")
    if intent in (None, "none") or intent not in MENU:
        return None
    if not supported(intent, text):
        log.info("The local model's reading (%s) is not supported by the words of the question", intent)
        return None
    metric, by, entity = _clean(found.get("metric")), _clean(found.get("by")) or "client", _clean(found.get("entity"))
    name = _clean(found.get("name"))
    if name and name.lower() not in text.lower():
        name = None  # a name the question does not contain is an invention
    notes: list[str] = []
    named = intents._find_periods(text.lower(), today)
    period = named[0][0] if named else ({"period": found["period"]} if _clean(found.get("period")) else None)

    def scope(default: str) -> dict[str, Any]:
        args: dict[str, Any] = dict(period or {})
        chosen = intents.page_selection(page)
        if not period:
            if "from" in chosen or "to" in chosen:
                args.update({k: chosen[k] for k in ("from", "to") if k in chosen})
                notes.append("the dates set on the dashboard you are looking at")
            else:
                args["period"] = default
                notes.append(default.replace("_", " "))
        if chosen.get("filters"):
            args["filters"] = chosen["filters"]
        return args

    calls: list[tuple[str, dict[str, Any]]]
    if intent == "summary":
        calls = [("get_business_summary", scope("last_month"))]
    elif intent == "metric":
        if not metric:
            return None
        args = {"metric": metric}
        if metric in PERIOD_METRICS:
            args.update(scope("last_month"))
        calls = [("get_metric", args)]
    elif intent == "top":
        key = metric if metric in ("revenue", "billed", "collected", "margin", "payroll", "expenses", "outstanding") else "revenue"
        args = {"by": by, "metric": key, "limit": 10, **scope("last_12_months" if key != "outstanding" else "all_time")}
        args.pop("filters", None)
        calls = [("get_top_items", args)]
    elif intent == "compare":
        base = scope("last_month")
        period_a = {k: base[k] for k in ("period", "from", "to") if k in base}
        calls = [("compare_periods", {"period_a": period_a, **({"metrics": [metric]} if metric in PERIOD_METRICS else {})})]
    elif intent == "why":
        key = metric if metric in ("revenue", "billed", "collected", "margin", "payroll", "expenses") else "revenue"
        base = scope("last_month")
        calls = [("explain_change", {"metric": key, "by": by, "period_a": {k: base[k] for k in ("period", "from", "to") if k in base}})]
    elif intent == "trend":
        key = metric if metric in PERIOD_METRICS else "revenue"
        calls = [("get_trend", {"metric": key, **scope("last_12_months")})]
    elif intent == "count":
        if not entity:
            return None
        calls = [("count_records", {"entity": entity})]
    elif intent == "search":
        if not entity or not name:
            return None
        calls = [("search_records", {"entity": entity, "query": name, "limit": 10})]
    elif intent == "owed":
        calls = [("get_top_items", {"by": by, "metric": "outstanding", "limit": 10})]
    elif intent == "client_owed":
        if not name:
            return None
        calls = [("get_receivables", {"client": name, "limit": 5})]
    elif intent == "receivables":
        calls = [("get_receivables", {"limit": 10})]
    elif intent == "bills_to_raise":
        calls = [("get_bills_to_raise", {})]
    elif intent == "inactive":
        calls = [("find_inactive_clients", {})]
    else:
        return None
    notes.insert(0, f"my reading of your question as “{MENU[intent].split(' (')[0]}”")
    return intents.Plan(intent, calls, 0.75, notes)


def interpret(provider: AIProvider, model: str, text: str, page: dict[str, Any] | None, names=None) -> tuple[intents.Plan | None, int, int]:
    """Asks the model to read the question. Returns (plan or None, tokens in, tokens out). Raises ProviderError on a provider failure."""
    try:
        found, turn = provider.structured(model=model, system=PROMPT, prompt=text, schema=schema(), max_tokens=120)
    except ProviderError as exc:
        if exc.kind == "invalid":
            log.info("The local model's reading of a question did not fit the form: %s", exc.technical)
            return None, 0, 0
        raise
    return intents.focus_on_named_client(to_plan(found, text, page), text, names), turn.usage.input_tokens, turn.usage.output_tokens
