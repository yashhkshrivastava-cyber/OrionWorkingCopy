"""Things worth knowing without having to ask, and what to ask first.

Insights are worked out by rules over the application's real data (the dashboards' own findings, what is overdue, what is
due to be billed, documents about to lapse, reminders that are due). No model is involved, so none can be invented, and
only what is genuinely worth attention is shown: a handful at most, each with the evidence, and a person can dismiss
one for a week. Opening one starts a conversation with the question already asked.
"""

from __future__ import annotations

import logging
import time
from datetime import date
from typing import Any

from app import billing, documents, receivables
from app.ai import periods, store
from app.ai.tools.analytics import _link
from app import bank
from app.auth import can_access_bank, can_access_billing, can_access_documents, can_access_orion_dashboard, can_access_tally_dashboard
from app.dashboard import build_view
from app.dashboard.filters import inr

log = logging.getLogger(__name__)

SEVERITY = {"critical": 0, "warning": 1, "info": 2}
MAX_INSIGHTS = 5
_cache: dict[int, tuple[float, list[dict[str, Any]]]] = {}
CACHE_SECONDS = 600


def _dashboard(today: date) -> list[dict[str, Any]]:
    first = periods._add_months(today.replace(day=1), -3)
    last = periods._month_end(*(lambda d: (d.year, d.month))(periods._add_months(today.replace(day=1), -1)))
    selection = {"from": first.isoformat(), "to": last.isoformat()}
    view = build_view("overview", selection)
    if view["meta"].get("empty"):
        return []
    out = []
    for item in view["insights"]:
        tone = item.get("tone")
        if tone not in ("negative", "warning"):
            continue
        out.append({
            "id": f"dash:{item['id']}",
            "severity": "critical" if tone == "negative" else "warning",
            "headline": item["title"],
            "body": item.get("detail") or "",
            "area": "Dashboard",
            "prompt": f"Investigate this finding and tell me what is behind it: {item['title']}",
            "link": _link(item.get("tab") or "overview", selection),
        })
    return out


def _money(user: dict[str, Any], today: date) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    report = receivables.list_receivables()
    totals = report["totals"]
    old = float(totals["buckets"][-1]) if totals["buckets"] else 0.0
    if old >= 1:
        worst = max(report["clients"], key=lambda c: c["buckets"][-1], default=None)
        out.append({
            "id": "owed:over90", "severity": "warning", "headline": f"{inr(old)} has been unpaid for more than 90 days",
            "body": (f"{worst['client_name']} accounts for {inr(worst['buckets'][-1])} of it." if worst and worst["buckets"][-1] else ""),
            "area": "Receivables", "prompt": "Which clients have bills unpaid for more than 90 days, and what should I do about them?", "link": "/utility/receivables",
        })
    month = billing.default_due_month(today)
    due = billing.list_due_to_bill(month.strftime("%Y-%m"))["cases"]
    if due:
        out.append({
            "id": f"billing:due:{month:%Y-%m}", "severity": "info", "headline": f"{len(due)} case(s) not yet billed for {month:%B %Y}",
            "body": ", ".join(c["case_name"] for c in due[:3]) + (" and more" if len(due) > 3 else ""),
            "area": "Billing", "prompt": f"Which cases still need to be billed for {month:%B %Y}?", "link": "/utility/due",
        })
    return out


def _bank(user: dict[str, Any]) -> list[dict[str, Any]]:
    """The balance against the minimum a person set on an account (nothing is said when none is set)."""
    out = []
    for alert in bank.alerts():
        out.append({
            "id": f"bank:{alert['key']}", "severity": alert["level"], "headline": alert["title"], "body": alert["detail"], "area": "Bank",
            "prompt": "How is the bank balance doing against its minimum, and what is coming in and out over the next two weeks?", "link": "/bank",
        })
    return out


def _documents(user: dict[str, Any]) -> list[dict[str, Any]]:
    ov = documents.overview(documents.can_see_confidential(user))
    out = []
    if ov["expired"]:
        out.append({"id": "docs:expired", "severity": "warning", "headline": f"{ov['expired']} document(s) have expired", "body": ov["expired_documents"][0]["title"] + (" and others" if ov["expired"] > 1 else "") if ov["expired_documents"] else "",
                    "area": "Documents", "prompt": "Which documents have expired, and what do they belong to?", "link": "/documents?view=all&expiry=expired"})
    if ov["expiring"]:
        out.append({"id": "docs:expiring", "severity": "info", "headline": f"{ov['expiring']} document(s) expire soon", "body": ov["expiring_documents"][0]["title"] if ov["expiring_documents"] else "",
                    "area": "Documents", "prompt": "Which documents are about to expire?", "link": "/documents?view=all&expiry=expiring"})
    return out


def _reminders(user: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"id": f"task:{t['id']}", "severity": "info", "headline": f"Reminder: {t['title']}", "body": t.get("note") or "", "area": "Reminder", "prompt": f"Help me with this reminder: {t['title']}",
             "link": t.get("link"), "task_id": t["id"]} for t in store.due_tasks(user["id"])]


