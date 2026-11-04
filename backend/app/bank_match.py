"""Matching bank statement lines to what Orion already holds, and guessing what the rest are.

Reconciliation is the check that makes a balance trustworthy: every line the bank shows should be a movement the book holds (a client's
payment of a bill, an expense, a GST payment, an entry someone made), and every movement the book holds should appear at the bank. This module
does the matching; it decides nothing and writes nothing. ``bank.py`` does the saving, and a person confirms anything that is not certain.

What counts as a match: the same direction and exactly the same amount to the paisa, dated within a few days of each other. Text on the line
(a bill number, a client's name, a reference) raises confidence but is never required, because banks write narrations in their own way.
A match is made automatically only when it is unambiguous both ways: the line has one candidate and the candidate has one line. Anything else
is offered as a suggestion for the person to accept. One deposit that pays several bills is found too (a few movements that add up to the
line), and is only ever suggested.
"""

from __future__ import annotations

import itertools
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Iterable, Optional

#: How many days apart a line and a movement can be and still be the same thing: money takes a day or two to clear, a cheque longer.
AUTO_DAYS = 5
SUGGEST_DAYS = 12
COMBO_DAYS = 12
COMBO_MAX_SIZE = 4
COMBO_MAX_CANDIDATES = 24
COMBO_MAX_TRIES = 60_000

#: Words banks put in every narration; they say nothing about who the money is from.
STOPWORDS = frozenset(
    "neft imps upi rtgs ach ecs nach pos atm cash cheque chq transfer trf payment paid pay received from to by for the and "
    "bank limited ltd pvt private india indian invoice inv bill ref reference credit debit cr dr txn trans transaction online "
    "internet banking mobile through via account acct a/c towards salary march april may june july august september october november "
    "december january february".split()
)


@dataclass(frozen=True)
class Candidate:
    """A movement that could be the line, with how well it fits and why."""

    movement: dict[str, Any]
    score: int
    days: int
    reasons: tuple[str, ...]

    @property
    def strong_text(self) -> bool:
        return any(reason.startswith(("bill number", "reference")) for reason in self.reasons)


def _day(value: Any) -> date:
    return value if isinstance(value, date) else date.fromisoformat(str(value)[:10])


def _dec(value: Any) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"))


def tokens(text: Optional[str]) -> set[str]:
    """The words in a narration or a name that could identify someone: letters and digits, four or more, minus the banks' own words."""
    return {word for word in re.findall(r"[a-z0-9]{4,}", (text or "").lower()) if word not in STOPWORDS and not word.isdigit()}


def digits(text: Optional[str]) -> str:
    return re.sub(r"[^0-9a-z]", "", (text or "").lower())


def text_signals(line: dict[str, Any], movement: dict[str, Any]) -> tuple[int, tuple[str, ...]]:
    """What the words on the line say about the movement: a bill number or reference on both is strong, the same client's name is some."""
    reasons: list[str] = []
    score = 0
    haystack = digits(f"{line.get('description') or ''} {line.get('reference') or ''}")
    for key in ("reference", "bill_number"):
        ref = movement.get(key)
        normalised = digits(str(ref)) if ref else ""
        # a bill number like 2026-27/185 becomes 202627185; a short reference would match anything, so it must be long enough to mean something
        if len(normalised) >= 7 and normalised in haystack:
            reasons.append(f"bill number {ref}" if key == "bill_number" or "/" in str(ref) else f"reference {ref}")
            score += 40
            break
    names = tokens(movement.get("counterparty")) | tokens(movement.get("detail"))
    shared = names & tokens(line.get("description"))
    if shared:
        reasons.append("name " + ", ".join(sorted(shared)[:2]))
        score += 30 if len(shared) > 1 else 20
    return score, tuple(reasons)


def _proximity(days: int) -> int:
    for limit, points in ((0, 50), (1, 45), (2, 40), (3, 35), (5, 25), (7, 15)):
        if days <= limit:
            return points
    return 5


def candidates(line: dict[str, Any], movements: Iterable[dict[str, Any]], *, window_days: int = SUGGEST_DAYS) -> list[Candidate]:
    """Movements the line could be: same direction, same amount, within ``window_days``. Best fit first."""
    out: list[Candidate] = []
    amount = _dec(line["amount"])
    when = _day(line["line_date"])
    for movement in movements:
        if movement["direction"] != line["direction"] or _dec(movement["amount"]) != amount:
            continue
        days = abs((_day(movement["move_date"]) - when).days)
        if days > window_days:
            continue
        text_score, reasons = text_signals(line, movement)
        why = (f"{days} day{'s' if days != 1 else ''} apart" if days else "same day",) + reasons
        out.append(Candidate(movement, _proximity(days) + text_score, days, why))
    out.sort(key=lambda c: (-c.score, c.days, str(c.movement["source_ref"])))
    return out


