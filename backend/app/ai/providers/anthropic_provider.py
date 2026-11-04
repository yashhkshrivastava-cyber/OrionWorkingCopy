"""Claude, through Anthropic's API. The key is read on the server and goes nowhere else."""

from __future__ import annotations

import logging
from typing import Any, Iterator

from app.ai import config
from app.ai.providers.base import CACHE_BOUNDARY, AIProvider, Capabilities, Health, ProviderError, ProviderTurn, ToolCall, Usage

log = logging.getLogger(__name__)


class AnthropicProvider(AIProvider):
    name = "anthropic"
    location = "cloud"

    def __init__(self, client: Any = None, model: str | None = None) -> None:
        try:
            import anthropic
        except ImportError as exc:  # the package is in requirements.txt; this is a half-installed machine
            raise ProviderError("The anthropic package is not installed") from exc
        self._sdk = anthropic
        self._model = model if model is not None else config.cloud_model("anthropic")
        if client is not None:
            self._client = client
            return
        key = config.api_key("anthropic")
        if not key:
            raise ProviderError("ANTHROPIC_API_KEY is not set", kind="unavailable")
        self._client = anthropic.Anthropic(api_key=key, max_retries=0, timeout=config.cloud_timeout())

    @property
    def model(self) -> str:
        return self._model

    def capabilities(self) -> Capabilities:
        return Capabilities(tools=True, streaming=True, structured_output=True, context_tokens=200_000, max_output_tokens=config.MAX_OUTPUT_TOKENS)

    def health(self) -> Health:
        try:
            self._client.models.list(limit=1)
        except self._sdk.APIConnectionError as exc:
            return Health("unreachable", f"Could not reach Anthropic: {exc}", self._model)
        except self._sdk.APIError as exc:
            return Health("error", f"Anthropic refused the check: {exc}", self._model)
        return Health("ok", "", self._model)

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
        sdk = self._sdk
        # The fixed instructions and the tool list repeat on every request, so the provider may cache them; the part about
        # this person and this moment changes, so it is left out of the cache.
        stable, boundary, details = system.partition(CACHE_BOUNDARY)
        if boundary:
            system_blocks = [{"type": "text", "text": stable.rstrip(), "cache_control": {"type": "ephemeral"}}, {"type": "text", "text": details.strip()}]
        else:
            system_blocks = [{"type": "text", "text": system}]
        kwargs: dict[str, Any] = {"model": model or self._model, "max_tokens": max_tokens, "system": system_blocks, "messages": messages}
        if tools:
            marked = [dict(tool) for tool in tools]
            marked[-1] = {**marked[-1], "cache_control": {"type": "ephemeral"}}
            kwargs["tools"] = marked
            if not allow_tools:
                kwargs["tool_choice"] = {"type": "none"}
        try:
            with self._client.messages.stream(**kwargs) as stream:
                for delta in stream.text_stream:
                    if delta:
                        yield "text", delta
                final = stream.get_final_message()
        except sdk.RateLimitError as exc:
            raise ProviderError(f"Anthropic rate limit: {exc}", retryable=True, kind="rate_limited") from exc
        except sdk.APIStatusError as exc:
            raise ProviderError(f"Anthropic returned {exc.status_code}: {exc.message}", retryable=exc.status_code in (429, 500, 502, 503, 529), kind="unavailable" if exc.status_code >= 500 else "other") from exc
        except sdk.APITimeoutError as exc:
            raise ProviderError(f"Anthropic timed out: {exc}", retryable=True, kind="timeout") from exc
        except sdk.APIConnectionError as exc:
            raise ProviderError(f"Could not reach Anthropic: {exc}", retryable=True, kind="unavailable") from exc
        except sdk.APIError as exc:  # anything else the SDK raises
            raise ProviderError(f"Anthropic error: {exc}") from exc

        text = "".join(block.text for block in final.content if getattr(block, "type", "") == "text")
        calls = [
            ToolCall(id=block.id, name=block.name, input=dict(block.input or {}))
            for block in final.content
            if getattr(block, "type", "") == "tool_use"
        ]
        usage = Usage(
            input_tokens=int(getattr(final.usage, "input_tokens", 0) or 0)
            + int(getattr(final.usage, "cache_read_input_tokens", 0) or 0)
            + int(getattr(final.usage, "cache_creation_input_tokens", 0) or 0),
            output_tokens=int(getattr(final.usage, "output_tokens", 0) or 0),
        )
        yield "turn", ProviderTurn(text=text, tool_calls=calls, stop_reason=str(final.stop_reason or "end"), usage=usage)
