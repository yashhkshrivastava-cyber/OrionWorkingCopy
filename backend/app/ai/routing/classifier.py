"""Working out what kind of request this is, cheaply, before anything expensive is chosen.

Rules only (words and shapes): no model is asked to classify, so classifying costs nothing and sends nothing anywhere. The
result is explainable: each category comes with the reasons that led to it, and the signals the routing policy weighs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.ai.routing import intents, sensitivity

CATEGORIES = {
    "A": "Simple conversation",
    "B": "Dashboard question",
    "C": "Data retrieval",
    "D": "Calculation or comparison",
    "E": "Summarisation",
    "F": "Multi-step reasoning",
    "G": "Complex document analysis",
    "H": "Code or technical reasoning",
    "I": "Application action",
    "J": "Sensitive or restricted",
}

_GREETING = re.compile(r"^\s*(hi|hello|hey|hii+|good\s+(morning|afternoon|evening)|thanks?( you)?|thank you|ok(ay)?|cool|great|bye|namaste|who are you|what can you do|help)\W*$", re.I)
_ACTION = re.compile(r"\b(delete|remove|create|add|new|update|change|edit|rename|set|send|email|mail|export|download|remind|reminder|schedule|open|go to|switch|turn|enable|disable|generate|make)\b", re.I)
_CALC = re.compile(r"(\d[\d,.]*\s*(%|percent)\s*(of)?\s*\d)|(\bcalculate\b)|(\d[\d,.]*\s*[-+*/x×÷]\s*\d)|\b(percentage|ratio|average of|sum of|total of|how much is)\b", re.I)
_TECH = re.compile(r"\b(code|python|javascript|typescript|sql|regex|function|script|algorithm|api|json|bug|error message|stack trace|query)\b", re.I)
_DOC = re.compile(r"\b(document|contract|agreement|policy|pdf|clause|tender|letter|uploaded|attachment|terms)\b", re.I)
_REASON = re.compile(r"\b(why|how come|reason|cause|driver|because|explain|analy[sz]e|analysis|recommend|should we|what if|forecast|predict|impact|root cause|diagnos|investigat|insight|implication|strateg|improve|opportunit|risk)\w*", re.I)
_DASH = re.compile(
    r"\b(revenue|billed|billing|collection|collected|collect|payroll|salary cost|margin|profit|expenses?|clients?|customers?|cases?|bills?|invoices?|outstanding|receivables?|overdue|owe[sd]?|"
    r"trend|dashboard|kpi|metric|month|quarter|financial year|fy|top \d+|biggest|highest|lowest|growth|decline|fell|dropped|rose|increase|decrease|compare|versus|vs\.?)\b",
    re.I,
)
_ATTENTION = re.compile(r"\b(worr\w*|concerns?|red flags?|anything (wrong|unusual|bad)|should i (know|be (aware|worried))|going on with|what('s| is) (happening|new)|problems?|issues?)\b", re.I)
_RETRIEVE = re.compile(r"\b(find|search|look up|lookup|show|list|get|which|who|what are|how many|count|number of|latest|recent|open)\b", re.I)
_SUMMARY = re.compile(r"\b(summari[sz]e|summary|tl;?dr|shorten|rewrite|rephrase|paraphrase|proofread|translate|make (it|this) (shorter|simpler))\b", re.I)
_MULTI = re.compile(r"\b(and then|then|also|as well as|step by step|first .* then|both)\b", re.I)


@dataclass
class Classification:
    category: str
    confidence: float
    reasons: list[str] = field(default_factory=list)
    signals: dict[str, Any] = field(default_factory=dict)

    @property
    def label(self) -> str:
        return CATEGORIES[self.category]

    @property
    def sensitive(self) -> bool:
        return self.signals.get("sensitivity", "none") != "none"

    def explain(self) -> dict[str, Any]:
        """What can be shown about the decision: no text from the question, only the findings."""
        return {"category": self.category, "label": self.label, "confidence": round(self.confidence, 2), "reasons": list(self.reasons), "signals": dict(self.signals)}


def estimate_tokens(*parts: str) -> int:
    return sum(len(p) for p in parts) // 4 + 1


INTENT_CATEGORY = {
    "smalltalk": "A", "summary": "B", "metric": "B", "top": "B", "owed_top": "B", "trend": "B", "anomalies": "B", "receivables": "B", "inactive": "B", "bills_to_raise": "B",
    "compare": "D", "calculate": "D", "why": "F",
    "count": "C", "search": "C", "documents": "C", "document_alerts": "C", "bills": "C", "reminders": "C",
    "delete": "I", "reminder": "I", "report": "I", "export": "I", "appearance": "I", "open_page": "I",
}


def classify(text: str, *, page: dict[str, Any] | None = None, history_chars: int = 0, plan_intent: str | None = None) -> Classification:
    """Sorts a request into a category (A to J) and records why. ``plan_intent`` is what the rules recognised, if anything:
    the application can then answer it itself."""
    plan_found = plan_intent is not None
    page = page or {}
    scan = sensitivity.scan(text)
    words = len(text.split())
    signals: dict[str, Any] = {
        "sensitivity": scan.level,
        "sensitive_kinds": scan.kinds,
        "words": words,
        "context_tokens": estimate_tokens(text) + history_chars // 4,
        "deterministic_possible": plan_found,
        "on_dashboard": page.get("area") == "dashboard",
    }
    reasons: list[str] = []

    def done(category: str, confidence: float, why: str) -> Classification:
        reasons.append(why)
        heavy = category in ("F", "G", "H") or words > 120
        signals.update(
            {
                "complexity": "high" if heavy and (words > 60 or category in ("G", "H") or bool(_MULTI.search(text))) else "medium" if heavy else "low",
                "reasoning_needed": category in ("F", "G", "H"),
                "needs_tools": category in ("B", "C", "D", "F", "I") or (category == "E" and signals["on_dashboard"]) or (category == "J" and bool(_DASH.search(text) or _RETRIEVE.search(text) or _SUMMARY.search(text) or _REASON.search(text))),
                "structured_output": category in ("B", "C", "D", "I"),
                "latency": "instant" if plan_found else "slow" if heavy else "seconds",
            }
        )
        return Classification(category, confidence, reasons, signals)

    if scan.sensitive:
        return done("J", 0.95, f"the request contains or asks about private information ({', '.join(scan.kinds[:3])})")
    if not plan_found and intents.is_definition(text):
        return done("A", 0.7, "asks what a word or idea means")
    if _GREETING.match(text) and not plan_found:
        return done("A", 0.95, "a greeting or a question about the assistant")
    if plan_found:
        # The application can answer it from its own data and rules: the kind of request it recognised sets the label.
        return done(INTENT_CATEGORY.get(plan_intent or "", "B"), 0.9, "a request the application can answer itself from its own data and rules")
    if _TECH.search(text) and not _DASH.search(text):
        return done("H", 0.7, "about code or technical detail")
    if _DOC.search(text) and (words > 25 or _REASON.search(text)):
        return done("G", 0.65, "asks for analysis of a document")
    if _SUMMARY.search(text):
        return done("E", 0.7, "asks for a summary or a rewrite")
    if _ACTION.search(text) and re.search(r"\b(delete|remove|create|add|update|change|edit|rename|send|email|remind)\b", text, re.I):
        return done("I", 0.75, "asks for something to be done in the application")
    if _CALC.search(text):
        return done("D", 0.7, "a calculation or comparison")
    if _REASON.search(text) and (_DASH.search(text) or page.get("area") in ("dashboard", "billing")):
        return done("F", 0.7, "asks why, or for analysis, about the business data")
    if _DASH.search(text) or _ATTENTION.search(text):
        return done("B", 0.7, "about dashboard figures")
    if _RETRIEVE.search(text):
        return done("C", 0.6, "asks to find or list records")
    if _REASON.search(text) or _MULTI.search(text) or words > 40:
        return done("F", 0.5, "open-ended or several steps")
    return done("A", 0.5, "general conversation")