def compute(user: dict[str, Any], *, fresh: bool = False) -> list[dict[str, Any]]:
    """The few insights worth showing this person now, most important first."""
    settings = store.get_settings(user["id"])
    if not settings["show_insights"]:
        return []
    now = time.monotonic()
    cached = _cache.get(user["id"])
    if cached and not fresh and now - cached[0] < CACHE_SECONDS:
        items = cached[1]
    else:
        today = date.today()
        items = []
        for work in (
            (lambda: _dashboard(today)) if can_access_orion_dashboard(user) else None,
            (lambda: _money(user, today)) if can_access_billing(user) else None,
            (lambda: _documents(user)) if can_access_documents(user) else None,
            (lambda: _bank(user)) if can_access_bank(user) else None,
        ):
            if work is None:
                continue
            try:
                items += work()
            except Exception:  # noqa: BLE001 - one source being down must not hide the rest
                log.exception("Could not compute an AI insight")
        _cache[user["id"]] = (now, items)
    hidden = store.hidden_insights(user["id"])
    try:
        reminders = _reminders(user)
    except Exception:  # noqa: BLE001
        log.exception("Could not read due reminders")
        reminders = []
    visible = [i for i in [*reminders, *items] if i["id"] not in hidden]
    visible.sort(key=lambda i: SEVERITY.get(i["severity"], 3))
    return visible[:MAX_INSIGHTS]


def forget(user_id: int) -> None:
    _cache.pop(user_id, None)


# ------------------------------------------------------------------------------------------------ suggestions

_BY_VIEW = {
    "overview": ["Summarize this dashboard", "What changed compared with last month?", "Show me the biggest problems", "What should I focus on?"],
    "revenue": ["Why did revenue change compared with last month?", "Who are my top 10 clients?", "Which clients haven't been billed recently?", "Show revenue over the last 12 months"],
    "collections": ["Who owes us the most?", "What is overdue?", "How has collection changed compared with last month?", "Create a receivables report"],
    "profitability": ["Which cases cost more than they bill?", "Explain the margin trend", "Compare this quarter with last quarter"],
    "people": ["How is payroll changing?", "Compare payroll with last month", "What is unusual in the people figures?"],
    "pipeline": ["How many opportunities are open?", "What is our win rate?", "Summarize the pipeline"],
    "fleet": ["How much did the fleet cost last month?", "Is cost per km changing?"],
    "controls": ["What needs checking in the controls?", "Are there cancelled or edited bills to look at?"],
}
_TALLY_BY_VIEW = {
    "overview": ["How is billing in the Tally books?", "Who are our top clients in Tally?", "Where does the income come from in Tally?"],
    "billing": ["Compare billing this quarter with last quarter in Tally", "How many invoices did Tally bill last month?"],
    "credit-notes": ["How many credit notes did we issue this year?", "Which clients got the most credit notes?"],
    "income": ["How much is manpower against vehicle rent in Tally?", "Where does the income come from in Tally?"],
    "clients": ["What do the Sundry Debtors show?", "Who are our top clients in Tally?"],
    "books": ["What do the books say about GST payable?", "How much cash do the books show?"],
}
_GENERAL = ["How are we doing this month?", "What changed compared with last month?", "Show me the biggest problems", "What should I focus on?", "Which customers haven't been billed recently?"]


def suggestions(user: dict[str, Any], page: dict[str, Any]) -> list[str]:
    """Starter questions for where the person is, limited to what they are allowed to ask about."""
    out: list[str] = []
    area = page.get("area")
    if area == "dashboard" and can_access_orion_dashboard(user):
        if page.get("filters"):
            out.append("Summarize everything I'm looking at")
        out += _BY_VIEW.get(page.get("view") or "overview", _BY_VIEW["overview"])
    elif area == "dashboard_tally" and can_access_tally_dashboard(user):
        if page.get("filters"):
            out.append("Summarize what I'm looking at in Tally")
        out += _TALLY_BY_VIEW.get(page.get("view") or "overview", _TALLY_BY_VIEW["overview"])
    elif area == "billing" and can_access_billing(user):
        out += ["Who owes us the most?", "Which cases still need to be billed this month?", "Show the latest bills", "Create a receivables report"]
    elif area == "documents" and can_access_documents(user):
        out += ["Which documents have expired?", "What is expiring soon?", "Find documents about insurance"]
    elif area == "data":
        out += ["How many clients and cases do we have?", "Find a client by name", "Show the latest opportunities"]
    if can_access_orion_dashboard(user):
        out += _GENERAL
    elif can_access_billing(user):
        out += ["Who owes us the most?", "Which cases still need to be billed?"]
    out += ["Set a reminder for me", "What are my reminders?"]
    seen: list[str] = []
    for item in out:
        if item not in seen:
            seen.append(item)
    return seen[:6]
