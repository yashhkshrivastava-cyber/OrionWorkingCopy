"""The tool layer: the only way the assistant touches the application.

The model never writes a query and never calls an endpoint. It can only ask for one of the tools registered here, with
arguments that are checked against the tool's schema. Each tool is a plain function over the application's own services
(the dashboard engine, billing, the record service ...), so it is held to the same permissions and rules as a person
using the screens.

For every call, in this order:

    1. the tool must exist and be one the person is allowed to use (``Tool.needs``), checked again here even though the
       model was only shown permitted tools;
    2. the arguments must satisfy the schema (types, ranges, enums, lengths, no extra keys);
    3. a tool that changes things and is not trivially safe does not run: it is *prepared* (checked, and a preview built
       from the validated arguments) and held until the person confirms it on screen;
    4. everything, allowed or refused, is written to the audit trail.

What comes back to the model is wrapped as untrusted data (``safety.wrap_untrusted``).
"""

from __future__ import annotations

import logging
import time
from contextlib import ExitStack
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Callable

from app.ai import safety, store
from app.database import db_cursor

log = logging.getLogger(__name__)

READ, WRITE, UI = "read", "write", "ui"


class ToolError(Exception):
    """A refusal or a problem the person (and the model) can be told about in plain words."""


class ToolInputError(ToolError):
    """The arguments did not satisfy the schema."""


@dataclass
class ToolContext:
    """Who is asking, where they are, and what has been gathered so far in this answer."""

    user: dict[str, Any]
    conversation_id: int | None = None
    page: dict[str, Any] = field(default_factory=dict)
    today: date = field(default_factory=date.today)
    blocks: dict[str, dict[str, Any]] = field(default_factory=dict)
    sources: list[dict[str, Any]] = field(default_factory=list)
    known_numbers: list[float] = field(default_factory=list)
    ui_actions: list[dict[str, Any]] = field(default_factory=list)
    _open: ExitStack = field(default_factory=ExitStack, repr=False)
    _cursor: Any = field(default=None, repr=False)

    def cursor(self):
        """A database cursor for the tool now running. Dashboard figures are worked out lazily, so the cursor has to stay
        open until the tool has finished; ``release`` (called by ``execute``) closes it."""
        if self._cursor is None:
            self._cursor = self._open.enter_context(db_cursor())
        return self._cursor

    def release(self) -> None:
        self._cursor = None
        self._open.close()

    def block(self, kind: str, **data: Any) -> str:
        """Registers something to draw (metric cards, a table, a chart). The model can place it; it cannot change it."""
        block_id = f"b{len(self.blocks) + 1}"
        self.blocks[block_id] = {"id": block_id, "kind": kind, **data}
        return block_id

    def source(self, label: str, detail: str = "", path: str | None = None) -> None:
        item = {"label": label, "detail": detail, "path": path}
        if item not in self.sources:
            self.sources.append(item)

    def remember(self, value: Any) -> None:
        """Counts the numbers in ``value`` as retrieved, so an answer that states them can be checked."""
        self.known_numbers.extend(safety.numbers_in(value))


@dataclass
class ToolResult:
    data: Any
    summary: str = ""


@dataclass
class Tool:
    name: str
    description: str
    schema: dict[str, Any]
    kind: str
    needs: Callable[[dict[str, Any]], bool]
    handler: Callable[[ToolContext, dict[str, Any]], ToolResult]
    label: str
    risk: str = "none"
    confirm: bool = False
    # For a tool that waits for confirmation: checks the arguments against the current state and describes the change.
    prepare: Callable[[ToolContext, dict[str, Any]], dict[str, Any]] | None = None
    entity_arg: str | None = None


REGISTRY: dict[str, Tool] = {}


def tool(**spec: Any):
    """Registers a function as a tool. The schema is a JSON schema of an object."""

    def register(function: Callable[[ToolContext, dict[str, Any]], ToolResult]):
        schema = spec.pop("schema", {"type": "object", "properties": {}})
        schema.setdefault("type", "object")
        schema.setdefault("properties", {})
        schema["additionalProperties"] = False
        REGISTRY[spec["name"]] = Tool(handler=function, schema=schema, **spec)
        return function

    return register


