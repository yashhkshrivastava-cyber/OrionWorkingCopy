"""Slow down guessing at the sign-in, password-reset and registration doors.

Nothing limited how often a password could be tried: a script could try thousands a minute against ``/api/auth/login``. Here
every attempt is a row of ``orion_ods.auth_attempt``, and an attempt is refused (HTTP 429, with how long to wait) when the
recent history already says too many. It is kept in the database, not in memory, so a restart does not give an attacker a clean
slate, and so there is a record of who failed to sign in, from where and when.

Sign-in failures are counted three ways, because each blocks a different attack:

* the same name from the same address (``pair``): someone guessing one person's password. A person who mistypes sits it out for
  a few minutes; nobody else is affected, and a correct sign-in clears the count.
* one name from anywhere (``username``): guessing spread across many addresses. The ceiling is high enough that the real
  person is not locked out by a few typos, and it ends by itself.
* one address with any names (``ip``): trying many accounts. Skipped when the address is the machine itself, which is what
  every request looks like behind a local proxy: there it would lock out the whole company on the strength of one person.

While blocked, an attempt is refused before the password is even checked and is not counted again, so a block cannot be
stretched forever by hammering it, and the block cannot be used to test passwords.

The rules below are the whole policy; ``retry_after`` is the arithmetic and needs no database.
"""

import logging
import math
import random
from dataclasses import dataclass
from typing import Optional

from app.database import db_cursor

logger = logging.getLogger(__name__)

ATTEMPT_TABLE = "orion_ods.auth_attempt"
KEEP_DAYS = 30
UNKNOWN_IP = "unknown"
# Addresses that say nothing about who is asking: the proxy, or this PC itself.
LOCAL_ADDRESSES = {"127.0.0.1", "::1", "localhost", UNKNOWN_IP}


@dataclass(frozen=True)
class Rule:
    scope: str  # pair | username | ip | global (everyone together: the ceiling when no one can be told apart)
    limit: int  # this many counted attempts inside the window blocks the next
    window_seconds: int
    failures_only: bool = True  # False counts every attempt (asking for a reset email is the abuse, not failing at it)
    cleared_by_success: bool = False  # a correct attempt by the same pair wipes the count


FIFTEEN_MINUTES = 15 * 60
HOUR = 60 * 60

RULES: dict[str, tuple[Rule, ...]] = {
    "login": (
        Rule("pair", 5, FIFTEEN_MINUTES, cleared_by_success=True),
        Rule("username", 15, FIFTEEN_MINUTES),
        Rule("ip", 30, FIFTEEN_MINUTES),
    ),
    # Anyone can ask for a reset email or request an account without signing in, so these cannot be failures-only.
    "forgot": (
        Rule("username", 3, HOUR, failures_only=False),
        Rule("ip", 8, HOUR, failures_only=False),
        Rule("global", 40, HOUR, failures_only=False),
    ),
    "register": (Rule("ip", 5, HOUR, failures_only=False), Rule("global", 30, HOUR, failures_only=False)),
    # A reset link's token is the secret being guessed: failures are what count.
    "reset": (Rule("ip", 10, FIFTEEN_MINUTES),),
}

MESSAGES = {
    "login": "Too many failed sign-in attempts.",
    "forgot": "Too many password reset requests.",
    "register": "Too many account requests.",
    "reset": "Too many attempts with an invalid reset link.",
}


class TooManyAttempts(Exception):
    def __init__(self, kind: str, retry_after: int):
        self.kind = kind
        self.retry_after = max(1, int(retry_after))
        minutes = math.ceil(self.retry_after / 60)
        self.message = f"{MESSAGES.get(kind, 'Too many attempts.')} Try again in {minutes} minute{'s' if minutes != 1 else ''}."
        super().__init__(self.message)


# ---------------------------------------------------------------------------------------------------------- the arithmetic