def combinations_for(line: dict[str, Any], movements: Iterable[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Two to four movements that together add up to the line: one deposit that pays several bills, one payment that settles several costs.
    Searched among movements of the same direction near the date, and cut off so a busy month cannot make it slow. Never matched
    automatically; offered for the person to accept. Fewest movements first."""
    amount = _dec(line["amount"])
    when = _day(line["line_date"])
    pool = [m for m in movements if m["direction"] == line["direction"] and abs((_day(m["move_date"]) - when).days) <= COMBO_DAYS and _dec(m["amount"]) < amount]
    pool.sort(key=lambda m: (abs((_day(m["move_date"]) - when).days), str(m["source_ref"])))
    pool = pool[:COMBO_MAX_CANDIDATES]
    found: list[list[dict[str, Any]]] = []
    tries = 0
    for size in range(2, COMBO_MAX_SIZE + 1):
        for group in itertools.combinations(pool, size):
            tries += 1
            if tries > COMBO_MAX_TRIES:
                return found
            if sum((_dec(m["amount"]) for m in group), Decimal(0)) == amount:
                found.append(list(group))
                if len(found) >= 5:
                    return found
        if found:
            break
    return found


def auto_pairs(lines: list[dict[str, Any]], movements: list[dict[str, Any]]) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """Line and movement pairs that are certain enough to match without asking: a line with one candidate whose candidate has one line, or
    several candidates of which exactly one has the bill number or reference on the line and nothing else claims it."""
    near = {line["line_id"]: candidates(line, movements, window_days=AUTO_DAYS) for line in lines}
    claimed: dict[tuple[str, str], list[int]] = {}
    for line_id, found in near.items():
        for candidate in found:
            claimed.setdefault((candidate.movement["source"], candidate.movement["source_ref"]), []).append(line_id)
    pairs: list[tuple[dict[str, Any], dict[str, Any]]] = []
    used: set[tuple[str, str]] = set()
    for line in lines:
        found = near[line["line_id"]]
        choice: Optional[Candidate] = None
        if len(found) == 1:
            choice = found[0]
        else:
            strong = [c for c in found if c.strong_text]
            if len(strong) == 1:
                choice = strong[0]
        if choice is None:
            continue
        key = (choice.movement["source"], choice.movement["source_ref"])
        rivals = [other for other in claimed[key] if other != line["line_id"]]
        if key in used:
            continue
        if rivals and not choice.strong_text:
            continue
        if rivals:  # several lines want it: it is theirs only if no other line carries the text
            others_strong = any(
                any(c.strong_text for c in near[other] if (c.movement["source"], c.movement["source_ref"]) == key) for other in rivals
            )
            if others_strong:
                continue
        used.add(key)
        pairs.append((line, choice.movement))
    return pairs


# ------------------------------------------------------------------------------------------------------------ what is this line?

#: (category, direction, pattern, why). The first that fits wins. These are the lines every bank statement has; anything they do not recognise is
#: left for the person (or the AI) to decide.
RULES: tuple[tuple[str, str, re.Pattern[str], str], ...] = (
    ("interest", "in", re.compile(r"\b(int\.?\s*pd|int\.?\s*credit|interest|int on|sb int|savings int|credit interest)\b", re.I), "looks like interest the bank paid"),
    ("bank_charges", "out", re.compile(r"\b(charges?|chgs?|sms|amc|annual fee|min(imum)? bal|non[- ]?maintenance|penal|processing fee|service fee|ecs return|chq return|cheque return|gst on (charges|fee)|debit card)\b", re.I), "looks like a bank charge"),
    ("tax", "out", re.compile(r"\b(income tax|advance tax|itns|self assessment|cbdt|tds payment|tds on)\b", re.I), "looks like a tax payment"),
    ("gst_other", "out", re.compile(r"\b(gst|cbic|cgst|sgst|igst|gstn)\b", re.I), "looks like GST paid to the government"),
    ("statutory", "out", re.compile(r"\b(epfo|\bpf\b|provident fund|esic|\besi\b|labour welfare|professional tax)\b", re.I), "looks like PF, ESI or another statutory payment"),
    ("salary", "out", re.compile(r"\b(salary|salaries|wages|payroll|sal for|staff pay)\b", re.I), "looks like salary or wages"),
    ("loan_repayment", "out", re.compile(r"\b(emi|loan repay|loan instal|loan a/?c|repayment of loan)\b", re.I), "looks like a loan repayment"),
    ("loan_in", "in", re.compile(r"\b(loan (disb|credit|a/?c)|disbursement|loan proceeds)\b", re.I), "looks like a loan received"),
    ("refund", "in", re.compile(r"\b(refund|reversal|rev of|returned|chq return)\b", re.I), "looks like a refund or reversal"),
)


def classify(line: dict[str, Any]) -> Optional[dict[str, Any]]:
    """A guess at what an unmatched line is, from its narration: ``{"category", "why"}`` or None when nothing is recognised."""
    text = f"{line.get('description') or ''} {line.get('reference') or ''}"
    for category, direction, pattern, why in RULES:
        if direction == line["direction"] and pattern.search(text):
            return {"category": category, "why": why}
    return None


def mask_numbers(text: str) -> str:
    """For anything leaving this computer: account and card numbers and UTRs reduced to their last four digits."""
    return re.sub(r"\d{9,}", lambda m: "…" + m.group(0)[-4:], text or "")