def allowed_tools(user: dict[str, Any]) -> list[Tool]:
    return [t for t in REGISTRY.values() if t.needs(user)]


def specs_for(user: dict[str, Any]) -> list[dict[str, Any]]:
    """The tools the model is offered: only those this person may use."""
    return [{"name": t.name, "description": t.description, "input_schema": t.schema} for t in allowed_tools(user)]


# ------------------------------------------------------------------------------------------------------ validation

_TYPES: dict[str, tuple[type, ...]] = {
    "string": (str,),
    "integer": (int,),
    "number": (int, float),
    "boolean": (bool,),
    "array": (list,),
    "object": (dict,),
}


def validate(schema: dict[str, Any], value: Any, path: str = "input") -> Any:
    """Checks ``value`` against a small JSON schema and returns it cleaned. Raises ToolInputError."""
    kind = schema.get("type")
    if kind:
        if kind == "integer" and isinstance(value, float) and value.is_integer():
            value = int(value)
        expected = _TYPES.get(kind, ())
        ok = isinstance(value, expected) and not (kind in ("integer", "number") and isinstance(value, bool))
        if not ok:
            raise ToolInputError(f"{path} must be a {kind}.")
    if "enum" in schema and value not in schema["enum"]:
        raise ToolInputError(f"{path} must be one of: {', '.join(map(str, schema['enum']))}.")
    if isinstance(value, str):
        value = safety.clean_text(value, schema.get("maxLength", 500) + 1)
        if len(value) > schema.get("maxLength", 500):
            raise ToolInputError(f"{path} is too long.")
        if len(value) < schema.get("minLength", 0):
            raise ToolInputError(f"{path} is too short.")
        if "pattern" in schema:
            import re

            if not re.fullmatch(schema["pattern"], value):
                raise ToolInputError(f"{path} is not in the expected form.")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            raise ToolInputError(f"{path} must be at least {schema['minimum']}.")
        if "maximum" in schema and value > schema["maximum"]:
            raise ToolInputError(f"{path} must be at most {schema['maximum']}.")
    if isinstance(value, list):
        if len(value) > schema.get("maxItems", 50):
            raise ToolInputError(f"{path} has too many items.")
        item_schema = schema.get("items")
        if item_schema:
            value = [validate(item_schema, item, f"{path}[{i}]") for i, item in enumerate(value)]
    if isinstance(value, dict) and (schema.get("properties") is not None):
        properties = schema["properties"]
        extra = [k for k in value if k not in properties]
        if extra and not schema.get("additionalProperties", True):
            raise ToolInputError(f"{path} has unknown field(s): {', '.join(sorted(map(str, extra))[:5])}.")
        cleaned = {}
        for key, sub in value.items():
            if key in properties:
                cleaned[key] = validate(properties[key], sub, f"{path}.{key}") if properties[key] else sub
            else:
                cleaned[key] = sub
        for key in schema.get("required", []):
            if key not in cleaned or cleaned[key] in (None, ""):
                raise ToolInputError(f"{path}.{key} is required.")
        value = cleaned
    return value


# -------------------------------------------------------------------------------------------------------- running


@dataclass
class Outcome:
    """What running (or refusing) one tool call produced."""

    for_model: str
    ok: bool
    label: str
    summary: str = ""
    pending: dict[str, Any] | None = None
    ui: list[dict[str, Any]] = field(default_factory=list)
    refused: bool = False
    #: What the tool returned, before it was wrapped for a model. The application's own answers are written from this.
    data: Any = None
    tool: str = ""
    args: dict[str, Any] = field(default_factory=dict)


def _args_for_audit(args: dict[str, Any]) -> dict[str, Any]:
    return safety.trim_strings(args, 120)


