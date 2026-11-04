"""Keeping the assistant honest and contained.

* Everything that comes back from the database is untrusted *data*: it is wrapped, trimmed and labelled so it can never
  read as an instruction (``wrap_untrusted``).
* What the browser says about where the person is (the page, the filters) is checked and cut down (``sanitize_context``).
* A model may place only the charts, tables and cards a tool produced on the server; it cannot draw its own numbers
  (``MarkerFilter``).
* Figures in an answer are compared with the figures that were actually retrieved, so an invented number is caught
  (``unverified_figures``).
* Arithmetic is done by a small evaluator, not guessed (``safe_calc``).
* One person cannot hammer the assistant (``RateLimiter``).
"""

from __future__ import annotations

import ast
import json
import math
import operator
import re
import threading
import time
from collections import defaultdict, deque
from typing import Any, Iterable

# ----------------------------------------------------------------------------------------------------- plain text

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def clean_text(value: Any, limit: int) -> str:
    """A string with control characters removed, tidied, and cut to ``limit`` characters."""
    text = _CONTROL.sub("", str(value if value is not None else ""))
    return text.strip()[:limit]


def trim_strings(value: Any, limit: int = 300) -> Any:
    """The same structure with every long string cut short, so one huge field cannot flood the model."""
    if isinstance(value, str):
        text = _CONTROL.sub("", value)
        return text if len(text) <= limit else text[: limit - 1] + "…"
    if isinstance(value, dict):
        return {str(k)[:80]: trim_strings(v, limit) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [trim_strings(v, limit) for v in value]
    return value


def _json_default(value: Any) -> Any:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if hasattr(value, "__float__"):
        return float(value)
    return str(value)


def to_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=_json_default, separators=(",", ":"))


MAX_TOOL_CHARS = 14_000


def wrap_untrusted(data: Any, *, ok: bool = True) -> str:
    """What the model is shown for a tool's result.

    The data is serialised, trimmed and put inside a tag that says it is data. The system prompt tells the model that
    nothing inside such a tag is an instruction, whatever it says; this is the other half: the wrapper makes it
    impossible for a result to pass itself off as the conversation (it cannot close the tag, and its text is cut).
    """
    body = to_json(trim_strings(data))
    body = body.replace("</tool_data", "<\\/tool_data")
    if len(body) > MAX_TOOL_CHARS:
        body = body[:MAX_TOOL_CHARS] + '..."truncated":true}'
    status = "ok" if ok else "error"
    return f'<tool_data status="{status}" trust="untrusted">{body}</tool_data>'


# ------------------------------------------------------------------------------------------------------ context

# Only these keys of the page's state ever reach the model; everything else the browser sends is dropped.
CONTEXT_AREAS = {
    "home", "dashboard", "dashboard_tally", "data", "billing", "letterhead", "documents", "bank", "tenders", "attendance", "etl", "admin", "messages", "settings", "other",
}


def sanitize_context(raw: Any) -> dict[str, Any]:
    """The few facts about where the person is that are worth telling the model, checked."""
    from app.dashboard.filters import clean_filters

    if not isinstance(raw, dict):
        return {}
    out: dict[str, Any] = {}
    path = clean_text(raw.get("path"), 200)
    if path.startswith("/") and not path.startswith("//"):
        out["path"] = path
    for key, limit in (("title", 120), ("view", 40), ("tab", 40), ("entity", 60), ("entity_id", 60), ("dataset", 40)):
        text = clean_text(raw.get(key), limit)
        if text:
            out[key] = text
    area = clean_text(raw.get("area"), 30)
    if area in CONTEXT_AREAS:
        out["area"] = area
    filters = raw.get("filters")
    if isinstance(filters, dict):
        given = {str(k)[:30]: clean_text(v, 60) for k, v in list(filters.items())[:30]}
        # A dashboard with no period chosen shows this financial year ("current"), and "all" means every year.
        from app.dashboard.windows import resolve_fy

        given = resolve_fy(given, None)
        if out.get("area") == "dashboard_tally":
            # The Tally dashboards have their own filters (client, company, document type ...), checked by their own rules.
            from app.tally_dashboard import _clean_filters as clean_tally
            from app.tally_insights import validate_filters

            cleaned = validate_filters(clean_tally(given))[0]
        else:
            cleaned = clean_filters(given)
        if cleaned:
            out["filters"] = cleaned
    selected = raw.get("selected")
    if isinstance(selected, list):
        ids = [clean_text(item, 60) for item in selected[:20]]
        ids = [i for i in ids if i]
        if ids:
            out["selected"] = ids
    return out


