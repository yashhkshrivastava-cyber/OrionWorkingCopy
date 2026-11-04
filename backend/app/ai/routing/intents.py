"""Understanding common requests with rules, so the application can answer them without asking a model.

"Show me the top 10 customers", "compare this month with last month", "who owes us the most", "remind me to chase Acme next
week", "how many clients do we have": each is a pattern here that turns into a call to one of the Copilot's tools. The tools
do the work against the real data, and ``compose.py`` writes the answer from what they return.

A request that is not recognised returns None and goes to a model. Rules are used only when they are sure: a plan has a
confidence, and a wrong guess is worse than asking a model, so the patterns are narrow.
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Callable

from app.ai.routing import names as _names
from app.dashboard.filters import DIMENSION_KEYS

MIN_CONFIDENCE = 0.7

MONTHS = {name.lower(): i for i, name in enumerate(calendar.month_name) if name}
MONTHS.update({name.lower(): i for i, name in enumerate(calendar.month_abbr) if name})
MONTHS["sept"] = 9
WEEKDAYS = {name.lower(): i for i, name in enumerate(calendar.day_name)}

# Words that mean a period, most specific first.
_PERIODS: list[tuple[re.Pattern[str], str, str]] = [
    (re.compile(r"\b(last|past|previous) (12|twelve) months\b|\bpast year\b|\blast twelve\b|\btrailing (12|twelve)\b", re.I), "last_12_months", "the last 12 months"),
    (re.compile(r"\b(last|past) (90|ninety) days\b|\b(last|past) (3|three) months\b", re.I), "last_90_days", "the last 90 days"),
    (re.compile(r"\b(last|past) (30|thirty) days\b", re.I), "last_30_days", "the last 30 days"),
    (re.compile(r"\b(last|past) (7|seven) days\b|\b(last|past|previous) week\b", re.I), "last_7_days", "the last 7 days"),
    (re.compile(r"\b(last|previous) quarter\b", re.I), "last_quarter", "last quarter"),
    (re.compile(r"\b(this|current) quarter\b|\bquarter to date\b|\bqtd\b", re.I), "this_quarter", "this quarter"),
    (re.compile(r"\b(last|previous) (financial|fiscal) year\b|\blast fy\b|\bprevious fy\b", re.I), "last_fy", "last financial year"),
    (re.compile(r"\b(this|current) (financial|fiscal) year\b|\bthis fy\b|\bcurrent fy\b|\bytd\b|\byear to date\b", re.I), "this_fy", "this financial year"),
    (re.compile(r"\blast year\b|\bprevious year\b", re.I), "last_year", "last calendar year"),
    (re.compile(r"\bthis year\b|\bcurrent year\b", re.I), "this_year", "this calendar year"),
    (re.compile(r"\b(last|previous) month\b", re.I), "last_month", "last month"),
    (re.compile(r"\b(this|current) month\b|\bmtd\b|\bmonth to date\b|\bso far this month\b", re.I), "this_month", "this month"),
    (re.compile(r"\ball[- ]time\b|\boverall\b|\bever\b|\bsince (the )?(start|beginning)\b|\bto date\b", re.I), "all_time", "all time"),
]
_MONTH_NAME = re.compile(r"\b(" + "|".join(sorted(MONTHS, key=len, reverse=True)) + r")\b(?:[ ,]+(\d{4}))?", re.I)

_METRICS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bcollection rate\b|\bcollected %", re.I), "collection_rate"),
    (re.compile(r"\bmargin %|\bmargin percent|\bmargin percentage\b", re.I), "margin_pct"),
    (re.compile(r"\bcollect(ed|ions?)?\b|\bcash( in)?\b|\bpayments? received\b|\breceived\b", re.I), "collected"),
    (re.compile(r"\bbilled\b|\bbilling\b|\binvoiced\b", re.I), "billed"),
    (re.compile(r"\bpayroll\b|\bsalary cost\b|\bsalaries\b|\bwages\b", re.I), "payroll"),
    (re.compile(r"\bexpenses?\b|\bspend(ing)?\b|\boperating cost\b", re.I), "expenses"),
    (re.compile(r"\bmargin\b|\bprofit(ability)?\b|\bearnings?\b", re.I), "margin"),
    (re.compile(r"\boverdue\b|\bover 90\b|\bmore than 90\b", re.I), "overdue_90"),
    (re.compile(r"\boutstanding\b|\bowed\b|\breceivables?\b|\bunpaid\b", re.I), "outstanding"),
    (re.compile(r"\bdso\b|\bdays sales outstanding\b|\bdays to collect\b", re.I), "dso"),
    (re.compile(r"\bhow many bills\b|\bnumber of bills\b|\bbills raised\b", re.I), "bills"),
    (re.compile(r"\bcancel(l)?ed bills\b", re.I), "cancelled"),
    (re.compile(r"\bgst\b", re.I), "gst"),
    (re.compile(r"\bheadcount\b|\bstaff on payroll\b|\bemployees on payroll\b", re.I), "heads"),
    (re.compile(r"\brevenue\b|\bsales\b|\bturnover\b|\bincome\b|\btop line\b", re.I), "revenue"),
]
SNAPSHOT = {"outstanding", "overdue_90", "dso"}
_SKIP_NAMES = {
    "i", "the", "this", "that", "last", "next", "show", "what", "which", "who", "how", "why", "compare", "give", "list", "find", "top", "can", "please", "all", "our", "my",
    "revenue", "tally", "january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december", "monday", "tuesday", "wednesday",
    "thursday", "friday", "saturday", "sunday", "q1", "q2", "q3", "q4", "fy", "gst", "a", "an", "me",
}


@dataclass
class Plan:
    intent: str
    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    confidence: float = 0.9
    notes: list[str] = field(default_factory=list)
    clarify: str | None = None
    #: A fixed reply for talk that needs no data (a greeting, "what can you do").
    reply: str | None = None

    @property
    def usable(self) -> bool:
        return self.confidence >= MIN_CONFIDENCE and bool(self.calls or self.clarify or self.reply)


# ----------------------------------------------------------------------------------------------------- pieces


def _month_span(month: int, year: int | None, today: date) -> dict[str, str]:
    if year is None:
        year = today.year if month <= today.month else today.year - 1
    last = calendar.monthrange(year, month)[1]
    return {"from": date(year, month, 1).isoformat(), "to": date(year, month, last).isoformat()}


def _find_periods(text: str, today: date) -> list[tuple[dict[str, str], str]]:
    """Every period named, in the order written: ({"period": preset} or {"from", "to"}, a name for it)."""
    found: list[tuple[int, dict[str, str], str]] = []
    taken: list[tuple[int, int]] = []
    for pattern, preset, label in _PERIODS:
        for m in pattern.finditer(text):
            if any(a <= m.start() < b for a, b in taken):
                continue
            taken.append((m.start(), m.end()))
            found.append((m.start(), {"period": preset}, label))
    for m in _MONTH_NAME.finditer(text):
        if any(a <= m.start() < b for a, b in taken):
            continue
        word = m.group(1).lower()
        if word == "may" and not re.search(r"\bin may\b|\bmay \d{4}\b|\bof may\b|\bfor may\b|\bmay\b$|\bmay\?", text, re.I):
            continue  # the verb
        year = int(m.group(2)) if m.group(2) else None
        span = _month_span(MONTHS[word], year, today)
        found.append((m.start(), span, f"{calendar.month_name[MONTHS[word]]} {span['from'][:4]}"))
    found.sort(key=lambda item: item[0])
    return [(spec, label) for _pos, spec, label in found]


def _metric(text: str) -> str | None:
    for pattern, key in _METRICS:
        if pattern.search(text):
            return key
    return None


def _name_filter(original: str) -> dict[str, str]:
    """A client named in the question ("revenue of Civil Hospital last month"), to be matched by the server against real clients."""
    for m in re.finditer(r"\b(?:for|of|from|by|with|at|about)\s+(?:the\s+)?((?:[A-Z][\w&.'-]*)(?:\s+(?:[A-Z][\w&.'-]*|\d+))*)", original):
        name = m.group(1).strip()
        if name.split()[0].lower() in _SKIP_NAMES or len(name) < 3:
            continue
        return {"client": name}
    return {}


def page_selection(page: dict[str, Any] | None) -> dict[str, Any]:
    """What the dashboard on screen is set to, as tool arguments: its dates and its client/case filters."""
    if not page or page.get("area") != "dashboard":
        return {}
    filters = page.get("filters") or {}
    out: dict[str, Any] = {}
    if filters.get("from") or filters.get("to"):
        out.update({k: filters[k] for k in ("from", "to") if filters.get(k)})
    dims = {k: v for k, v in filters.items() if k in DIMENSION_KEYS and v}
    if dims:
        out["filters"] = dims
    return out


def _scope(text: str, original: str, page: dict[str, Any] | None, today: date, default_period: str, notes: list[str]) -> dict[str, Any]:
    """The period and filters for a tool call: what the person said, else what is on their screen, else a sensible default."""
    args: dict[str, Any] = {}
    named = _find_periods(text, today)
    chosen = page_selection(page)
    if named:
        args.update(named[0][0])
        chosen.pop("from", None)
        chosen.pop("to", None)
    elif "from" in chosen or "to" in chosen:
        notes.append("the dates set on the dashboard you are looking at")
    else:
        args["period"] = default_period
        label = next((lbl for _p, preset, lbl in _PERIODS if preset == default_period), default_period)
        notes.append(f"{label}" + (", the latest complete month" if default_period == "last_month" else ""))
    filters = dict(chosen.pop("filters", {}))
    mentioned = _name_filter(original)
    if mentioned and "client" not in filters:
        filters.update(mentioned)
    args.update(chosen)
    if filters:
        args["filters"] = filters
    return args


# What people call a record type, besides its own name.
SYNONYMS = {
    "Client": ("customer", "party", "parties", "company", "companies", "account"),
    "Case": ("site", "contract", "project", "deployment", "posting"),
    "Employee": ("guard", "staff", "worker", "personnel", "people", "headcount", "supervisor"),
    "Car": ("vehicle", "van", "bike"),
    "Opportunity": ("lead", "prospect", "tender", "enquiry", "inquiry"),
    "Contact": ("point of contact", "contact person", "poc", "representative"),
    "EMD": ("earnest money", "earnest money deposit"),
}


def _entity(text: str) -> str | None:
    """The record type a sentence is about: the one it names first ("how many sites do we guard" is about sites, not guards)."""
    from app.ai.tools.records import ENTITY_NAMES

    lowered = text.lower()
    best: tuple[int, int, str] | None = None
    for name in ENTITY_NAMES:
        base = name.lower()
        words = {base, *SYNONYMS.get(name, ())}
        forms = set()
        for word in words:
            forms |= {word, word + "s", word[:-1] + "ies" if word.endswith("y") else word + "es"}
        for form in forms:
            found = re.search(rf"\b{re.escape(form)}\b", lowered)
            if found:
                key = (found.start(), -len(form), name)
                if best is None or key < best:
                    best = key
    return best[2] if best else None


def _when(text: str, today: date) -> tuple[str | None, str | None]:
    """A due date and time in a reminder request ("tomorrow at 5pm", "next week", "on 15 October", "in 3 days")."""
    lowered = text.lower()
    day: date | None = None
    if "tomorrow" in lowered:
        day = today + timedelta(days=1)
    elif re.search(r"\btoday\b|\btonight\b", lowered):
        day = today
    elif re.search(r"\bnext week\b", lowered):
        day = today + timedelta(days=7)
    elif re.search(r"\bnext month\b", lowered):
        month = today.month % 12 + 1
        year = today.year + (1 if today.month == 12 else 0)
        day = date(year, month, min(today.day, calendar.monthrange(year, month)[1]))
    elif m := re.search(r"\bin (\d{1,3}) (day|week|month)s?\b", lowered):
        n = int(m.group(1))
        day = today + timedelta(days=n * {"day": 1, "week": 7, "month": 30}[m.group(2)])
    elif m := re.search(r"\b(?:next\s+|on\s+)?(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", lowered):
        ahead = (WEEKDAYS[m.group(1)] - today.weekday() - 1) % 7 + 1
        day = today + timedelta(days=ahead)
    elif m := re.search(r"\b(?:on\s+)?(\d{1,2})(?:st|nd|rd|th)?\s+(" + "|".join(sorted(MONTHS, key=len, reverse=True)) + r")\b(?:\s+(\d{4}))?", lowered):
        month, number = MONTHS[m.group(2)], int(m.group(1))
        year = int(m.group(3)) if m.group(3) else today.year
        try:
            day = date(year, month, number)
            if day < today and not m.group(3):
                day = date(year + 1, month, number)
        except ValueError:
            day = None
    clock = None
    if m := re.search(r"\bat (\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b", lowered):
        hour = int(m.group(1)) % 12 + (12 if (m.group(3) or "").lower() == "pm" else 0) if m.group(3) else int(m.group(1))
        if 0 <= hour <= 23:
            clock = f"{hour:02d}:{m.group(2) or '00'}"
    return (day.isoformat() if day else None), clock


_NUMBER = r"\d[\d,]*(?:\.\d+)?"
_UNIT = {"lakh": 100_000, "lakhs": 100_000, "lac": 100_000, "l": 100_000, "crore": 10_000_000, "crores": 10_000_000, "cr": 10_000_000, "k": 1_000, "thousand": 1_000, "million": 1_000_000}


def _amount(token: str) -> str | None:
    m = re.fullmatch(rf"({_NUMBER})\s*([a-z]+)?", token.strip().lower())
    if not m:
        return None
    value = m.group(1).replace(",", "")
    if m.group(2):
        if m.group(2) not in _UNIT:
            return None
        return f"({value}*{_UNIT[m.group(2)]})"
    return value


def _expression(text: str) -> str | None:
    """Arithmetic written in words or symbols ("15% of 2,40,000", "12.5 lakh + 3 lakh"), as an expression the calculator takes."""
    lowered = text.lower().replace("×", "*").replace("÷", "/")
    if m := re.search(rf"({_NUMBER})\s*(?:%|percent)\s*of\s*({_NUMBER}\s*[a-z]*)", lowered):
        a, b = _amount(m.group(1)), _amount(m.group(2))
        if a and b:
            return f"{a}/100*{b}"
    tokens = re.findall(rf"({_NUMBER}\s*[a-z]*)\s*(\+|-|\*|/|x|plus|minus|times|divided by|multiplied by)\s*(?={_NUMBER})", lowered)
    if tokens:
        # Rebuild the whole sum in order.
        parts = re.split(r"\s*(\+|-|\*|/|\bx\b|\bplus\b|\bminus\b|\btimes\b|\bdivided by\b|\bmultiplied by\b)\s*", re.sub(r"^.*?(?=" + _NUMBER + ")", "", lowered, count=1).strip(" ?.!"))
        expression, ops = "", {"x": "*", "plus": "+", "minus": "-", "times": "*", "divided by": "/", "multiplied by": "*"}
        for part in parts:
            part = part.strip()
            if not part:
                continue
            if part in ("+", "-", "*", "/") or part in ops:
                expression += ops.get(part, part)
            elif (value := _amount(part)) is not None:
                expression += value
            else:
                return None
        if re.fullmatch(r"[\d.()+\-*/]+", expression) and re.search(r"[+\-*/]", expression):
            return expression
    return None


# ------------------------------------------------------------------------------------------------------ small talk

CAPABILITIES = (
    "I can look things up in your data and do things for you. For example:\n"
    "- **Figures:** “How are we doing this month?”, “What was revenue last quarter?”, “Compare September with August”\n"
    "- **Why:** “Why did revenue fall last month?”, “Who are my top 10 customers?”, “Who owes us the most?”\n"
    "- **Records:** “How many clients do we have?”, “Find client Acme”, “Which documents are expiring?”\n"
    "- **The Tally books:** “How is billing in Tally?”, “Who are our top clients in Tally?”, “How many credit notes this year?”, “What do the Sundry Debtors show?”\n"
    "- **Actions:** “Create a receivables report”, “Remind me to chase Acme next week”, “Export bills”, “Delete client CL-0007” (I'll ask you to confirm)\n"
    "- **Maths:** “What is 15% of 2,40,000?”"
)

_SMALLTALK: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"^\s*(thanks?( you)?( so much)?|thank you( so much)?|cheers|much appreciated)\W*$", re.I), "You're welcome."),
    (re.compile(r"^\s*(bye|goodbye|see you|good night)\W*$", re.I), "Goodbye."),
    (re.compile(r"^\s*(ok(ay)?|cool|great|nice|got it|alright|fine)\W*$", re.I), "Okay. Ask me anything about your data when you're ready."),
    (re.compile(r"^\s*(hi+|hello+|hey+|namaste|good\s+(morning|afternoon|evening)|hi there|hello there)\W*$", re.I), "Hello! " + CAPABILITIES),
    (re.compile(r"^\s*(help|what can you do|what do you do|how do (i|you) use (this|you)|what can i ask( you)?|who are you|what are you)\W*$", re.I), "I'm the Orion Copilot, built into your workspace. " + CAPABILITIES),
]

# What needs thought rather than a lookup: a model's job (or a person's), not the rules'.
_NEEDS_REASONING = re.compile(
    r"\b(recommend\w*|advice|advise|suggest\w*|what to do|what should (we|i) do|how (can|could|should|do) (we|i)|improv\w*|strateg\w*|forecast\w*|predict\w*|"
    r"plan for|pros and cons|pros|cons|trade-?offs?|negotiat\w*|draft|write (a|an|me)|explain (how|what|the concept)|thin|healthy|good or bad|worried|concern\w*)\b",
    re.I,
)
_DEFINING = re.compile(r"^\s*(please\s+)?(explain|define|describe|tell me about)\b|\bwhat (does|do) .{0,50}\bmean\b|\bmeaning of\b|\bwhat is an? [a-z ]{3,40}\??\s*$|\bdifference between (a|an|the)\b", re.I)
_CHANGE_WORD = re.compile(r"\b(fall|fell|falling|drop|dropped|decline|declined|declining|decreas\w*|down|lower|rise|rose|rising|grow|grew|growth|increas\w*|up|jump\w*|higher|change[ds]?|move[ds]?|differ\w*)\b", re.I)



# ------------------------------------------------------------------------------------------------------ Tally

# A request is about the Tally books when it says so, or uses a word that only the books have (a credit note, a sundry debtor).
_TALLY_WORDS = re.compile(r"\btally\b|\bsundry (debtors?|creditors?)\b|\bcredit notes?\b|\bdebit notes?\b|\bgst (payable|liability)\b|\bclosing balances?\b|\bthe books\b|\bledgers?\b", re.I)
# On a Tally page a plain question is about Tally, unless it uses a word that only Orion's own records have.
_ORION_ONLY = re.compile(r"\b(owe|owes|owed|overdue|receivables?|outstanding|payroll|salar\w+|margin|collections?|collected|employees?|staff|headcount|cases?|sites?|opportunit\w+|tenders?|fleet|km|expenses?)\b", re.I)
_TALLY_NOT_NAMES = {"tally", "sundry", "gst", "epf", "esic", "manpower", "vehicle", "credit", "debit", "books", "income", "ledger", "ledgers"}
_INCOME = [
    (re.compile(r"\bmanpower\b", re.I), "manpower"),
    (re.compile(r"\bvehicle( rent(al)?)?\b|\brent(al)? income\b", re.I), "vehicle_rent"),
    (re.compile(r"\bsg service\b|\bservice charges?\b", re.I), "service_charges"),
    (re.compile(r"\bepf\b", re.I), "epf_billed"),
    (re.compile(r"\besic\b", re.I), "esic_billed"),
    (re.compile(r"\bother income\b", re.I), "other_income"),
]
_TALLY_METRICS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bhow many (invoices|documents|bills|vouchers)\b|\bnumber of (invoices|documents|vouchers)\b", re.I), "invoices"),
    (re.compile(r"\bhow many clients\b|\bclients? (billed|did we bill)\b|\bnumber of clients\b", re.I), "clients"),
    (re.compile(r"\baverage (invoice|bill|sale)\b", re.I), "avg_invoice"),
    (re.compile(r"\bgst\b", re.I), "gst"),
    (re.compile(r"\brevenue\b|\bsales\b|\bturnover\b|\bex(cluding)? gst\b|\bbefore gst\b", re.I), "revenue"),
    (re.compile(r"\bbilled\b|\bbilling\b|\binvoiced\b|\bbill\b", re.I), "billed"),
]


def _fy_dates(value: str) -> dict[str, str]:
    """A financial year such as "2026" (April 2026 to March 2027) as dates."""
    try:
        year = int(str(value)[:4])
    except ValueError:
        return {}
    return {"from": f"{year}-04-01", "to": f"{year + 1}-03-31"}


def tally_selection(page: dict[str, Any] | None) -> dict[str, Any]:
    """What the Tally dashboard on screen is set to, as tool arguments: its dates and its client/company/document filters."""
    if not page or page.get("area") != "dashboard_tally":
        return {}
    filters = page.get("filters") or {}
    out: dict[str, Any] = {}
    if filters.get("from") or filters.get("to"):
        out.update({k: filters[k] for k in ("from", "to") if filters.get(k)})
    elif filters.get("fy"):
        out.update(_fy_dates(filters["fy"]))
    dims = {k: v for k, v in filters.items() if k in ("client", "company", "voucher_type", "income_line", "cost_centre") and v}
    if dims:
        out["filters"] = dims
    return out


def _tally_scope(t: str, original: str, page: dict[str, Any], today: date, default_period: str, notes: list[str]) -> dict[str, Any]:
    args: dict[str, Any] = {}
    chosen = tally_selection(page)
    named = _find_periods(t, today)
    if named:
        args.update(named[0][0])
        chosen.pop("from", None)
        chosen.pop("to", None)
    elif "from" in chosen or "to" in chosen:
        notes.append("the dates set on the Tally dashboard you are looking at")
    else:
        args["period"] = default_period
        notes.append(next((lbl for _p, preset, lbl in _PERIODS if preset == default_period), default_period))
    filters = dict(chosen.pop("filters", {}))
    mentioned = _name_filter(original)
    if not mentioned:
        # "how much did we bill Narmada Cement Works": the name follows the verb, with no "for" or "of" before it.
        found = re.search(r"\b(?:bill|billed|invoiced?|charged?|sold to|sales to)\s+(?:the\s+)?((?:[A-Z][\w&.'-]*)(?:\s+(?:[A-Z][\w&.'-]*|\d+))*)", original)
        mentioned = {"client": found.group(1).strip()} if found else {}
    if mentioned and "client" not in filters:
        name = mentioned["client"]
        if name.split()[0].lower() not in _TALLY_NOT_NAMES and name.lower() not in _TALLY_NOT_NAMES:
            filters["client"] = name
    args.update(chosen)
    if filters:
        args["filters"] = filters
    return args


def _tally_plan(t: str, original: str, page: dict[str, Any], today: date) -> Plan | None:
    """The Tally tool calls that answer this, or None. The caller decides what None means."""
    notes: list[str] = []
    limit = re.search(r"\b(?:top|biggest|largest|best|highest)\s*(\d{1,2})\b", t)
    periods_named = _find_periods(t, today)

    if re.search(r"\b(gst (payable|liability)|loans?|creditors?|cash (and|&|in) bank|bank balances?|cash balances?|closing balances?|balance sheet|statutory|books say)\b", t):
        return Plan("tally_books", [("get_tally_books_position", {})], 0.88)
    if re.search(r"\bdebtors?\b", t):
        scope = {k: v for k, v in _tally_scope(t, original, page, today, "last_12_months", notes).items() if k == "filters"}
        return Plan("tally_debtors", [("get_tally_debtors", {**scope, "limit": int(limit.group(1)) if limit else 10})], 0.88)
    if re.search(r"\bcredit notes?\b|\bdebit notes?\b", t):
        return Plan("tally_notes", [("get_tally_credit_notes", _tally_scope(t, original, page, today, "last_12_months", notes))], 0.88, notes)
    single = next((metric for pattern, metric in _INCOME if pattern.search(t)), None)
    mix = re.search(
        r"\b(income|revenue)\s+(mix|split|by line|breakdown|lines?)\b|\bwhere does (the |our )?(income|revenue) come from\b|\bincome lines?\b"
        r"|\b(vs|versus|against)\b.*\b(manpower|vehicle|service|epf|esic)\b|\b(manpower|vehicle|service|epf|esic)\b.*\b(vs|versus|against)\b",
        t,
    )
    if mix:
        return Plan("tally_income", [("get_tally_income_mix", _tally_scope(t, original, page, today, "last_12_months", notes))], 0.86, notes)
    if single and re.search(r"\b(what|how much|show|tell|give|total|our)\b|\?|income|billed|billing", t):
        return Plan("tally_metric", [("get_tally_metric", {"metric": single, **_tally_scope(t, original, page, today, "last_month", notes)})], 0.85, notes)
    if re.search(
        r"\b(top|biggest|largest|best|highest|leading)\s*(\d{1,2})?\s*(clients?|customers?|parties)\b|\bwhich (clients?|customers?)\b.{0,30}\b(most|biggest|largest)\b|\bclients?\b.{0,20}\bby (revenue|billing|billed)\b",
        t,
    ):
        scope = {k: v for k, v in _tally_scope(t, original, page, today, "last_12_months", notes).items() if k != "filters"}
        by = "billed" if re.search(r"\bbilled\b|\bbilling\b|\binvoice", t) else "revenue"
        return Plan("tally_top", [("get_tally_top_clients", {**scope, "metric": by, "limit": int(limit.group(1)) if limit else 10})], 0.88, notes)
    metric = next((m for pattern, m in _TALLY_METRICS if pattern.search(t)), None)
    if re.search(r"\b(compare|versus|vs\.?|difference between|against|changed?|what changed)\b", t) and (metric or periods_named):
        a_spec = periods_named[0][0] if periods_named else {"period": "last_month"}
        args: dict[str, Any] = {"period_a": a_spec}
        if len(periods_named) > 1:
            args["period_b"] = periods_named[1][0]
        if metric:
            args["metrics"] = [metric]
        chosen = tally_selection(page).get("filters")
        if chosen:
            args["filters"] = chosen
        return Plan("tally_compare", [("compare_tally_periods", args)], 0.86, notes)
    if metric and not re.search(r"\b(why|how to|should|recommend)\b", t) and (re.search(r"\b(what|how much|how many|show|tell|give|total|our)\b", t) or periods_named):
        return Plan("tally_metric", [("get_tally_metric", {"metric": metric, **_tally_scope(t, original, page, today, "last_month", notes)})], 0.85, notes)
    if re.search(r"\b(summari[sz]e|summary|overview|how (are|is) (we|billing|the books|it)|status|doing|performance|what do (the books|tally)|dashboard|looking at|key figures|snapshot)\b", t):
        return Plan("tally_summary", [("get_tally_summary", _tally_scope(t, original, page, today, "last_12_months", notes))], 0.86, notes)
    return None


# ------------------------------------------------------------------------------------------------------ the plan


def is_definition(text: str) -> bool:
    """A question about what a word or idea means, which no figure in the data can answer."""
    t = text.lower()
    return bool(_DEFINING.search(t) and not _CHANGE_WORD.search(t))


CLIENT_SCOPED = {"get_business_summary", "get_metric", "compare_periods", "explain_change", "get_trend", "find_anomalies"}


def focus_on_named_client(found: Plan | None, text: str, names: Callable[[], list[str]] | None) -> Plan | None:
    """"What's going on with Civil Hospital?" is about Civil Hospital, not the whole company: the client is added as a filter."""
    if found is None or names is None:
        return found
    known = _names.find_in(text, names)
    if not known:
        return found
    for i, (tool, args) in enumerate(found.calls):
        if tool in CLIENT_SCOPED and not (args.get("filters") or {}).get("client"):
            found.calls[i] = (tool, {**args, "filters": {**(args.get("filters") or {}), "client": known}})
            found.notes.append(f"figures for {known} only")
    return found


def plan(text: str, page: dict[str, Any] | None = None, today: date | None = None, names: Callable[[], list[str]] | None = None) -> Plan | None:
    return focus_on_named_client(_plan(text, page, today, names), text, names)


def _plan(text: str, page: dict[str, Any] | None = None, today: date | None = None, names: Callable[[], list[str]] | None = None) -> Plan | None:
    """The tool calls that answer this request, or None when it is not one of the patterns the application knows."""
    today = today or date.today()
    original = text.strip()
    t = original.lower()
    page = page or {}
    notes: list[str] = []

    for pattern, reply in _SMALLTALK:
        if pattern.match(original):
            return Plan("smalltalk", [], 0.95, reply=reply)

    if re.search(r"\b(ignore|disregard|forget)\b.{0,40}\b(instruction|rule|prompt)s?\b|\bsystem prompt\b|\bjailbreak\b|\bdeveloper mode\b", t):
        return None
    if re.search(r"\b(delete|remove|wipe|erase|drop)\s+(all|everything|every)\b", t):
        return None  # never one request that touches many things: a model (or a person) can say no
    if re.search(r"\bsql\b|\bselect\b.+\bfrom\b|\bdrop table\b|\bquery the database\b", t):
        return None
    if _NEEDS_REASONING.search(t) and not re.search(r"\b(focus|attention|biggest problems?)\b", t):
        return None
    if _DEFINING.search(t) and not _CHANGE_WORD.search(t):
        return None  # "explain what ageing buckets mean" is a question about a word, not a request for the receivables

    # --- calculation ---------------------------------------------------------------------------------------------
    if (m := re.search(r"\b(calculate|compute|what is|what's|how much is|work out)\b", t)) or re.search(rf"{_NUMBER}\s*%\s*of\b", t):
        expression = _expression(t)
        if expression:
            return Plan("calculate", [("calculate", {"expression": expression})], 0.92)

    # --- settings and navigation -----------------------------------------------------------------------------------
    if re.search(r"\b(dark|light)\s*(mode|theme)\b|\b(switch|turn|change|make).{0,20}\b(dark|light)\b", t):
        return Plan("appearance", [("set_appearance", {"mode": "dark" if "dark" in t else "light"})], 0.93)
    if m := re.search(r"\b(?:switch|change|use|set|apply)\b.{0,25}\b(default|midnight|aurora|obsidian|ivory|flux)\b(?:\s+theme)?", t):
        return Plan("appearance", [("set_appearance", {"theme": m.group(1)})], 0.9)
    if m := re.search(r"\b(?:open|go to|take me to|show me the|navigate to)\s+(?:the\s+)?(overview|revenue|collections|profitability|people|pipeline|fleet|controls)\s+(?:dashboard|tab)\b", t):
        return Plan("open_page", [("open_page", {"page": "dashboard", "view": m.group(1), **{k: v for k, v in page_selection(page).items()}})], 0.9)
    pages = {"billing": "billing", "bills": "billing", "receivables": "receivables", "documents": "documents", "document center": "documents", "letterhead": "letterhead", "settings": "settings",
             "messages": "messages", "orion data": "data", "admin": "admin"}
    if m := re.search(r"\b(?:open|go to|take me to|navigate to)\s+(?:the\s+)?(billing|bills|receivables|documents|document center|letterhead|settings|messages|orion data|admin)(?:\s+page)?\b", t):
        return Plan("open_page", [("open_page", {"page": pages[m.group(1)]})], 0.88)

    # --- reminders ---------------------------------------------------------------------------------------------------
    if re.search(r"\b(my|open|pending|upcoming)\s+(reminders?|tasks?|to-?dos?)\b", t) and not re.search(r"\b(remind me|create|add|set)\b", t):
        return Plan("reminders", [("get_reminders", {})], 0.9)
    if m := re.search(r"\b(remind me|set (?:a )?reminder|add (?:a )?(?:reminder|task)|create (?:a )?(?:reminder|task))\b(?:\s+(?:to|about|that|for))?\s*(.*)", original, re.I):
        due, clock = _when(original, today)
        title = re.sub(r"\b(?:tomorrow|today|tonight|next (?:week|month)|in \d+ (?:day|week|month)s?|on [a-z]+day|at \d{1,2}(?::\d{2})?\s*(?:am|pm)?|on \d{1,2}(?:st|nd|rd|th)? [a-z]+(?: \d{4})?)\b", "", m.group(2), flags=re.I).strip(" .,-")
        if len(title) < 3:
            return Plan("reminder", [], 0.9, clarify="What should I remind you about?")
        if not due:
            return Plan("reminder", [], 0.9, clarify=f"When should I remind you to {title[:80]}? For example “tomorrow at 10am” or “on 15 October”.")
        args: dict[str, Any] = {"kind": "task" if re.search(r"\btask\b", m.group(1), re.I) else "reminder", "title": title[:150], "due_date": due}
        if clock:
            args["due_time"] = clock
        if re.search(r"\b(this|here|this page|this dashboard)\b", t):
            args["link_to_current_page"] = True
        return Plan("reminder", [("create_reminder_or_task", args)], 0.9)

    # --- the Tally books -----------------------------------------------------------------------------------------
    explicit_tally = bool(_TALLY_WORDS.search(t))
    if explicit_tally or (page.get("area") == "dashboard_tally" and not _ORION_ONLY.search(t)):
        if explicit_tally and re.search(r"\b(remind me|delete|remove|export|download|excel|csv|report|pdf|email|send)\b", t):
            return None  # nothing the rules do for the books; a model, or a person, decides
        found = _tally_plan(t, original, page, today)
        if found is not None:
            return found
        if explicit_tally:
            return None  # it is about the books but not a shape the rules know; never answer it from Orion's records

    # --- deleting one named record ---------------------------------------------------------------------------------
    if m := re.search(r"\b(?:delete|remove)\s+(?:the\s+)?([a-z ]+?)\s+([A-Za-z]{1,4}-?\d{1,8}|[A-Z]{2,}-[A-Za-z0-9-]+)\b", original, re.I):
        entity = _entity(m.group(1))
        if entity:
            return Plan("delete", [("delete_record", {"entity": entity, "id": m.group(2).upper()})], 0.88)

    # --- exports and reports -------------------------------------------------------------------------------------
    if re.search(r"\b(report|summary report|pdf)\b", t) and re.search(r"\b(create|generate|make|prepare|build|give me|produce|need)\b", t):
        kind = "receivables" if re.search(r"receivable|owe|overdue|outstanding|ageing|aging", t) else "revenue_by_client" if re.search(r"by (client|customer)|per (client|customer)|client report|customer report", t) else "monthly_summary"
        args = _scope(t, original, page, today, "last_month", notes)
        args.pop("filters", None) if kind == "receivables" else None
        return Plan("report", [("generate_report", {"kind": kind, **({} if kind == "receivables" else args)})], 0.9, notes)
    if re.search(r"\b(export|download|excel|csv|spreadsheet)\b", t):
        if re.search(r"\bbills?\b|\binvoices?\b", t):
            return Plan("export", [("export_data", {"dataset": "bills", **_scope(t, original, page, today, "all_time", [])})], 0.85)
        entity = _entity(t)
        if entity:
            return Plan("export", [("export_data", {"entity": entity, "format": "csv" if "csv" in t else "xlsx"})], 0.85)

    # --- records and documents ------------------------------------------------------------------------------------
    if re.search(r"\b(expired|expiring|about to expire|lapse|lapsing|expire soon)\b.*\b(documents?|licen[cs]es?|certificates?|insurance|policies)\b|\bdocuments?\b.*\b(expired|expiring|expire)\b", t):
        return Plan("document_alerts", [("get_document_alerts", {})], 0.9)
    if m := re.search(r"\b(?:find|search|look for|show me)\s+documents?\s+(?:about|for|on|named|called|with)\s+(.+)", t):
        return Plan("documents", [("search_documents", {"query": m.group(1).strip(" ?.")[:80]})], 0.82)
    counting = re.search(r"\bhow many\b|\b(number|count|total|no\.?)\s+of\b|^\s*(total|count)\b|\bcount\s*$", t)
    if counting and not _metric(t) and not re.search(r"\b(days?|months?|hours?|times|years?)\b", t):
        entity = _entity(t)
        if entity:
            return Plan("count", [("count_records", {"entity": entity})], 0.9)
    listing = re.match(r"^\s*(?:please\s+)?(?:show|list|give|display|get|see)(?:\s+me)?(?:\s+(?:all|every|each))?(?:\s+(?:of\s+)?(?:the|our|my|us))?\s+([a-z ]{3,30}?)\s*(?:please|today|now|here)?\s*\??$", t)
    if listing and not _metric(t):
        entity = _entity(listing.group(1))
        if entity and not re.search(r"\b(top|biggest|largest|best|bills?|invoices?|expiring|expired|overdue|unpaid)\b", t):
            return Plan("search", [("search_records", {"entity": entity, "query": "", "limit": 10})], 0.85)
    if m := re.search(r"\b(?:find|search for|search|look up|show me|show)\s+(?:the\s+)?(?:a\s+)?([a-z]+)\s+(?:named\s+|called\s+)?(.{2,60})$", original, re.I):
        entity = _entity(m.group(1))
        query = m.group(2).strip(" ?.!")
        if entity and query and query.lower() not in ("records", "list", "all") and not re.search(r"\b(by|per)\b", query, re.I):
            return Plan("search", [("search_records", {"entity": entity, "query": query[:80], "limit": 10})], 0.8)
    if re.search(r"\b(latest|recent|last \d+)\b.*\b(bills?|invoices?)\b|\b(show|list)\b.*\b(bills|invoices)\b", t):
        n = re.search(r"\b(\d{1,2})\b", t)
        return Plan("bills", [("list_bills", {"limit": int(n.group(1)) if n else 10})], 0.85)
    if re.search(r"\b(need|needs|have|still)\s+to\s+be\s+(billed|invoiced)\b|\bto bill\b|\bnot (yet )?billed\b|\bbills? (due|to raise|to be raised)\b|\bwhat (do i|should i) (still )?(need to )?bill\b", t) and not re.search(r"\bclients?\b.*\b(haven'?t|have not)\b", t):
        month = next((s["from"][:7] for s, _l in _find_periods(t, today) if "from" in s), None)
        return Plan("bills_to_raise", [("get_bills_to_raise", {"month": month} if month else {})], 0.88)

    # --- one client's balance ("Is Sunrise School paying on time?", "How much does Acme owe?") ---------------------------
    name = r"((?:[A-Z][\w&.'-]*)(?:\s+(?:[A-Z][\w&.'-]*|\d+))*)"
    owing = (
        re.search(rf"\b(?i:how much (?:does|do|is|has))\s+(?:the\s+)?{name}\s+(?:owe|owing|pending|outstanding|still to pay)", original)
        or re.search(rf"\b(?i:is|are|does|do|has|have)\s+(?:the\s+)?{name}\s+(?i:paying|pay|paid|owe|owing|owes|late|overdue|behind|clear)", original)
        or re.search(rf"\b(?i:what (?:does|do))\s+(?:the\s+)?{name}\s+(?i:owe)", original)
    )
    if owing and owing.group(1).split()[0].lower() not in _SKIP_NAMES and len(owing.group(1)) >= 3:
        return Plan("client_owed", [("get_receivables", {"client": owing.group(1), "limit": 5})], 0.85)
    if names is not None and re.search(r"\b(pay|paying|paid|payment|owe|owes|owing|owed|due|dues|late|overdue|outstanding|balance|unpaid|pending)\b", t):
        known = _names.find_in(original, names)
        if known:
            return Plan("client_owed", [("get_receivables", {"client": known, "limit": 5})], 0.85)

    # --- money owed -------------------------------------------------------------------------------------------
    if re.search(r"\bwho owes\b|\bowe us\b|\bowes us\b|\bunpaid\b|\boverdue\b|\breceivables?\b|\bageing\b|\baging\b|\boutstanding (bills|payments|balance|amount)\b", t) and not re.search(r"\bcompare\b|\bvs\b|\bversus\b", t):
        limit = re.search(r"\btop (\d{1,2})\b", t)
        if re.search(r"\bwho owes\b|\bowes us\b|\bowe us the most\b|\bmost\b|\blargest\b|\bbiggest\b|\btop\b", t):
            return Plan("owed_top", [("get_top_items", {"by": "client", "metric": "outstanding", "limit": int(limit.group(1)) if limit else 10})], 0.9)
        return Plan("receivables", [("get_receivables", {"limit": int(limit.group(1)) if limit else 10})], 0.88)

    # --- what the dashboards say ---------------------------------------------------------------------------------
    if re.search(r"\b(haven'?t|have not|hasn'?t|no)\b.{0,30}\b(billed|purchased|bought|ordered|invoiced)\b|\b(inactive|dormant|lapsed|quiet|gone quiet)\b.{0,20}\b(clients?|customers?)\b|\bwhich (clients?|customers?)\b.{0,30}\b(stopped|not)\b", t):
        m = re.search(r"\b(\d{1,2})\s+months?\b", t)
        return Plan("inactive", [("find_inactive_clients", {"months": int(m.group(1))} if m else {})], 0.88)
    if re.search(r"\b(unusual|anomal\w*|odd|strange|spike|outlier|abnormal|suspicious)\b", t):
        return Plan("anomalies", [("find_anomalies", _scope(t, original, page, today, "last_12_months", notes))], 0.85, notes)
    metric = _metric(t)
    periods_named = _find_periods(t, today)
    if re.search(r"\b(compare|versus|\bvs\.?|difference between|against|changed?|change in|what changed)\b", t) and (metric or re.search(r"\b(month|quarter|year|period)\b", t) or len(periods_named) >= 1):
        base = {k: v for k, v in _scope(t, original, page, today, "this_month", notes).items() if k == "filters"}
        a_spec = periods_named[0][0] if periods_named else {"period": "last_month"}
        b_spec = periods_named[1][0] if len(periods_named) > 1 else None
        if len(periods_named) == 1 and re.search(r"\b(compared? (with|to)|vs\.?|versus|against)\b", t) and re.search(r"\b(previous|prior|before|earlier)\b", t):
            b_spec = None
        if not periods_named:
            notes.append("last month against the month before it")
        args = {"period_a": a_spec, **base}
        if b_spec:
            args["period_b"] = b_spec
        if metric and metric not in SNAPSHOT:
            args["metrics"] = [metric]
        return Plan("compare", [("compare_periods", args)], 0.88, notes)
    if re.search(r"\b(why|reason|cause|what (drove|caused|is behind|happened)|who is responsible|which (clients?|customers?|cases?) (are|is|were|was) (responsible|behind)|biggest (fall|drop|decline|increase|rise|jump))\b", t) and _CHANGE_WORD.search(t):
        key = metric if metric in ("revenue", "billed", "collected", "margin", "payroll", "expenses") else "revenue"
        by = "case" if re.search(r"\bcases?\b|\bsites?\b", t) else "domain" if re.search(r"\bdomains?\b|\bsegments?\b", t) else "client"
        args = {"metric": key, "by": by}
        scope = _scope(t, original, page, today, "last_month", notes)
        if "period" in scope:
            args["period_a"] = {"period": scope["period"]}
        elif "from" in scope or "to" in scope:
            args["period_a"] = {k: scope[k] for k in ("from", "to") if k in scope}
        if scope.get("filters"):
            args["filters"] = {k: v for k, v in scope["filters"].items() if k != {"client": "client", "case": "case", "domain": "business_domain"}[by]}
        return Plan("why", [("explain_change", args)], 0.86, notes)
    if m := re.search(r"\b(?:which|what|who)\b.{0,25}\b(clients?|customers?|accounts?|cases?|sites?)\b.{0,30}\b(bring|brings|earn|earns|make|makes|give|gives|generate|generates|contribute|contributes)\b.{0,15}\b(most|more|the most|best)\b", t):
        by = "case" if m.group(1).startswith(("case", "site")) else "client"
        args = {"by": by, "metric": "revenue", "limit": 5, "order": "highest"}
        scope = _scope(t, original, page, today, "last_12_months", notes)
        scope.pop("filters", None)
        args.update(scope)
        return Plan("top", [("get_top_items", args)], 0.82, notes)
    if m := re.search(r"\bwhich\s+(?:of\s+(?:my|our|the)\s+)?(clients?|customers?|cases?|sites?|domains?|segments?)\s+(?:is|are|was|were)\s+(?:the\s+|our\s+|my\s+)*(biggest|largest|best|top|highest|smallest|lowest|worst)\b", t):
        by = "case" if m.group(1).startswith(("case", "site")) else "domain" if m.group(1).startswith(("domain", "segment")) else "client"
        key = metric if metric in ("revenue", "billed", "collected", "margin", "payroll", "expenses") else "revenue"
        args = {"by": by, "metric": key, "limit": 3, "order": "lowest" if m.group(2) in ("smallest", "lowest", "worst") else "highest"}
        scope = _scope(t, original, page, today, "last_12_months", notes)
        scope.pop("filters", None)
        args.update(scope)
        return Plan("top", [("get_top_items", args)], 0.85, notes)
    if m := re.search(r"\b(top|biggest|largest|best|highest|lowest|smallest|worst|leading)\s*(\d{1,2})?\s*(clients?|customers?|cases?|sites?|domains?|segments?)\b|\b(clients?|customers?|cases?)\b.{0,20}\b(by|ranked by)\s+(revenue|billing|billed|collection|margin|payroll)", t):
        subject = re.search(r"(clients?|customers?|cases?|sites?|domains?|segments?)", m.group(0)).group(1)
        by = "case" if subject.startswith(("case", "site")) else "domain" if subject.startswith(("domain", "segment")) else "client"
        key = metric if metric in ("revenue", "billed", "collected", "margin", "payroll", "expenses") else "revenue"
        number = re.search(r"\b(?:top|biggest|largest|best|highest|lowest|smallest|worst)\s*(\d{1,2})\b", t)
        args = {"by": by, "metric": key, "limit": int(number.group(1)) if number else 10, "order": "lowest" if re.search(r"\b(lowest|smallest|worst)\b", t) else "highest"}
        scope = _scope(t, original, page, today, "last_12_months", notes)
        scope.pop("filters", None)
        args.update(scope)
        return Plan("top", [("get_top_items", args)], 0.9, notes)
    if re.search(r"\b(trend|over time|month by month|month-by-month|each month|monthly|growing|growth|over the (last|past)|history of)\b", t) and metric and metric not in SNAPSHOT:
        args = {"metric": metric, **_scope(t, original, page, today, "last_12_months", notes)}
        return Plan("trend", [("get_trend", args)], 0.88, notes)
    business_word = re.search(r"\b(business|company|dashboard|dashboards|figures|numbers|performance|results|month|quarter|year|week|looking at|everything|view|screen|page|today|so far)\b", t) or page.get("area") == "dashboard"
    about_text = re.search(r"\b(paragraph|text|email|letter|document|contract|article|note|message|sentence|passage|following|below|attached)\b", t)
    if (not re.search(r"\bsummari[sz]e\b|\bsummary\b", t) or (business_word and not about_text)) and re.search(r"\b(summari[sz]e|summary|overview|how (are|is) (we|the business|things)|how('s| is) (it|business) going|status|health|what should i (focus|look)|what needs attention|biggest problems?|key (figures|numbers)|snapshot|performance|worr\w*|anything (wrong|unusual|bad|i should know)|should i (know|be (aware|worried))|red flags?|concerns?|going on with|what('s| is) (happening|new))\b", t):
        return Plan("summary", [("get_business_summary", _scope(t, original, page, today, "last_month", notes))], 0.88, notes)
    if metric and (re.search(r"\b(what|how much|how many|show|tell|give|current|total|our)\b", t) or periods_named or (names is not None and _names.find_in(original, names))) and not re.search(r"\b(why|how to|should|recommend)\b", t):
        args = {"metric": metric}
        if metric not in SNAPSHOT:
            args.update(_scope(t, original, page, today, "last_month", notes))
        else:
            scope = _scope(t, original, page, today, "last_month", [])
            if scope.get("filters"):
                args["filters"] = scope["filters"]
        return Plan("metric", [("get_metric", args)], 0.86, notes)
    return None