def execute(ctx: ToolContext, name: str, raw_input: Any) -> Outcome:
    """Runs one tool call the model asked for. Never raises: every failure becomes an outcome the model can read."""
    try:
        outcome = _execute(ctx, name, raw_input)
        outcome.tool = name
        outcome.args = raw_input if isinstance(raw_input, dict) else {}
        return outcome
    finally:
        ctx.release()


def _execute(ctx: ToolContext, name: str, raw_input: Any) -> Outcome:
    started = time.monotonic()
    found = REGISTRY.get(name)
    user_id = ctx.user.get("id")
    if found is None or not found.needs(ctx.user):
        store.audit(user_id, ctx.conversation_id, name, "unknown" if found is None else found.kind, "denied", summary="Not available to this person")
        text = "That tool is not available." if found is None else "You do not have access to that. Say so, and do not try another way around it."
        return Outcome(safety.wrap_untrusted({"error": text}, ok=False), False, "Checking access", refused=True)

    try:
        args = validate(found.schema, raw_input if raw_input is not None else {})
    except ToolInputError as exc:
        store.audit(user_id, ctx.conversation_id, name, found.kind, "invalid", args=_args_for_audit(raw_input if isinstance(raw_input, dict) else {}), error=str(exc))
        return Outcome(safety.wrap_untrusted({"error": str(exc), "hint": "Fix the arguments and call again."}, ok=False), False, found.label)

    entity = str(args.get(found.entity_arg)) if found.entity_arg and args.get(found.entity_arg) else None
    try:
        if found.confirm:
            assert found.prepare is not None
            preview = found.prepare(ctx, args)
            action_id = store.create_pending(user_id, ctx.conversation_id, found.name, args, preview, found.risk)
            store.audit(user_id, ctx.conversation_id, name, found.kind, "pending", entity=entity, args=_args_for_audit(args),
                        summary=preview.get("title"), confirmation_required=True, duration_ms=_ms(started))
            pending = {"id": action_id, "tool": found.name, "risk": found.risk, "preview": preview}
            data = {
                "status": "awaiting_confirmation",
                "action_id": action_id,
                "what_will_happen": preview.get("title"),
                "instruction": "Nothing has been changed. A confirmation card is now shown to the person. Tell them briefly what you "
                               "prepared and that it needs their confirmation. Do not call this tool again.",
            }
            return Outcome(safety.wrap_untrusted(data), True, found.label, summary=preview.get("title", ""), pending=pending)

        result = found.handler(ctx, args)
        ctx.remember(result.data)
        store.audit(user_id, ctx.conversation_id, name, found.kind, "ok", entity=entity, args=_args_for_audit(args),
                    summary=result.summary, duration_ms=_ms(started))
        return Outcome(safety.wrap_untrusted(result.data), True, found.label, summary=result.summary, data=result.data, tool=name)
    except ToolError as exc:
        store.audit(user_id, ctx.conversation_id, name, found.kind, "refused", entity=entity, args=_args_for_audit(args), error=str(exc), duration_ms=_ms(started))
        return Outcome(safety.wrap_untrusted({"error": str(exc)}, ok=False), False, found.label, summary=str(exc))
    except Exception as exc:  # noqa: BLE001 - the model and the person get a plain message, the log gets the detail
        log.exception("AI tool %s failed", name)
        store.audit(user_id, ctx.conversation_id, name, found.kind, "error", entity=entity, args=_args_for_audit(args), error=repr(exc), duration_ms=_ms(started))
        return Outcome(
            safety.wrap_untrusted({"error": "That lookup failed. Say that you could not retrieve it; do not guess the answer."}, ok=False),
            False,
            found.label,
            summary="Could not retrieve this",
        )


def run_confirmed(ctx: ToolContext, name: str, args: dict[str, Any]) -> ToolResult:
    """Runs a confirmed action. The caller has already claimed it; permissions are checked once more here."""
    found = REGISTRY.get(name)
    if found is None or not found.needs(ctx.user):
        raise ToolError("You no longer have access to do that.")
    validated = validate(found.schema, args)
    try:
        return found.handler(ctx, validated)
    finally:
        ctx.release()


def _ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)
