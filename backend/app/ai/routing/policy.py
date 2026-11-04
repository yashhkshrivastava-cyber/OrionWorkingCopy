"""Whether a request may leave this machine. Every rule is checked and reported, so the decision can be explained.

The default is no. A request reaches a cloud model only when all of these hold:

  * cloud models are switched on in the environment and have a key and a model;
  * the organisation's policy allows it for this kind of request (see ``MODES``);
  * the person has allowed it (a standing choice in their settings, or "use cloud AI" for this one question);
  * the request is not sensitive (credentials, ID or bank numbers, pay);
  * the spending budget, the person's daily cloud allowance and the provider's rate limit have room;
  * the cloud provider is not currently failing.

This module is pure: it is handed the facts and returns the decision, which is what makes it testable.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# The organisation's choices, strictest first.
MODES = {
    "local_only": "Local only: nothing is ever sent to a cloud model.",
    "no_app_data": "Never send application data to cloud models: a cloud model may be used only for questions that need none of your data.",
    "local_first": "Local first, with approved cloud fallback: the local model answers first; a cloud model may be tried when it cannot, with minimised data.",
    "cloud_eligible": "Cloud allowed for eligible tasks: a cloud model may also be chosen directly for heavy analysis, with minimised data.",
}


@dataclass
class Check:
    name: str
    ok: bool
    note: str


@dataclass
class CloudDecision:
    allowed: bool
    #: what may be sent: "question_only" (the person's words and nothing from the application) or "minimised" (plus retrieved figures, names replaced)
    payload: str = "none"
    blocked_by: str | None = None
    checks: list[Check] = field(default_factory=list)

    def explain(self) -> list[dict[str, object]]:
        return [{"check": c.name, "ok": c.ok, "note": c.note} for c in self.checks]


def decide(
    *,
    mode: str,
    switched_on: bool,
    ready: bool,
    user_allows: bool,
    consent_once: bool,
    sensitive: bool,
    needs_data: bool,
    reason: str,
    spend_month: float,
    budget_month: float,
    estimate: float,
    user_answers_today: int,
    user_daily_limit: int,
    breaker_open: bool,
    rate_ok: bool,
) -> CloudDecision:
    """``reason`` says why the local model is not enough:

    * ``failed``: it answered, and the answer did not pass its checks (after bounded retries);
    * ``incapable``: it is running but cannot do this (no tool use, or the request is too large for it);
    * ``unavailable``: it is not running. The person's say-so for this one question is then required, however the standing
      setting is, so a stopped local model never quietly turns into cloud traffic.
    """
    checks: list[Check] = []

    def check(name: str, ok: bool, note: str) -> None:
        checks.append(Check(name, ok, note))

    check("environment", switched_on and ready, "cloud models are switched on and configured" if switched_on and ready else "cloud models are not switched on or not configured")
    check("policy", mode != "local_only", MODES.get(mode, MODES["local_only"]))
    if mode == "no_app_data" and needs_data:
        check("policy_data", False, "the policy forbids sending application data, and this question needs it")
    else:
        check("policy_data", True, "the policy allows this kind of request")
    check("sensitivity", not sensitive, "the request is not sensitive" if not sensitive else "the request holds private or restricted information, which stays on this machine")
    consent = user_allows or consent_once
    check("person", consent, "the person has allowed cloud AI" if consent else "the person has not allowed cloud AI")
    if reason == "unavailable":
        check("consent", consent_once, "the person chose cloud AI for this question" if consent_once else "the local model is not running, so cloud AI is used only if the person chooses it for this question")
    within = budget_month > 0 and spend_month + estimate <= budget_month
    check("budget", within, "within the monthly budget" if within else ("no cloud budget is set" if budget_month <= 0 else "the monthly cloud budget would be exceeded"))
    check("daily_limit", user_answers_today < user_daily_limit, "within the person's daily cloud allowance" if user_answers_today < user_daily_limit else "the person's daily cloud allowance is used up")
    check("provider", not breaker_open, "the cloud provider is responding" if not breaker_open else "the cloud provider has been failing and is being left alone for a moment")
    check("rate", rate_ok, "within the cloud request rate" if rate_ok else "the cloud request rate limit is reached")
    failed = next((c for c in checks if not c.ok), None)
    if failed:
        return CloudDecision(False, "none", failed.name, checks)
    return CloudDecision(True, "minimised" if needs_data else "question_only", None, checks)
