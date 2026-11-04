"""OpenAI, through the official ``openai`` package (Chat Completions). Used only when cloud models are switched on, permitted
and configured; the key is read on the server and goes nowhere else."""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Iterator

from app.ai import config
from app.ai.providers.base import AIProvider, Capabilities, Health, ProviderError, ProviderTurn, ToolCall, Usage

log = logging.getLogger(__name__)


class OpenAIProvider(AIProvider):
    name = "openai"
    location = "cloud"

    def __init__(self, client: Any = None, model: str | None = None) -> None:
        try:
            import openai
        except ImportError as exc:  # the package is in requirements.txt; this is a half-installed machine
            raise ProviderError("The openai package is not installed", kind="unavailable") from exc
        self._sdk = openai
        self._model = model if model is not None else config.cloud_model("openai")
        if client is not None:
            self._client = client
            return
        key = config.api_key("openai")
        if not key:
            raise ProviderError("OPENAI_API_KEY is not set", kind="unavailable")
        self._client = openai.OpenAI(api_key=key, max_retries=0, timeout=config.cloud_timeout())

    @property
    def model(self) -> str:
        return self._model

    def capabilities(self) -> Capabilities:
        return Capabilities(tools=True, streaming=True, structured_output=True, context_tokens=128_000, max_output_tokens=config.MAX_OUTPUT_TOKENS)

    def health(self) -> Health:
        started = time.monotonic()
        if not self._model:
            return Health("no_model", "ORION_AI_OPENAI_MODEL is not set")
        try:
            self._client.models.list()
        except self._sdk.APIConnectionError as exc:
            return Health("unreachable", f"Could not reach OpenAI: {exc}", self._model)
        except self._sdk.APIError as exc:
            return Health("error", f"OpenAI refused the check: {exc}", self._model)
        return Health("ok", "", self._model, latency_ms=int((time.monotonic() - started) * 1000))

    # --------------------------------------------------------------------------------------------- translating

    @staticmethod
    def _messages(system: str, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = [{"role": "system", "content": system}]
        for message in messages:
            content = message["content"]
            if isinstance(content, str):
                out.append({"role": message["role"], "content": content})
            elif message["role"] == "assistant":
                text = "".join(b.get("text", "") for b in content if b.get("type") == "text")
                calls = [
                    {"id": b["id"], "type": "function", "function": {"name": b["name"], "arguments": json.dumps(b.get("input") or {})}}
                    for b in content
                    if b.get("type") == "tool_use"
                ]
                entry: dict[str, Any] = {"role": "assistant", "content": text or None}
                if calls:
                    entry["tool_calls"] = calls
                out.append(entry)
            else:
                for block in content:
                    if block.get("type") == "tool_result":
                        out.append({"role": "tool", "tool_call_id": block["tool_use_id"], "content": str(block.get("content", ""))})
                    elif block.get("type") == "text":
                        out.append({"role": "user", "content": block.get("text", "")})
        return out

    def _raise(self, exc: Exception) -> None:
        sdk = self._sdk
        if isinstance(exc, sdk.APITimeoutError):
            raise ProviderError(f"OpenAI timed out: {exc}", retryable=True, kind="timeout") from exc
        if isinstance(exc, sdk.APIConnectionError):
            raise ProviderError(f"Could not reach OpenAI: {exc}", retryable=True, kind="unavailable") from exc
        if isinstance(exc, sdk.RateLimitError):
            raise ProviderError(f"OpenAI rate limit: {exc}", retryable=True, kind="rate_limited") from exc
        if isinstance(exc, sdk.APIStatusError):
            raise ProviderError(f"OpenAI returned {exc.status_code}: {exc.message}", retryable=exc.status_code >= 500, kind="unavailable" if exc.status_code >= 500 else "other") from exc
        raise ProviderError(f"OpenAI error: {exc}") from exc

    # ------------------------------------------------------------------------------------------------ answering

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
        kwargs: dict[str, Any] = {
            "model": model or self._model,
            "messages": self._messages(system, messages),
            "max_completion_tokens": max_tokens,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if tools:
            kwargs["tools"] = [{"type": "function", "function": {"name": t["name"], "description": t.get("description", ""), "parameters": t["input_schema"]}} for t in tools]
            if not allow_tools:
                kwargs["tool_choice"] = "none"
        text, partial, usage, reason = "", {}, Usage(), "end"
        try:
            for chunk in self._client.chat.completions.create(**kwargs):
                if getattr(chunk, "usage", None):
                    usage = Usage(int(chunk.usage.prompt_tokens or 0), int(chunk.usage.completion_tokens or 0))
                for choice in chunk.choices or []:
                    delta = choice.delta
                    if delta and delta.content:
                        text += delta.content
                        yield "text", delta.content
                    for piece in (delta.tool_calls or []) if delta else []:
                        slot = partial.setdefault(piece.index, {"id": "", "name": "", "args": ""})
                        slot["id"] = piece.id or slot["id"]
                        if piece.function:
                            slot["name"] = piece.function.name or slot["name"]
                            slot["args"] += piece.function.arguments or ""
                    if choice.finish_reason:
                        reason = choice.finish_reason
        except Exception as exc:  # noqa: BLE001 - mapped to a ProviderError below
            if isinstance(exc, ProviderError):
                raise
            self._raise(exc)
        calls = []
        for index in sorted(partial):
            slot = partial[index]
            try:
                arguments = json.loads(slot["args"] or "{}")
            except ValueError:
                arguments = {}
            calls.append(ToolCall(id=slot["id"] or f"call_{index + 1}", name=slot["name"], input=arguments if isinstance(arguments, dict) else {}))
        yield "turn", ProviderTurn(text=text, tool_calls=calls, stop_reason="tool_use" if calls else ("length" if reason == "length" else "end"), usage=usage)
