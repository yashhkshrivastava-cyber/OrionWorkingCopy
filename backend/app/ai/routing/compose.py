"""Writing the application's own answers from what the tools returned.

Every number in these sentences is copied from a tool's result (the same results a model would have been given), so it cannot
be wrong in a way the data is not. Blocks (tables, charts, cards) are placed with the same ``{{block:ID}}`` markers a model
uses, so the screen draws them the same way.
"""

from __future__ import annotations

import calendar
import re
from datetime import datetime
from typing import Any

from app.ai.tools.analytics import fmt
from app.ai.tools.core import Outcome


def _blocks(data: Any, limit: int = 3) -> list[str]:
    ids = [b["id"] for b in (data or {}).get("blocks", []) if isinstance(b, dict) and b.get("id")]
    return ["{{block:%s}}" % i for i in ids[:limit]]


def _signed(pct: Any) -> str:
    return f"{pct:+.1f}%" if isinstance(pct, (int, float)) else ""


def _cap(text: str) -> str:
    return text[:1].upper() + text[1:]


def _name(label: str | None) -> str:
    """A comparison label as a phrase: "vs prior 30 days" becomes "the prior 30 days"."""
    text = re.sub(r"^vs\.?\s+", "", label or "").strip()
    return f"the {text}" if text.startswith(("prior", "previous", "same", "last")) else text


def _move(item: dict[str, Any], compared: str | None) -> str:
    """How a figure moved: "-21.4% on ₹24.6 L in August 2026". Without a percentage (it was nothing before) it says what it was."""
    before = item.get("previous_display")
    where = f" in {_name(compared)}" if compared else ""
    if item.get("change_pct") is not None:
        return f"{_signed(item['change_pct'])} on {before}{where}" if before else _signed(item["change_pct"])
    if before is not None and compared:
        return f"was {before}{where}"
    return ""


def _month(code: str) -> str:
    m = re.fullmatch(r"(\d{4})-(\d{2})", code or "")
    return f"{calendar.month_abbr[int(m.group(2))]} {m.group(1)}" if m else code


def _when(value: str | None) -> str:
    try:
        moment = datetime.fromisoformat(value) if value else None
    except ValueError:
        return value or ""
    if moment is None:
        return ""
    clock = moment.strftime("%I:%M %p").lstrip("0").lower()
    return f"{moment.day} {calendar.month_abbr[moment.month]}" + (f", {clock}" if (moment.hour, moment.minute) != (0, 0) else "")


