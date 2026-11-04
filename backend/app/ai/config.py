"""Settings for the AI Copilot, all in one place.

Nothing else in the application names a model, a limit or a key. Secrets stay in the server's environment (``.env``);
the browser never sees them and the API never sends them anywhere but to the provider they belong to.

The assistant answers in three ways, cheapest first: the application itself (rules and its own calculations, no model),
a model running on this machine (Ollama), and, only when permitted, a cloud model (Anthropic or OpenAI). It works with
none of the model settings below.

    ORION_AI_ENABLED             1 (default) or 0: switch the assistant off for everyone.
    ORION_AI_ROUTING_MODE        local_first (default) or local_only (cloud models are never used, whatever else is set)

  The local model (nothing leaves this machine)
    ORION_AI_LOCAL_PROVIDER      ollama (default), none, or scripted (tests and demos only; refused in production)
    ORION_AI_LOCAL_URL           where Ollama listens (default http://127.0.0.1:11434)
    ORION_AI_LOCAL_MODEL         the model to use, e.g. qwen2.5:3b-instruct. Empty: the first installed one
    ORION_AI_LOCAL_CONTEXT       the context window to ask Ollama for, in tokens (default 8192)
    ORION_AI_LOCAL_TIMEOUT       seconds to wait for it (default 180: a CPU is slow)
    ORION_AI_LOCAL_CONCURRENCY   answers written at once (default 1)
    ORION_AI_LOCAL_RETRIES       extra local attempts after an answer fails its checks (default 1)
    ORION_AI_LOCAL_TOOLS         auto (default: ask the model), on or off

  Cloud models (off unless switched on here AND permitted by the organisation's policy AND the person)
    ORION_AI_CLOUD_ESCALATION    0 (default) or 1
    ORION_AI_CLOUD_PROVIDER      none (default), anthropic or openai
    ANTHROPIC_API_KEY, OPENAI_API_KEY   server side only, never sent to a browser
    ORION_AI_ANTHROPIC_MODEL, ORION_AI_OPENAI_MODEL   the cloud models (OpenAI has no default: name one)
    ORION_AI_CLOUD_TIMEOUT, ORION_AI_CLOUD_RETRIES    seconds to wait, and extra tries after a timeout
    ORION_AI_CLOUD_MONTHLY_BUDGET_USD    spend ceiling per calendar month (default 0: no cloud spending at all)
    ORION_AI_CLOUD_USER_DAILY    cloud answers one person can have a day (default 20)
    ORION_AI_CLOUD_RPM           cloud requests a minute, all people together (default 20)
    ORION_AI_CLOUD_PRICE_IN, ORION_AI_CLOUD_PRICE_OUT   US dollars per million tokens, for cost estimates
    ORION_AI_CLOUD_EST_PER_REQUEST_USD   what one cloud answer is assumed to cost when prices are not given (default 0.05)

  Limits per person
    ORION_AI_RATE_PER_MINUTE     requests one person can make a minute
    ORION_AI_DAILY_REQUESTS      requests one person can make a day
    ORION_AI_DAILY_OUTPUT_TOKENS output tokens one person can use a day
"""

from __future__ import annotations

from app.config import env

TIERS = ("fast", "standard", "strong")

# The Anthropic models behind each tier (used when Anthropic is the cloud provider). Change them here or in the environment.
DEFAULT_MODELS = {
    "fast": "claude-haiku-5-5",
    "standard": "claude-sonnet-5-5",
    "strong": "claude-opus-5-5",
}

MAX_MESSAGE_CHARS = 4000
MAX_TOOL_STEPS = 8
MAX_OUTPUT_TOKENS = 2400
# How many recent messages are sent to the model word for word; anything older is summarised.
RECENT_MESSAGES = 12
SUMMARISE_AFTER_MESSAGES = 24
PENDING_ACTION_MINUTES = 20
FILE_LIFETIME_HOURS = 48

PROVIDER_LABELS = {"openai": "OpenAI", "anthropic": "Anthropic", "ollama": "Ollama", "scripted": "Test"}
ROUTING_MODES = ("local_first", "local_only")
CLOUD_PROVIDERS = ("none", "anthropic", "openai")
LOCAL_PROVIDERS = ("ollama", "none", "scripted")
# What the organisation's policy may say about cloud models, strictest first (see routing/policy.py).
CLOUD_POLICIES = ("local_only", "no_app_data", "local_first", "cloud_eligible")
DEFAULT_CLOUD_POLICY = "local_only"

# The most that is ever put into one cloud request, in characters, however much was gathered.
CLOUD_MAX_CONTEXT_CHARS = 24_000


def _int(name: str, default: int, minimum: int = 1) -> int:
    try:
        return max(minimum, int(env(name, str(default))))
    except ValueError:
        return default


def _float(name: str, default: float) -> float:
    try:
        return max(0.0, float(env(name, str(default))))
    except ValueError:
        return default


