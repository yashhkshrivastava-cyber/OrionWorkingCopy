"""Doing a thing once, however many times the request arrives.

A tax invoice has a legal number that is never reused, and a payment is money. Nothing used to stop the same request arriving
twice (a double-click, a retry after a dropped connection, a stale tab): the second one made a second invoice with its own
number, or recorded a repeated partial payment twice.

How it works:

* The browser makes a random **key** when a form opens and sends it as ``Idempotency-Key`` with the save. The same form always
  sends the same key; a new form, or the same form after it succeeded, has a new one.
* The server **claims the key in the same database transaction** as the work (``claim`` then ``remember`` then commit). So the
  key and the work are saved together or not at all: a failed save leaves the key free for the retry, and a saved one can never
  be saved again.
* Two identical requests at the same instant are serialised by the database (the second INSERT waits for the first to finish):
  exactly one does the work, and the other is answered with the first one's result, marked ``Idempotent-Replayed: true``.
* The same key with something different (another amount, another bill) is refused (409), not mistaken for a repeat.
* A key lasts ``KEEP_DAYS`` days, then is forgotten.

``ORION_IDEMPOTENCY_REQUIRED=1`` makes the money endpoints refuse a request that carries no key (for when no stale tab or
other client can still be sending one without). The default is to accept it, unprotected, and say so in the log.
"""

import hashlib
import json
import logging
import os
import random
import re
from typing import Any, Optional

logger = logging.getLogger(__name__)

TABLE = "orion_ods.idempotency_key"
KEEP_DAYS = 30
_KEY_OK = re.compile(r"^[A-Za-z0-9._:-]{8,100}$")


class IdempotencyError(ValueError):
    """The key is not usable (wrong shape, or required and missing)."""


class IdempotencyConflict(ValueError):
    """The key was already used for a different request."""


def required(environ=None) -> bool:
    return ((environ or os.environ).get("ORION_IDEMPOTENCY_REQUIRED") or "").strip().lower() in ("1", "true", "yes", "on")


def clean_key(raw: Optional[str]) -> Optional[str]:
    """The key as sent, or None when there is none. A key that is there but malformed is an error, never silently ignored."""
    text = (raw or "").strip()
    if not text:
        return None
    if not _KEY_OK.fullmatch(text):
        raise IdempotencyError("The request key is not valid.")
    return text


def fingerprint(operation: str, *parts: Any) -> str:
    """A hash of exactly what was asked: the same on every repeat, different for any change."""
    canonical = json.dumps([operation, *parts], sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


class Idempotency:
    """One submission's key. Pass it to the function that does the work, which calls ``claim`` first and ``remember`` last."""

    def __init__(self, user_id: int, key: str, operation: str, request_fingerprint: str):
        self.user_id, self.key, self.operation, self.fingerprint = user_id, key, operation, request_fingerprint
        self.replayed = False

    def claim(self, cur) -> Optional[dict]:
        """None when this is the first time (go ahead, then call ``remember``); the first one's result when it is a repeat.

        Must be called inside the transaction that does the work. If another request holds the same key and has not finished,
        this waits for it, then answers with its result (or, if it failed, goes ahead).
        """
        if random.random() < 0.01:  # a month of keys is plenty; this keeps the table small
            cur.execute(f"DELETE FROM {TABLE} WHERE created_timestamp < CURRENT_TIMESTAMP - make_interval(days => %s)", (KEEP_DAYS,))
        cur.execute(
            f"INSERT INTO {TABLE} (user_id, idem_key, operation, fingerprint) VALUES (%s, %s, %s, %s) "
            f"ON CONFLICT (user_id, idem_key) DO NOTHING RETURNING id",
            (self.user_id, self.key, self.operation, self.fingerprint),
        )
        if cur.fetchone():
            return None
        cur.execute(f"SELECT operation, fingerprint, result FROM {TABLE} WHERE user_id = %s AND idem_key = %s", (self.user_id, self.key))
        row = cur.fetchone()
        if row is None:  # removed between the two statements by the clean-up: treat as new
            return self.claim(cur)
        operation, request_fingerprint, result = row
        if operation != self.operation or request_fingerprint != self.fingerprint:
            raise IdempotencyConflict(
                "This form was already used to save something else. Check the list before saving again: your earlier save may have gone through."
            )
        if result is None:  # cannot happen (the claim and the result are committed together), but never guess
            raise IdempotencyConflict("An earlier save with this form is still being processed. Wait a moment and check the list.")
        self.replayed = True
        logger.info("Repeat of %s (key %s...) answered with the first result instead of doing it again", self.operation, self.key[:8])
        return result

    def remember(self, cur, result: dict) -> None:
        """What a repeat is answered with. Call it just before committing the work."""
        cur.execute(
            f"UPDATE {TABLE} SET result = %s::jsonb WHERE user_id = %s AND idem_key = %s",
            (json.dumps(result), self.user_id, self.key),
        )
