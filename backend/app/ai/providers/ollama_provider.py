"""A model running on this machine, through Ollama's HTTP API (https://github.com/ollama/ollama/blob/main/docs/api.md).

Nothing here leaves the computer: the address is configured (``ORION_AI_LOCAL_URL``) and defaults to localhost. Ollama is
not assumed to be installed, running or to have a model; ``health`` says which of those is missing and what to do.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any, Iterator

import httpx

from app.ai import config
from app.ai.providers.base import AIProvider, Capabilities, Health, ProviderError, ProviderTurn, ToolCall, Usage

log = logging.getLogger(__name__)

# Models that are known to take tools when Ollama does not say (older Ollama versions do not report capabilities).
_TOOL_FAMILIES = ("llama3.1", "llama3.2", "llama3.3", "qwen2.5", "qwen3", "mistral", "mixtral", "command-r", "firefunction", "hermes", "granite3", "smollm2", "gpt-oss")
_NOT_CHAT = ("embed", "minilm", "bge-", "rerank")

_slots_lock = threading.Lock()
_slots: threading.BoundedSemaphore | None = None
_slots_size = 0


def _gate() -> threading.BoundedSemaphore:
    """At most ``ORION_AI_LOCAL_CONCURRENCY`` answers are written at once; a small machine does one."""
    global _slots, _slots_size
    wanted = config.local_concurrency()
    with _slots_lock:
        if _slots is None or _slots_size != wanted:
            _slots, _slots_size = threading.BoundedSemaphore(wanted), wanted
        return _slots


class LocalProvider(AIProvider):
    name = "ollama"
    location = "local"

    def __init__(self, base_url: str | None = None, model: str | None = None) -> None:
        self._url = (base_url or config.local_url()).rstrip("/")
        self._configured_model = model if model is not None else config.local_model()
        self._resolved = ""
        self._capabilities: dict[str, tuple[float, Capabilities]] = {}

    # ----------------------------------------------------------------------------------------------- the machine

    def _client(self, timeout: float | None = None) -> httpx.Client:
        return httpx.Client(base_url=self._url, timeout=httpx.Timeout(timeout or config.local_timeout(), connect=3.0))

    def installed(self) -> list[str]:
        """The names of the models Ollama has, or raises ProviderError(kind="unavailable")."""
        try:
            with self._client(5.0) as client:
                response = client.get("/api/tags")
                response.raise_for_status()
                return [m["name"] for m in response.json().get("models", []) if not any(bad in m["name"].lower() for bad in _NOT_CHAT)]
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            raise ProviderError(f"Ollama is not reachable at {self._url}: {exc}", retryable=True, kind="unavailable") from exc
        except httpx.TimeoutException as exc:
            raise ProviderError(f"Ollama did not answer in time: {exc}", retryable=True, kind="timeout") from exc
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            raise ProviderError(f"Ollama gave an unexpected answer: {exc}", kind="other") from exc

    def resolve_model(self, installed: list[str] | None = None) -> str:
        """The model to use: the configured one if it is installed, else (when none is configured) the first installed."""
        names = installed if installed is not None else self.installed()
        wanted = self._configured_model
        if wanted:
            for name in names:
                if name == wanted or name == f"{wanted}:latest" or name.split(":")[0] == wanted:
                    return name
            raise ProviderError(f"The model {wanted!r} is not installed (installed: {', '.join(names) or 'none'})", kind="model_missing")
        if not names:
            raise ProviderError("No model is installed in Ollama", kind="model_missing")
        return names[0]

    @property
    def model(self) -> str:
        return self._resolved or self._configured_model

    def health(self) -> Health:
        started = time.monotonic()
        try:
            names = self.installed()
        except ProviderError as exc:
            return Health("unreachable" if exc.kind in ("unavailable", "timeout") else "error", exc.technical, self._configured_model)
        took = int((time.monotonic() - started) * 1000)
        try:
            chosen = self.resolve_model(names)
        except ProviderError as exc:
            return Health("no_model" if not self._configured_model else "model_missing", exc.technical, self._configured_model, names, took)
        self._resolved = chosen
        return Health("ok", "", chosen, names, took)

    def capabilities(self) -> Capabilities:
        model = self._resolved or self._configured_model
        if not model:
            return Capabilities(tools=False, context_tokens=config.local_context(), max_output_tokens=config.MAX_OUTPUT_TOKENS)
        cached = self._capabilities.get(model)
        if cached and time.monotonic() - cached[0] < 300:
            return cached[1]
        tools = model.lower().startswith(_TOOL_FAMILIES)
        window = config.local_context()
        try:
            with self._client(5.0) as client:
                shown = client.post("/api/show", json={"model": model}).json()
            reported = shown.get("capabilities")
            if isinstance(reported, list):
                tools = "tools" in reported
            for key, value in (shown.get("model_info") or {}).items():
                if key.endswith(".context_length") and isinstance(value, int):
                    window = min(window, value)
        except (httpx.HTTPError, ValueError):
            pass  # not reachable now: the guess from the name stands, and the next call will say what is wrong
        setting = config.local_tools_setting()
        found = Capabilities(tools=(setting == "on") or (setting == "auto" and tools), streaming=True, structured_output=True, context_tokens=window, max_output_tokens=config.MAX_OUTPUT_TOKENS)
        self._capabilities[model] = (time.monotonic(), found)
        return found

    # --------------------------------------------------------------------------------------------- translating

    @staticmethod
    def _messages(system: str, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = [{"role": "system", "content": system}]
        names: dict[str, str] = {}
        for message in messages:
            content = message["content"]
            if isinstance(content, str):
                out.append({"role": message["role"], "content": content})
                continue
            if message["role"] == "assistant":
                text = "".join(block.get("text", "") for block in content if block.get("type") == "text")
                calls = []
                for block in content:
                    if block.get("type") == "tool_use":
                        names[block["id"]] = block["name"]
                        calls.append({"function": {"name": block["name"], "arguments": block.get("input") or {}}})
                entry: dict[str, Any] = {"role": "assistant", "content": text}
                if calls:
                    entry["tool_calls"] = calls
                out.append(entry)
            else:
                for block in content:
                    if block.get("type") == "tool_result":
                        out.append({"role": "tool", "tool_name": names.get(block.get("tool_use_id", ""), ""), "content": str(block.get("content", ""))})
                    elif block.get("type") == "text":
                        out.append({"role": "user", "content": block.get("text", "")})
        return out

    @staticmethod
    def _tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [{"type": "function", "function": {"name": t["name"], "description": t.get("description", ""), "parameters": t["input_schema"]}} for t in tools]

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
        body: dict[str, Any] = {
            "model": model or self.model,
            "messages": self._messages(system, messages),
            "stream": True,
            "options": {"num_ctx": config.local_context(), "num_predict": max_tokens, "temperature": 0.2},
        }
        if tools and allow_tools:
            body["tools"] = self._tools(tools)
        slot = _gate()
        if not slot.acquire(timeout=min(30.0, config.local_timeout())):
            raise ProviderError("The local model is busy with another answer", retryable=True, kind="busy")
        text, calls, usage, reason = "", [], Usage(), "end"
        try:
            with self._client() as client, client.stream("POST", "/api/chat", json=body) as response:
                if response.status_code == 404:
                    response.read()
                    raise ProviderError(f"Ollama does not have the model {body['model']!r}", kind="model_missing")
                if response.status_code >= 400:
                    detail = response.read().decode("utf-8", "replace")[:300]
                    raise ProviderError(f"Ollama returned {response.status_code}: {detail}", retryable=response.status_code >= 500)
                for line in response.iter_lines():
                    if not line:
                        continue
                    try:
                        chunk = json.loads(line)
                    except ValueError:
                        continue
                    if chunk.get("error"):
                        raise ProviderError(f"Ollama error: {chunk['error']}")
                    message = chunk.get("message") or {}
                    if message.get("content"):
                        text += message["content"]
                        yield "text", message["content"]
                    for call in message.get("tool_calls") or []:
                        function = call.get("function") or {}
                        arguments = function.get("arguments") or {}
                        if isinstance(arguments, str):
                            try:
                                arguments = json.loads(arguments)
                            except ValueError:
                                arguments = {}
                        calls.append(ToolCall(id=f"call_{len(calls) + 1}", name=str(function.get("name", "")), input=arguments if isinstance(arguments, dict) else {}))
                    if chunk.get("done"):
                        usage = Usage(int(chunk.get("prompt_eval_count") or 0), int(chunk.get("eval_count") or 0))
                        reason = str(chunk.get("done_reason") or "end")
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            raise ProviderError(f"Ollama is not reachable at {self._url}: {exc}", retryable=True, kind="unavailable") from exc
        except httpx.TimeoutException as exc:
            raise ProviderError(f"Ollama did not finish in {config.local_timeout():.0f}s: {exc}", retryable=True, kind="timeout") from exc
        except httpx.HTTPError as exc:
            raise ProviderError(f"Ollama connection failed: {exc}", retryable=True, kind="unavailable") from exc
        finally:
            slot.release()
        yield "turn", ProviderTurn(text=text, tool_calls=calls, stop_reason="tool_use" if calls else ("length" if reason == "length" else "end"), usage=usage)

    def structured(self, *, model: str, system: str, prompt: str, schema: dict[str, Any], max_tokens: int = 600) -> tuple[Any, ProviderTurn]:
        """Ollama can constrain its output to a JSON schema, which is far more reliable on a small model than asking nicely."""
        from app.ai.providers.base import parse_json
        from app.ai.tools.core import ToolInputError, validate

        body = {
            "model": model or self.model, "stream": False, "format": schema,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            "options": {"num_ctx": config.local_context(), "num_predict": max_tokens, "temperature": 0},
        }
        slot = _gate()
        if not slot.acquire(timeout=min(30.0, config.local_timeout())):
            raise ProviderError("The local model is busy with another answer", retryable=True, kind="busy")
        try:
            with self._client() as client:
                response = client.post("/api/chat", json=body)
            response.raise_for_status()
            data = response.json()
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            raise ProviderError(f"Ollama is not reachable: {exc}", retryable=True, kind="unavailable") from exc
        except httpx.TimeoutException as exc:
            raise ProviderError(f"Ollama did not answer in time: {exc}", retryable=True, kind="timeout") from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise ProviderError(f"Ollama call failed: {exc}") from exc
        finally:
            slot.release()
        text = str((data.get("message") or {}).get("content", ""))
        turn = ProviderTurn(text=text, usage=Usage(int(data.get("prompt_eval_count") or 0), int(data.get("eval_count") or 0)))
        value = parse_json(text)
        if value is None:
            raise ProviderError("The model did not return JSON", kind="invalid")
        try:
            return validate(schema, value), turn
        except ToolInputError as exc:
            raise ProviderError(f"The model's JSON did not fit the schema: {exc}", kind="invalid") from exc
