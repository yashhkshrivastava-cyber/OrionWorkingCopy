"""A GSTIN (the 15-character GST number of a supplier or a customer): its shape and its check digit.

The 15th character is a check digit worked out from the other 14 (a Luhn-style sum over base 36), so a mistyped number is caught
when it is entered instead of when the input tax credit is claimed.
"""

from __future__ import annotations

import re
from typing import Any

_SHAPE = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


class GstinError(ValueError):
    """The GSTIN cannot be right: said in words."""


def normalise(value: Any) -> str:
    """What was typed, without spaces or dashes, in capitals (empty if nothing was typed)."""
    return re.sub(r"[\s-]", "", str(value or "")).upper()


def check_digit(first_fourteen: str) -> str:
    """The 15th character of a GSTIN whose first 14 characters are given."""
    total, factor = 0, 2
    for character in reversed(first_fourteen):
        product = factor * _CHARS.index(character)
        total += product // 36 + product % 36
        factor = 1 if factor == 2 else 2
    return _CHARS[(36 - total % 36) % 36]


def clean(value: Any) -> str | None:
    """The GSTIN in its usual form, None when none was given. A number that is the wrong shape or whose check digit does not fit is refused."""
    text = normalise(value)
    if not text:
        return None
    if not _SHAPE.match(text):
        raise GstinError("A GSTIN is 15 characters: 2 digits (the state), 10 for the PAN, then a digit or letter, Z and a check character, for example 27AAPFU0939F1ZV.")
    if check_digit(text[:14]) != text[14]:
        raise GstinError("That GSTIN does not pass its check digit, so a character is mistyped. Check it against the supplier's invoice.")
    return text