def describe_context(context: dict[str, Any]) -> str:
    """The context as a few plain lines for the system prompt."""
    if not context:
        return "The person's current page is not known."
    lines = []
    if context.get("title"):
        lines.append(f"Page: {context['title']}" + (f" ({context['path']})" if context.get("path") else ""))
    elif context.get("path"):
        lines.append(f"Page: {context['path']}")
    if context.get("area"):
        lines.append(f"Area: {context['area']}")
    if context.get("view"):
        lines.append(f"Dashboard tab: {context['view']}")
    if context.get("filters"):
        lines.append("Filters applied on the page: " + ", ".join(f"{k}={v}" for k, v in context["filters"].items()))
    elif context.get("area") in ("dashboard", "dashboard_tally"):
        lines.append("Filters applied on the page: none (all time)")
    if context.get("entity"):
        lines.append(f"Record open: {context['entity']} {context.get('entity_id', '')}".strip())
    if context.get("selected"):
        lines.append("Records selected: " + ", ".join(context["selected"]))
    return "\n".join(lines) or "The person's current page is not known."


# ------------------------------------------------------------------------------------------------------ streaming

_MARKER = re.compile(r"\{\{block:([A-Za-z0-9_-]{1,32})\}\}")


class MarkerFilter:
    """Splits streamed text at ``{{block:ID}}`` markers.

    ``feed`` returns a list of ``("text", str)`` and ``("block", id)`` in order. Text that might be the start of a marker
    is held back until it is clear, so a marker split across two chunks is still recognised and a marker is never shown.
    """

    def __init__(self) -> None:
        self._held = ""

    def feed(self, chunk: str) -> list[tuple[str, str]]:
        data = self._held + chunk
        self._held = ""
        out: list[tuple[str, str]] = []
        position = 0
        for match in _MARKER.finditer(data):
            if match.start() > position:
                out.append(("text", data[position : match.start()]))
            out.append(("block", match.group(1)))
            position = match.end()
        rest = data[position:]
        cut = rest.rfind("{{")
        if cut != -1 and "}}" not in rest[cut:] and len(rest) - cut <= 48:
            self._held = rest[cut:]
            rest = rest[:cut]
        elif rest.endswith("{"):
            self._held = "{"
            rest = rest[:-1]
        if rest:
            out.append(("text", rest))
        return out

    def flush(self) -> list[tuple[str, str]]:
        held, self._held = self._held, ""
        return [("text", held)] if held else []


def strip_markers(text: str) -> str:
    return _MARKER.sub("", text)


# ------------------------------------------------------------------------------------------------------- numbers

_UNITS = {"cr": 1e7, "crore": 1e7, "crores": 1e7, "l": 1e5, "lakh": 1e5, "lakhs": 1e5, "lac": 1e5, "k": 1e3, "m": 1e6, "million": 1e6}
_FIGURE = re.compile(
    r"(?<![\w.\-/])(?:₹|rs\.?\s?|inr\s?)?(\d{1,3}(?:,\d{2,3})+|\d+)(\.\d+)?\s?(%|crores?|cr\b|lakhs?|lac\b|l\b|k\b|million|m\b)?",
    re.IGNORECASE,
)


def numbers_in(value: Any) -> list[float]:
    """Every number in a structure: numeric values, and figures written inside strings (``₹2.96 Cr``, ``8.4%``)."""
    found: list[float] = []

    def walk(item: Any) -> None:
        if isinstance(item, bool) or item is None:
            return
        if isinstance(item, (int, float)):
            if math.isfinite(item):
                found.append(float(item))
        elif isinstance(item, str):
            for _text, number in figures_in(item):
                found.append(number)
        elif isinstance(item, dict):
            for sub in item.values():
                walk(sub)
        elif isinstance(item, (list, tuple)):
            for sub in item:
                walk(sub)

    walk(value)
    return found


def figures_in(text: str) -> list[tuple[str, float]]:
    """``(the text as written, its value)`` for each figure in some prose. Percentages keep their face value."""
    out = []
    for m in _FIGURE.finditer(text):
        whole, frac, unit = m.group(1), m.group(2) or "", (m.group(3) or "").lower()
        try:
            value = float(whole.replace(",", "") + frac)
        except ValueError:
            continue
        if unit and unit != "%":
            value *= _UNITS.get(unit, 1)
        out.append((m.group(0).strip(), value))
    return out


def _close(a: float, b: float, decimals: int, scale: float) -> bool:
    tolerance = max(abs(b) * 0.006, 0.5 * (10 ** -decimals) * scale, 0.51 if decimals == 0 else 0)
    return abs(abs(a) - abs(b)) <= tolerance