def _choice(name: str, default: str, allowed: tuple[str, ...]) -> str:
    value = env(name, default).strip().lower() or default
    return value if value in allowed else default


def model_for(tier: str) -> str:
    """An Anthropic model for a tier."""
    tier = tier if tier in TIERS else "standard"
    return env(f"ORION_AI_MODEL_{tier.upper()}").strip() or DEFAULT_MODELS[tier]


def is_production() -> bool:
    return env("ORION_ENV").strip().lower() == "production"


def switched_on() -> bool:
    return env("ORION_AI_ENABLED", "1").strip().lower() not in ("0", "false", "no", "off")


def available() -> bool:
    """The assistant answers at all. The application's own answers need no model, so no model setting is required."""
    return switched_on()


def configured() -> bool:
    return available()


def routing_mode() -> str:
    return _choice("ORION_AI_ROUTING_MODE", "local_first", ROUTING_MODES)


# ----------------------------------------------------------------------------------------------------- local model


def local_provider_name() -> str:
    name = _choice("ORION_AI_LOCAL_PROVIDER", "ollama", LOCAL_PROVIDERS)
    return "none" if name == "scripted" and is_production() else name


def local_url() -> str:
    return env("ORION_AI_LOCAL_URL", "http://127.0.0.1:11434").strip().rstrip("/")


def local_model() -> str:
    return env("ORION_AI_LOCAL_MODEL").strip()


def local_context() -> int:
    return _int("ORION_AI_LOCAL_CONTEXT", 8192, 1024)


def local_timeout() -> float:
    return float(_int("ORION_AI_LOCAL_TIMEOUT", 180, 5))


def local_concurrency() -> int:
    return _int("ORION_AI_LOCAL_CONCURRENCY", 1)


def local_retries() -> int:
    return _int("ORION_AI_LOCAL_RETRIES", 1, 0)


def local_tools_setting() -> str:
    return _choice("ORION_AI_LOCAL_TOOLS", "auto", ("auto", "on", "off"))


# ---------------------------------------------------------------------------------------------------- cloud models


def cloud_provider_name() -> str:
    return _choice("ORION_AI_CLOUD_PROVIDER", "none", CLOUD_PROVIDERS)


def api_key(provider: str | None = None) -> str:
    """A cloud provider's key. It is read here, on the server, and goes nowhere but to that provider."""
    name = provider or cloud_provider_name()
    variable = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY"}.get(name)
    return env(variable).strip() if variable else ""


def cloud_model(provider: str | None = None) -> str:
    name = provider or cloud_provider_name()
    if name == "anthropic":
        return env("ORION_AI_ANTHROPIC_MODEL").strip() or model_for("standard")
    if name == "openai":
        return env("ORION_AI_OPENAI_MODEL").strip()
    return ""


def cloud_switched_on() -> bool:
    """The environment allows cloud models at all. The organisation's policy and the person's choice are further checks."""
    return (
        routing_mode() != "local_only"
        and env("ORION_AI_CLOUD_ESCALATION", "0").strip().lower() in ("1", "true", "yes", "on")
        and cloud_provider_name() != "none"
    )


def cloud_ready() -> bool:
    """A cloud model could be called: switched on, with a key and a model."""
    return cloud_switched_on() and bool(api_key()) and bool(cloud_model())


def cloud_timeout() -> float:
    return float(_int("ORION_AI_CLOUD_TIMEOUT", 60, 5))


def cloud_retries() -> int:
    return _int("ORION_AI_CLOUD_RETRIES", 1, 0)


def cloud_monthly_budget() -> float:
    return _float("ORION_AI_CLOUD_MONTHLY_BUDGET_USD", 0.0)


def cloud_user_daily() -> int:
    return _int("ORION_AI_CLOUD_USER_DAILY", 20, 0)


def cloud_rpm() -> int:
    return _int("ORION_AI_CLOUD_RPM", 20)


def cloud_prices() -> tuple[float, float]:
    """US dollars per million input and output tokens, as the operator entered them (0 when not given)."""
    return _float("ORION_AI_CLOUD_PRICE_IN", 0.0), _float("ORION_AI_CLOUD_PRICE_OUT", 0.0)


def cloud_flat_estimate() -> float:
    return _float("ORION_AI_CLOUD_EST_PER_REQUEST_USD", 0.05)


# After this many failures in a row a provider is left alone for a while, so a dead one does not slow every answer.
def breaker_failures() -> int:
    return _int("ORION_AI_BREAKER_FAILURES", 3)


def breaker_seconds() -> int:
    return _int("ORION_AI_BREAKER_SECONDS", 60, 5)


# ------------------------------------------------------------------------------------------------ per-person limits


def rate_per_minute() -> int:
    return _int("ORION_AI_RATE_PER_MINUTE", 10)


def daily_requests() -> int:
    return _int("ORION_AI_DAILY_REQUESTS", 200)


def daily_output_tokens() -> int:
    return _int("ORION_AI_DAILY_OUTPUT_TOKENS", 200_000)
