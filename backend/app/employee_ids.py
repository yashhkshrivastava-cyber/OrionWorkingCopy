"""Checks for the identity numbers kept on an employee: Aadhaar, PAN and the decided monthly salary.

They are used as field rules by the Employee entity (``entities.ENTITIES``), so the data form, the Excel
upload and any other way of saving an employee are held to the same rules. Each rule takes what was entered
and returns the value to store, or raises ``PayloadError`` with a message that is safe to show.
"""

from __future__ import annotations

import math
import re
from typing import Any

from app.payload import PayloadError

# Verhoeff check digit, the one Aadhaar uses: the multiplication, permutation and inverse tables.
_D = (
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9), (1, 2, 3, 4, 0, 6, 7, 8, 9, 5), (2, 3, 4, 0, 1, 7, 8, 9, 5, 6),
    (3, 4, 0, 1, 2, 8, 9, 5, 6, 7), (4, 0, 1, 2, 3, 9, 5, 6, 7, 8), (5, 9, 8, 7, 6, 0, 4, 3, 2, 1),
    (6, 5, 9, 8, 7, 1, 0, 4, 3, 2), (7, 6, 5, 9, 8, 2, 1, 0, 4, 3), (8, 7, 6, 5, 9, 3, 2, 1, 0, 4),
    (9, 8, 7, 6, 5, 4, 3, 2, 1, 0),
)
_P = (
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9), (1, 5, 7, 6, 2, 8, 3, 0, 9, 4), (5, 8, 0, 3, 7, 9, 6, 1, 4, 2),
    (8, 9, 1, 6, 0, 4, 3, 5, 2, 7), (9, 4, 5, 3, 1, 2, 6, 8, 7, 0), (4, 2, 8, 6, 5, 7, 3, 9, 0, 1),
    (2, 7, 9, 3, 8, 0, 6, 4, 1, 5), (7, 0, 4, 6, 9, 1, 3, 2, 5, 8),
)

PAN = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")
MAX_SALARY = 10_000_000


def verhoeff_valid(digits: str) -> bool:
    """Whether a string of digits ends in a correct Verhoeff check digit."""
    check = 0
    for index, char in enumerate(reversed(digits)):
        check = _D[check][_P[index % 8][int(char)]]
    return check == 0


def clean_aadhaar(value: Any) -> str:
    """A 12 digit Aadhaar number, stored as digits only. Spaces and dashes typed between groups are dropped."""
    digits = re.sub(r"[\s-]", "", str(value))
    if not digits.isdigit() or len(digits) != 12:
        raise PayloadError("Aadhaar Number must be 12 digits.")
    if digits[0] in "01":
        raise PayloadError("Aadhaar Number cannot start with 0 or 1.")
    if not verhoeff_valid(digits):
        raise PayloadError("Aadhaar Number is not valid. Check the digits against the card.")
    return digits


def clean_pan(value: Any) -> str:
    """A PAN as five letters, four digits and a letter, in capitals."""
    pan = re.sub(r"\s", "", str(value)).upper()
    if not PAN.match(pan):
        raise PayloadError("PAN No must be five letters, four digits and a letter, for example ABCDE1234F.")
    return pan


def clean_salary(value: Any) -> float:
    salary = float(value)
    # NaN fails every comparison, so it has to be refused by name or it would slip through the range check.
    if not math.isfinite(salary) or salary < 0 or salary > MAX_SALARY:
        raise PayloadError("Monthly Salary must be between 0 and 1,00,00,000.")
    return round(salary, 2)

