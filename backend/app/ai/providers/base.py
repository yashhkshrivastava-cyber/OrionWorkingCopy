"""What a model provider has to be able to do, so the rest of the application is not tied to one of them.

Messages use one neutral shape (the same as Anthropic's, which is the simplest to translate from):

    {"role": "user" | "assistant", "content": str | [block, ...]}
    block = {"type": "text", "text": ...}
          | {"type": "tool_use", "id": ..., "name": ..., "input": {...}}
          | {"type": "tool_result", "tool_use_id": ..., "content": str, "is_error": bool}

A tool is {"name", "description", "input_schema"} (JSON schema). A provider turns these into whatever its API wants.
A new provider is one class that implements ``stream`` (and, to be routed to sensibly, ``capabilities`` and ``health``).

The five jobs of a provider, and what they are called here:

    generate a response ............ ``complete``
    stream a response .............. ``stream``
    run a tool conversation ........ ``stream`` with ``tools``; the orchestrator runs the loop and executes the tools
    generate structured output ..... ``structured``
    check health / get capabilities  ``health`` / ``capabilities``
"""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Iterator

# Where the fixed instructions end and the details of this one request begin. A provider that can cache a prompt prefix
# caches what is before this line (the same for everyone) and not what is after it (different for each person and day).
CACHE_BOUNDARY = "<<end of fixed instructions>>"


@dataclass
class ToolCall:
    id: str
    name: str
    input: dict[str, Any]


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class ProviderTurn:
    """One complete answer from the model: some text, perhaps some tool calls, and why it stopped."""

    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    stop_reason: str = "end"
    usage: Usage = field(default_factory=Usage)


@dataclass(frozen=True)
class Capabilities:
    """What a model can be relied on to do. Workflows are chosen from this, never assumed."""

    tools: bool = True
    streaming: bool = True
    structured_output: bool = True
    context_tokens: int = 8192
    max_output_tokens: int = 2400


@dataclass
class Health:
    """Whether a provider can answer now. ``state`` is one of ok, unreachable, no_model, model_missing, error."""

    state: str
    detail: str = ""
    model: str = ""
    models: list[str] = field(default_factory=list)
    latency_ms: int | None = None

    @property
    def ok(self) -> bool:
        return self.state == "ok"


class ProviderError(Exception):
    """The provider could not answer. ``technical`` is for the server log only, never for a person.

    ``kind`` says what sort of failure it was, so the router can decide whether to retry, wait or give up:
    ``unavailable`` (cannot be reached), ``timeout``, ``rate_limited``, ``model_missing``, ``invalid`` (it answered, but not
    in the form asked for), ``busy`` (too many at once), ``other``.
    """

    def __init__(self, technical: str, *, retryable: bool = False, kind: str = "other"):
        super().__init__(technical)
        self.technical = technical
        self.retryable = retryable
        self.kind = kind


class AIProvider(ABC):
    name = "provider"
    #: "local" means the question never leaves this machine; "cloud" means it goes to the provider's servers.
    location = "local"

    @property
    def model(self) -> str:
        return ""

    @abstractmethod
    def stream(
        self,
        *,
        model: str,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_tokens: int,
        allow_tools: bool = True,
    ) -> Iterator[tuple[str, Any]]:
        """Yield ``("text", delta)`` as text is produced, then exactly one ``("turn", ProviderTurn)``.

        ``tools`` is always the full list when the conversation so far contains tool calls (providers insist on it);
        ``allow_tools=False`` says the model must answer now and not ask for another."""

    def capabilities(self) -> Capabilities:
        return Capabilities()

    def health(self) -> Health:
        return Health("ok")

    def complete(self, **kwargs: Any) -> ProviderTurn:
        """The whole answer at once, for short jobs such as summarising."""
        turn = ProviderTurn()
        for kind, value in self.stream(**kwargs):
            if kind == "turn":
                turn = value
        return turn

    def structured(self, *, model: str, system: str, prompt: str, schema: dict[str, Any], max_tokens: int = 600) -> tuple[Any, ProviderTurn]:
        """An answer that must be JSON fitting ``schema``. Raises ProviderError(kind="invalid") when it is not.

        The default asks for JSON in words and checks the result; a provider with a way to constrain the output overrides it.
        """
        from app.ai.tools.core import ToolInputError, validate

        ask = (system + "\n\nReply with one JSON object only, no other text, matching this JSON schema:\n" + json.dumps(schema)).strip()
        turn = self.complete(model=model, system=ask, messages=[{"role": "user", "content": prompt}], tools=[], max_tokens=max_tokens)
        value = parse_json(turn.text)
        if value is None:
            raise ProviderError("The model did not return JSON", kind="invalid")
        try:
            return validate(schema, value), turn
        except ToolInputError as exc:
            raise ProviderError(f"The model's JSON did not fit the schema: {exc}", kind="invalid") from exc


_FENCE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.S | re.I)


def parse_json(text: str) -> Any:
    """The JSON in a model's reply (it may be wrapped in a code fence or have a sentence before it), or None."""
    body = (text or "").strip()
    fenced = _FENCE.match(body)
    if fenced:
        body = fenced.group(1)
    for candidate in (body, body[body.find("{") : body.rfind("}") + 1] if "{" in body else ""):
        if not candidate:
            continue
        try:
            return json.loads(candidate)
        except ValueError:
            continue
    return None
