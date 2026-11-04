"""Choosing the providers. This is the only place that knows which ones exist.

There are two roles. The **local** provider runs on this machine and is where private questions are answered. The **cloud**
provider is optional and is reached only through the routing policy (``app.ai.routing``), never directly.
"""

from __future__ import annotations

from app.ai import config
from app.ai.providers.base import AIProvider, ProviderError

_overrides: dict[str, AIProvider | None] = {"local": None, "cloud": None}
_cache: dict[tuple, AIProvider] = {}


def set_provider(role: str, provider: AIProvider | None) -> None:
    """Replaces the provider for a role (tests do this). Pass None to go back to the configured one."""
    if role not in _overrides:
        raise ValueError(f"Unknown provider role {role!r}")
    _overrides[role] = provider
    _cache.clear()


def local_provider() -> AIProvider | None:
    """The model on this machine, or None when none is configured."""
    if _overrides["local"] is not None:
        return _overrides["local"]
    name = config.local_provider_name()
    if name == "none":
        return None
    key = ("local", name, config.local_url(), config.local_model())
    if key not in _cache:
        if name == "scripted":
            from app.ai.providers.scripted import ScriptedProvider

            _cache[key] = ScriptedProvider()
        else:
            from app.ai.providers.ollama_provider import LocalProvider

            _cache[key] = LocalProvider()
    return _cache[key]


def cloud_provider() -> AIProvider:
    """The configured cloud model. Raises ProviderError when cloud models are not switched on or not set up."""
    if _overrides["cloud"] is not None:
        return _overrides["cloud"]
    if not config.cloud_ready():
        raise ProviderError("No cloud model is switched on and configured", kind="unavailable")
    name = config.cloud_provider_name()
    key = ("cloud", name, config.cloud_model())
    if key not in _cache:
        if name == "anthropic":
            from app.ai.providers.anthropic_provider import AnthropicProvider

            _cache[key] = AnthropicProvider()
        elif name == "openai":
            from app.ai.providers.openai_provider import OpenAIProvider

            _cache[key] = OpenAIProvider()
        else:
            raise ProviderError(f"Unknown cloud provider {name!r}", kind="unavailable")
    return _cache[key]