def retry_after(times: list[float], rule: Rule, now: float) -> int:
    """Seconds until one more attempt is allowed under ``rule`` (0 when it is allowed now).

    ``times`` are the counted attempts, as seconds since the epoch. Only those inside the window count. Blocked means the
    count has reached the limit; the block lifts when enough of the oldest have aged out to bring it back under.
    """
    recent = sorted(t for t in times if t > now - rule.window_seconds)
    if len(recent) < rule.limit:
        return 0
    frees_up_at = recent[len(recent) - rule.limit] + rule.window_seconds
    return max(1, math.ceil(frees_up_at - now))


def normalise_username(username: Optional[str]) -> Optional[str]:
    text = (username or "").strip().lower()[:100]
    return text or None


def normalise_ip(ip: Optional[str]) -> str:
    return (ip or "").strip()[:64] or UNKNOWN_IP


def applies(rule: Rule, username: Optional[str], ip: str) -> bool:
    """Whether a rule can be judged for this attempt (an address rule needs a real address, a name rule needs a name)."""
    if rule.scope == "global":
        return True
    if rule.scope == "username":
        return username is not None
    if rule.scope == "pair":
        return username is not None and ip != UNKNOWN_IP
    return ip not in LOCAL_ADDRESSES


# --------------------------------------------------------------------------------------------------------------- the history


def _times(cur, kind: str, rule: Rule, username: Optional[str], ip: str) -> list[float]:
    where = ["kind = %s", "attempted_timestamp > CURRENT_TIMESTAMP - make_interval(secs => %s)"]
    params: list = [kind, rule.window_seconds]
    if rule.failures_only:
        where.append("succeeded = FALSE")
    if rule.scope in ("pair", "username"):
        where.append("username = %s")
        params.append(username)
    if rule.scope in ("pair", "ip"):
        where.append("ip = %s")
        params.append(ip)
    if rule.cleared_by_success:
        where.append(
            f"attempted_timestamp > COALESCE((SELECT MAX(attempted_timestamp) FROM {ATTEMPT_TABLE} "
            f"WHERE kind = %s AND succeeded AND username = %s AND ip = %s), '-infinity')"
        )
        params += [kind, username, ip]
    cur.execute(
        f"SELECT EXTRACT(EPOCH FROM attempted_timestamp) FROM {ATTEMPT_TABLE} WHERE {' AND '.join(where)} "
        f"ORDER BY attempted_timestamp LIMIT 1000",
        params,
    )
    return [float(row[0]) for row in cur.fetchall()]


def check(kind: str, username: Optional[str], ip: Optional[str]) -> None:
    """Raise TooManyAttempts when this kind of attempt, by this name and address, is currently blocked."""
    name, address = normalise_username(username), normalise_ip(ip)
    waits = []
    with db_cursor() as cur:
        cur.execute("SELECT EXTRACT(EPOCH FROM CURRENT_TIMESTAMP)")
        now = float(cur.fetchone()[0])
        for rule in RULES[kind]:
            if applies(rule, name, address):
                wait = retry_after(_times(cur, kind, rule, name, address), rule, now)
                if wait:
                    waits.append((wait, rule.scope))
    if waits:
        wait, scope = max(waits)
        logger.warning("Blocked %s attempt (%s limit): name=%s address=%s, wait %ss", kind, scope, name, address, wait)
        raise TooManyAttempts(kind, wait)


def record(kind: str, username: Optional[str], ip: Optional[str], succeeded: bool) -> None:
    """Remember an attempt. Call it only for attempts that were allowed to happen (not for ones ``check`` refused)."""
    with db_cursor(commit=True) as cur:
        cur.execute(
            f"INSERT INTO {ATTEMPT_TABLE} (kind, username, ip, succeeded) VALUES (%s, %s, %s, %s)",
            (kind, normalise_username(username), normalise_ip(ip), succeeded),
        )
        if random.random() < 0.02:  # now and then: a month of history is plenty, and this keeps the table small
            cur.execute(f"DELETE FROM {ATTEMPT_TABLE} WHERE attempted_timestamp < CURRENT_TIMESTAMP - make_interval(days => %s)", (KEEP_DAYS,))


def client_address(request) -> str:
    """The address a request came from. Behind a proxy on this PC uvicorn already swapped in the forwarded address."""
    return request.client.host if getattr(request, "client", None) and request.client else UNKNOWN_IP
