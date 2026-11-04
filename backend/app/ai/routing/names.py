"""The names of the clients and cases, so a question can be understood however it is typed ("is sunrise school paying?").

Names are read from the database on this machine, kept for a minute, and used only to recognise a name in the question. They go
nowhere else.
"""

from __future__ import annotations

import re
import time
from typing import Callable

from app.database import db_cursor

_cache: tuple[float, list[str]] = (0.0, [])
TTL_SECONDS = 60


def known_names() -> list[str]:
    """Every client and case name, longest first (so "Acme Group HQ" is found before "Acme")."""
    global _cache
    if time.monotonic() - _cache[0] < TTL_SECONDS and _cache[1]:
        return _cache[1]
    names: set[str] = set()
    try:
        with db_cursor() as cur:
            cur.execute("SELECT client_name FROM orion_ods.client WHERE client_name IS NOT NULL")
            names |= {row[0].strip() for row in cur.fetchall() if row[0]}
            cur.execute('SELECT case_name FROM orion_ods."case" WHERE case_name IS NOT NULL')
            names |= {row[0].strip() for row in cur.fetchall() if row[0]}
    except Exception:  # noqa: BLE001 - not knowing the names only makes the rules less forgiving
        return _cache[1]
    ordered = sorted((n for n in names if len(n) >= 3), key=len, reverse=True)
    _cache = (time.monotonic(), ordered)
    return ordered


def forget() -> None:
    global _cache
    _cache = (0.0, [])


def find_in(text: str, names: Callable[[], list[str]] | None = None) -> str | None:
    """The longest known name written in the text, in any case, as the database spells it."""
    for name in (names or known_names)():
        if re.search(rf"(?<!\w){re.escape(name)}(?!\w)", text, re.IGNORECASE):
            return name
    return None