def _plain_number(value: float) -> str:
    """15,36,000 style grouping, with decimals only when there are some."""
    negative, value = value < 0, abs(value)
    whole, _dot, fraction = f"{value:.4f}".rstrip("0").partition(".")
    head, tail = whole[:-3], whole[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    text = ",".join(groups + [tail]) if groups else tail
    return ("-" if negative else "") + text + (f".{fraction}" if fraction else "")


def _notes(data: Any) -> list[str]:
    seen: list[str] = []
    for note in [*(data or {}).get("notes", []), *(data or {}).get("filter_notes", [])]:
        if note and note not in seen and not note.startswith("The warehouse has data through"):
            seen.append(note)
    return [f"_{n}_" for n in seen[:2]]


# ------------------------------------------------------------------------------------------------ one per tool


def business_summary(d: dict[str, Any]) -> list[str]:
    head = {h["metric"]: h for h in d.get("headline", [])}
    compared = d.get("compared_with")
    lines = [f"**{_cap(d['period'])}**" + (f", set against {_name(compared)}:" if compared else ":")]
    for key in ("revenue", "collected", "margin", "payroll", "expenses"):
        item = head.get(key)
        if item and item.get("value") is not None:
            moved = _move(item, compared)
            lines.append(f"- {item['label']}: **{item['display']}**" + (f" ({moved})" if moved else ""))
    owed = d.get("receivables_now") or {}
    if owed.get("outstanding", {}).get("value"):
        over = owed.get("overdue_over_90_days", {})
        lines.append(f"- Owed to you now: **{owed['outstanding']['display']}**" + (f", of which **{over['display']}** is more than 90 days old" if over.get("value") else ""))
    findings = [f for f in d.get("dashboard_findings", []) if f.get("title")][:3]
    if findings:
        lines += ["", "What the dashboard flags:"]
        lines += [f"- {f['title']}" + (f". {f['detail']}" if f.get("detail") else "") for f in findings]
    return lines


def metric(d: dict[str, Any]) -> list[str]:
    line = f"**{d['label']}** for {d['period']}: **{d['display']}**"
    moved = _move(d, d.get("compared_with"))
    return [line + (f" ({moved})" if moved else "") + "."]


def compare(d: dict[str, Any]) -> list[str]:
    a, b = d["period_a"]["label"], d["period_b"]["label"]
    lines = [f"**{_cap(a)}** compared with **{b}**:"]
    for row in d["comparison"][:8]:
        change = _signed(row.get("change_pct")) or (row.get("change_display") if row.get("change_display") not in (None, row.get(a)) else "")
        lines.append(f"- {row['label']}: {row.get(a, '–')} against {row.get(b, '–')}" + (f" ({change})" if change else ""))
    return lines


def explain(d: dict[str, Any]) -> list[str]:
    unit = d.get("unit", "inr")
    change = d.get("total_change") or 0
    verb = "fell" if change < 0 else "rose" if change > 0 else "did not change"
    head = f"**{d['metric']}** {verb}"
    if change:
        head += f" by **{d['total_change_display'].lstrip('+-')}**" + (f" ({_signed(d['total_change_pct'])})" if d.get("total_change_pct") is not None else "")
    head += f", from {fmt(d.get('total_before'), unit)} in {d['period_b']} to {fmt(d.get('total_now'), unit)} in {d['period_a']}."
    lines = [head]
    movers = d["biggest_decreases"] if change < 0 else d["biggest_increases"]
    if movers:
        lines.append(f"The biggest {'falls' if change < 0 else 'rises'} by {d['by']}:")
        for m in movers[:3]:
            share = f", {abs(m['share_of_total_change_pct']):.0f}% of the total change" if m.get("share_of_total_change_pct") is not None else ""
            tag = " (billed nothing this time)" if m.get("status") == "stopped" else " (new)" if m.get("status") == "new" else ""
            lines.append(f"- {m['name']}: {'-' if m['change'] < 0 else '+'}{fmt(abs(m['change']), unit)}{share}{tag}")
        if d.get("top_contributors_explain_pct_of_change") is not None:
            lines.append(f"Together these account for about {abs(d['top_contributors_explain_pct_of_change']):.0f}% of the change.")
    else:
        lines.append(f"No {d['by']} moved by a meaningful amount.")
    return lines


def top(d: dict[str, Any]) -> list[str]:
    items = d["items"]
    if not items:
        return ["I couldn't find data matching that request."]
    unit = d.get("unit", "inr")
    lines = [f"**{len(items)} {d['by']}{'s' if len(items) != 1 else ''} by {d['metric'].lower()}**, {d['period']}:"]
    for i, item in enumerate(items[:10], 1):
        extra = f" ({item['share_pct']:.1f}% of the total)" if item.get("share_pct") is not None else (f", oldest {item['oldest_days']} days" if item.get("oldest_days") else "")
        lines.append(f"{i}. {item['name']}: **{fmt(item['value'], unit)}**{extra}")
    return lines


def trend(d: dict[str, Any]) -> list[str]:
    ch = d.get("change_first_to_latest") or {}
    lines = [
        f"**{d['metric']}**, {d['period']}: latest **{d['latest']['display']}** ({_month(d['latest']['month'])}), highest {d['highest']['display']} ({_month(d['highest']['month'])}), "
        f"lowest {d['lowest']['display']} ({_month(d['lowest']['month'])}), average {d['average_display']}."
    ]
    if ch.get("change_pct") is not None:
        lines.append(f"From {_month(d['first']['month'])} to {_month(d['latest']['month'])} it moved {_signed(ch['change_pct'])}.")
    return lines


def anomalies(d: dict[str, Any]) -> list[str]:
    found = d.get("unusual_months", [])
    if not found:
        return [f"Nothing stands out as unusual in {d['period']}."]
    lines = [f"**{len(found)} unusual month{'s' if len(found) != 1 else ''}** in {d['period']}:"]
    for u in found[:6]:
        lines.append(f"- {u['metric']}, {_month(u['month'])}: {u['display']} against about {u['usual_display']} usually ({u['deviation_pct']:+.0f}%)")
    return lines


def one_client_owes(d: dict[str, Any], asked: str) -> list[str]:
    clients = d.get("clients", [])
    if not clients:
        return [f"Nothing is outstanding for {asked}, or I couldn't find a client by that name."]
    c = clients[0]
    ages = ", ".join(f"{label}: {fmt(value, 'inr')}" for label, value in c.get("by_age", {}).items() if value)
    line = f"**{c['client']}** owes **{fmt(c['total_owed'], 'inr')}** across {c['unpaid_bills']} unpaid bill{'s' if c['unpaid_bills'] != 1 else ''}; the oldest is {c['oldest_days']} days old."
    out = [line]
    if ages:
        out.append(f"By age: {ages}.")
    if c.get("last_reminder"):
        out.append(f"The last reminder went on {c['last_reminder']}.")
    return out


def receivables(d: dict[str, Any]) -> list[str]:
    totals = d["totals"]
    if not totals.get("bills"):
        return ["Nothing is outstanding."]
    lines = [f"**{fmt(totals['total'], 'inr')}** is owed across {totals['bills']} unpaid bill{'s' if totals['bills'] != 1 else ''} (as of {d['as_of']})."]
    buckets, figures = d.get("ageing_buckets", []), totals.get("buckets", [])
    if buckets and figures:
        lines.append("By age: " + ", ".join(f"{label}: {fmt(value, 'inr')}" for label, value in zip(buckets, figures)) + ".")
    for c in d.get("clients", [])[:3]:
        lines.append(f"- {c['client']}: {fmt(c['total_owed'], 'inr')}, oldest {c['oldest_days']} days")
    return lines


def bills(d: dict[str, Any]) -> list[str]:
    rows = d["bills"]
    if not rows:
        return ["I couldn't find data matching that request."]
    return [f"Here are the {len(rows)} most recent bill{'s' if len(rows) != 1 else ''}."]


def to_raise(d: dict[str, Any]) -> list[str]:
    cases = d["cases"]
    month = _month(d["service_month"][:7])
    if not cases:
        return [f"Every case that was billed before has a bill for {month}."]
    names = ", ".join(c["case"] for c in cases[:4]) + (" and more" if len(cases) > 4 else "")
    return [f"**{len(cases)} case{'s' if len(cases) != 1 else ''}** still to be billed for {month}: {names}."]


def inactive(d: dict[str, Any]) -> list[str]:
    clients = d["clients"]
    if not clients:
        return [f"Every client billed before has been billed in the last {d['months']} months."]
    names = ", ".join(c["name"] for c in clients[:4]) + (" and others" if len(clients) > 4 else "")
    return [f"**{d['count']} client{'s' if d['count'] != 1 else ''}** that billed before have had nothing billed in the last {d['months']} months: {names}."]


def documents(d: dict[str, Any]) -> list[str]:
    if "expired_count" in d:
        return [f"**{d['expired_count']}** document{'s' if d['expired_count'] != 1 else ''} expired and **{d['expiring_count']}** expire soon (of {d['documents_total']})."]
    return [f"Found **{d.get('total_matching', 0)}** matching document{'s' if d.get('total_matching') != 1 else ''}."]


def count(d: dict[str, Any]) -> list[str]:
    word = d["record_type"].lower()
    if d.get("matching") is not None and d["matching"] != d["total"]:
        return [f"**{d['matching']}** {word} record{'s' if d['matching'] != 1 else ''} match, of {d['total']} in all."]
    return [f"There {'is' if d['total'] == 1 else 'are'} **{d['total']}** {word} record{'s' if d['total'] != 1 else ''}."]


def reminders(d: dict[str, Any]) -> list[str]:
    items = d["open"]
    if not items:
        return ["You have no open reminders or tasks."]
    return [f"You have **{len(items)}** open:"] + [f"- {i['title']}" + (f" ({_when(i['due'])})" if i.get("due") else "") for i in items[:8]]


# ---------------------------------------------------------------------------------------------------- the Tally books


def tally_summary(d: dict[str, Any]) -> list[str]:
    head = {h["metric"]: h for h in d.get("headline", [])}
    compared = d.get("compared_with")
    lines = [f"**{_cap(d['period'])}** in the Tally books" + (f", set against {_name(compared)}:" if compared else ":")]
    for key in ("billed", "revenue", "gst", "invoices", "clients", "credit_notes"):
        item = head.get(key)
        if item and item.get("value") is not None:
            moved = _move(item, compared)
            lines.append(f"- {item['label']}: **{item['display']}**" + (f" ({moved})" if moved else ""))
    top = d.get("top_clients") or []
    if top:
        share = top[0].get("share_pct")
        lines.append(f"- Largest client: **{top[0]['client']}**" + (f", {share:.0f}% of revenue" if share is not None else ""))
    debtors = d.get("sundry_debtors_now") or {}
    if debtors.get("closing_balance"):
        lines.append(f"- Sundry Debtors closing balance: **{debtors['display']}** (Tally shows debit balances as negative)")
    findings = [f for f in d.get("dashboard_findings", []) if f.get("title")][:3]
    if findings:
        lines += ["", "What the Tally dashboard flags:"]
        lines += [f"- {f['title']}" + (f". {f['detail']}" if f.get("detail") else "") for f in findings]
    return lines


def tally_metric(d: dict[str, Any]) -> list[str]:
    line = f"**{d['label']}** in the Tally books for {d['period']}: **{d['display']}**"
    moved = _move(d, d.get("compared_with"))
    return [line + (f" ({moved})" if moved else "") + "."]


def tally_compare(d: dict[str, Any]) -> list[str]:
    a, b = d["period_a"]["label"], d["period_b"]["label"]
    lines = [f"**{_cap(a)}** compared with **{b}**, in the Tally books:"]
    for row in d["comparison"][:8]:
        moved = _signed(row.get("change_pct")) or (row.get("change_display") or "")
        lines.append(f"- {row['label']}: {row['a_display']} against {row['b_display']}" + (f" ({moved})" if moved else ""))
    return lines


def tally_top_clients(d: dict[str, Any]) -> list[str]:
    items = d["clients"]
    if not items:
        return [f"Nothing was billed in the Tally books for {d['period']}."]
    word = "revenue" if d["ranked_by"] == "revenue" else "amount billed"
    lines = [f"**Top {len(items)} client{'s' if len(items) != 1 else ''} by {word}** in the Tally books for {d['period']} (of {d['total_display']}):"]
    for r in items[:5]:
        value = r["revenue"] if d["ranked_by"] == "revenue" else r["billed"]
        lines.append(f"{r['rank']}. {r['client']}: **{fmt(value, 'inr')}**" + (f" ({r['share_pct']:.0f}%)" if r.get("share_pct") is not None else ""))
    if d.get("top_three_share_pct") is not None:
        lines.append(f"The top three are {d['top_three_share_pct']:.0f}% of the total.")
    return lines


def tally_income(d: dict[str, Any]) -> list[str]:
    groups = d["by_line"]
    if not groups:
        return [f"No income lines were found in the Tally books for {d['period']}."]
    lines = [f"**Income by line** in the Tally books for {d['period']}, **{d['total_display']}** in all:"]
    lines += [f"- {g['line']}: **{g['display']}**" + (f" ({g['share_pct']:.0f}%)" if g.get("share_pct") is not None else "") for g in groups[:6]]
    return lines


def tally_debtors(d: dict[str, Any]) -> list[str]:
    lines = [f"**Sundry Debtors** in the Tally books close at **{d['total_display']}** across {d['debtor_ledgers']} ledgers, as at the last warehouse load. Tally shows debit balances as negative; this is not aged receivables."]
    big = d.get("largest") or []
    if big:
        lines += ["", "Largest balances:"] + [f"- {r['client']}: **{r['closing_display']}**" for r in big[:5]]
    return lines


def tally_credit_notes(d: dict[str, Any]) -> list[str]:
    cn, dn, rate = d["credit_notes"], d["debit_notes"], d["credit_note_rate"]
    lines = [f"In the Tally books for {d['period']}: **{d['credit_note_count']}** credit note{'s' if d['credit_note_count'] != 1 else ''} worth **{cn['display']}**"
             + (f" ({rate['display']} of sales)" if rate.get("value") is not None else "") + f", and **{d['debit_note_count']}** debit note{'s' if d['debit_note_count'] != 1 else ''} worth **{dn['display']}**."]
    top = d.get("most_credited_clients") or []
    if top:
        lines += ["", "Most credited:"] + [f"- {r['client']}: **{fmt(r['credited'], 'inr')}**" for r in top[:3]]
    return lines


def tally_books(d: dict[str, Any]) -> list[str]:
    lines = ["**Closing balances in the Tally books**, as at the last warehouse load:"]
    held = [b for b in [*d["balances"], *d.get("other_balances", [])] if b.get("closing")]
    nil = [b["balance"] for b in d["balances"] if not b.get("closing")]
    lines += [f"- {b['balance']}: **{b['display']}**" for b in held]
    if not held:
        lines.append("- Every balance is nil at the last load.")
    elif nil:
        lines.append(f"- Nil: {', '.join(nil)}.")
    lines.append("_Signs are as Tally stores them (debit balances negative). These are different kinds of balance and are not added together._")
    return lines



COMPOSERS = {
    "get_business_summary": business_summary, "get_metric": metric, "compare_periods": compare, "explain_change": explain, "get_top_items": top,
    "get_trend": trend, "find_anomalies": anomalies, "get_receivables": receivables, "list_bills": bills, "get_bills_to_raise": to_raise,
    "find_inactive_clients": inactive, "get_document_alerts": documents, "search_documents": documents, "count_records": count, "get_reminders": reminders,
    "get_tally_summary": tally_summary, "get_tally_metric": tally_metric, "compare_tally_periods": tally_compare, "get_tally_top_clients": tally_top_clients,
    "get_tally_income_mix": tally_income, "get_tally_debtors": tally_debtors, "get_tally_credit_notes": tally_credit_notes, "get_tally_books_position": tally_books,
}
# These already say everything the data's notes would add.
QUIET = {"find_inactive_clients", "get_bills_to_raise", "get_reminders", "count_records", "get_tally_debtors", "get_tally_books_position"}


def answer(outcomes: list[Outcome], notes: list[str] | None = None) -> str:
    """The whole answer for a set of tool results, as markdown with block markers."""
    out: list[str] = []
    for o in outcomes:
        if o.pending:
            out.append("I've prepared that. It is waiting for your confirmation below; nothing changes until you confirm.")
            continue
        if not o.ok:
            out.append("You don't have access to that." if o.refused else (o.summary or "I couldn't do that."))
            continue
        data = o.data if isinstance(o.data, dict) else {}
        if o.tool == "calculate":
            out.append(f"**{_plain_number(float(data.get('result', 0)))}**")
            continue
        composer = COMPOSERS.get(o.tool)
        if o.tool == "get_receivables" and o.args.get("client"):
            out += one_client_owes(data, o.args["client"])
        elif composer:
            try:
                out += composer(data)
            except (KeyError, TypeError, ValueError):
                out.append(o.summary or "Done.")
        elif o.tool == "create_reminder_or_task":
            made = data.get("created", {})
            out.append(f"Done. I've set a {made.get('kind', 'reminder')}: **{made.get('title', '')}**" + (f", due {_when(made['due'])}" if made.get("due") else "") + ".")
        elif o.tool in ("export_data", "generate_report"):
            out.append("Here it is. It stays available to download for two days.")
        elif o.tool == "open_page":
            out.append(f"Opening {data.get('opened', 'the page')}.")
        elif o.tool == "set_appearance":
            out.append("Done. I've changed how the workspace looks for you.")
        else:
            out.append(o.summary or "Done.")
        if o.tool not in QUIET:
            out += _notes(data)
        out += _blocks(data)
    if notes:
        out.append(f"_I used {'; '.join(notes)}._")
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip() or "I couldn't find data matching that request."
