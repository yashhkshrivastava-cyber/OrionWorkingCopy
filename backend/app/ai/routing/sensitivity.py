"""Finding private information in what a person typed, and in what is about to be sent out.

This is deliberately blunt: it looks for the shapes of the identifiers a security-services company holds (Aadhaar, PAN,
bank and card numbers, IFSC and GST numbers, phone numbers, email addresses) and for talk of credentials and pay. When it
finds any, the request stays on this machine. It is not a promise that nothing else is private, and nothing here makes a
cloud transfer safe by hiding names: the policy (``policy.py``) is what decides whether data may leave at all.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Order matters: the longer, more specific shapes are taken out of the text before the shorter ones are looked for.
PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("aadhaar", re.compile(r"(?<!\d)\d{4}[ -]?\d{4}[ -]?\d{4}(?!\d)")),
    ("card", re.compile(r"(?<!\d)(?:\d[ -]?){13,16}(?!\d)")),
    ("pan", re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b")),
    ("gstin", re.compile(r"\b\d{2}[A-Z]{5}\d{4}[A-Z][A-Z\d]Z[A-Z\d]\b")),
    ("ifsc", re.compile(r"\b[A-Z]{4}0[A-Z0-9]{6}\b")),
    ("phone", re.compile(r"(?<!\d)(?:\+?91[ -]?)?[6-9]\d{4}[ -]?\d{5}(?!\d)")),
    ("email", re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")),
    ("account", re.compile(r"(?<!\d)\d{9,18}(?!\d)")),
]

# Talk of things that are never for a cloud model, whoever asks.
RESTRICTED = re.compile(
    r"\b(password|passcode|passphrase|otp|cvv|pin\s*code\s*of|api[ -]?key|secret|private key|token|credentials?|aadhaar|aadhar|pan\s*(?:number|card)|"
    r"bank\s*account|account\s*number|ifsc|salary\s+of|pay(?:slip)?\s+of|medical|police\s+verification|criminal)\b",
    re.IGNORECASE,
)


@dataclass
class Scan:
    #: none, identifier (it contains a private identifier) or restricted (it is about credentials, ID or pay).
    level: str = "none"
    kinds: list[str] = field(default_factory=list)

    @property
    def sensitive(self) -> bool:
        return self.level != "none"


def scan(text: str) -> Scan:
    found: list[str] = []
    remaining = text or ""
    for kind, pattern in PATTERNS:
        if pattern.search(remaining):
            found.append(kind)
            remaining = pattern.sub(" ", remaining)
    restricted = sorted({m.group(0).lower() for m in RESTRICTED.finditer(text or "")})
    if restricted:
        return Scan("restricted", sorted(set(found)) + [f"topic:{word}" for word in restricted])
    if found:
        return Scan("identifier", found)
    return Scan()


def redact(text: str) -> str:
    """The text with identifiers replaced, for places that must not hold them (logs, explanations)."""
    out = text or ""
    for kind, pattern in PATTERNS:
        out = pattern.sub(f"[{kind}]", out)
    return out