def unverified_figures(answer: str, known: Iterable[float]) -> list[str]:
    """Figures the answer states that match nothing the tools returned. Small counts, years and ids are not checked.

    It tolerates rounding and Indian units (Cr, L, k): ₹2.96 Cr matches 2,959,000. A figure that is a sum or a
    difference of retrieved figures must come from the ``calculate`` tool, whose results count as retrieved.
    """
    pool = list(known)
    # Percent shown as a fraction, and the other way round, are the same figure.
    pool += [x * 100 for x in pool if abs(x) <= 5] + [x / 100 for x in pool if abs(x) >= 20]
    bad: list[str] = []
    for text, value in figures_in(strip_markers(answer)):
        has_unit = bool(re.search(r"%|₹|rs|inr|cr|lakh|lac|crore|\bk\b|million", text, re.IGNORECASE))
        digits = re.sub(r"\D", "", text.split(".")[0])
        if not has_unit and (value < 100 or 1990 <= value <= 2100 and "," not in text):
            continue  # a count of a few, a day of the month, a year
        if digits.startswith("0") and len(digits) > 1:
            continue  # an id such as 0003
        decimals = len(re.sub(r"\D", "", text.split(".")[1])) if "." in text else 0
        unit_scale = 1.0
        unit = re.search(r"(crores?|cr\b|lakhs?|lac\b|l\b|k\b|million|m\b)", text, re.IGNORECASE)
        if unit:
            unit_scale = _UNITS.get(unit.group(1).lower(), 1.0)
        if any(_close(value, x, decimals, unit_scale) for x in pool):
            continue
        if text not in bad:
            bad.append(text)
    return bad[:6]


# ------------------------------------------------------------------------------------------------------ arithmetic

_BINARY = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
    ast.Mod: operator.mod, ast.Pow: operator.pow, ast.FloorDiv: operator.floordiv,
}
_UNARY = {ast.UAdd: operator.pos, ast.USub: operator.neg}
_FUNCTIONS = {"abs": abs, "round": round, "min": min, "max": max, "sum": lambda *a: sum(a)}


class CalcError(ValueError):
    pass


def safe_calc(expression: str) -> float:
    """Evaluates arithmetic (``+ - * / % **``, brackets, abs, round, min, max, sum) and nothing else."""
    text = re.sub(r"(?<=\d),(?=\d{3}\b)", "", str(expression or "")).replace("%", "/100").replace("×", "*").replace("÷", "/").strip()
    if not text or len(text) > 300:
        raise CalcError("Give a short arithmetic expression.")
    try:
        tree = ast.parse(text, mode="eval")
    except SyntaxError as exc:
        raise CalcError("That is not a valid arithmetic expression.") from exc

    def run(node: ast.AST) -> float:
        if isinstance(node, ast.Expression):
            return run(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return float(node.value)
        if isinstance(node, ast.BinOp) and type(node.op) in _BINARY:
            left, right = run(node.left), run(node.right)
            if isinstance(node.op, ast.Pow) and (abs(right) > 12 or abs(left) > 1e9):
                raise CalcError("That power is too large.")
            if isinstance(node.op, (ast.Div, ast.Mod, ast.FloorDiv)) and right == 0:
                raise CalcError("Division by zero.")
            return float(_BINARY[type(node.op)](left, right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
            return float(_UNARY[type(node.op)](run(node.operand)))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _FUNCTIONS and not node.keywords:
            return float(_FUNCTIONS[node.func.id](*[run(arg) for arg in node.args]))
        raise CalcError("Only plain arithmetic is allowed.")

    result = run(tree)
    if not math.isfinite(result):
        raise CalcError("That did not give a number.")
    return result


# --------------------------------------------------------------------------------------------------- rate limiting


class RateLimiter:
    """At most ``per_minute`` requests a minute for each person (one process: this application runs as one)."""

    def __init__(self) -> None:
        self._hits: dict[int, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()
        self._busy: set[int] = set()

    def check(self, user_id: int, per_minute: int, now: float | None = None) -> int:
        """0 when the request may go ahead; otherwise the seconds to wait."""
        moment = time.monotonic() if now is None else now
        with self._lock:
            hits = self._hits[user_id]
            while hits and moment - hits[0] > 60:
                hits.popleft()
            if len(hits) >= per_minute:
                return max(1, int(60 - (moment - hits[0])) + 1)
            hits.append(moment)
            return 0

    def begin(self, user_id: int) -> bool:
        """One answer being written at a time per person. False when one already is."""
        with self._lock:
            if user_id in self._busy:
                return False
            self._busy.add(user_id)
            return True

    def end(self, user_id: int) -> None:
        with self._lock:
            self._busy.discard(user_id)

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()
            self._busy.clear()


limiter = RateLimiter()
