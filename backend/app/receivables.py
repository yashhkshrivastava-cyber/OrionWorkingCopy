"""What clients owe, how old it is, and sending bills and reminders to them.

A bill is owed from its bill date until it is paid. Its balance is the grand total less the
Committed revenue entries billing.py keeps for it (``received_total``), so this module reads
the same figures the Bills register shows and never works out money of its own.

Only bills tagged to a case count. A bill raised before bills were tagged to cases has no
revenue entries, so there is no record of whether it was paid; those are counted and left out
rather than reported as owed.

Every email or WhatsApp message sent from here is recorded in ``orion_ods.bill_message``.
That record gives "last reminded" on the Outstanding page and the address or number to
start the next message with.
"""

from __future__ import annotations

import logging
import re
from datetime import date
from decimal import Decimal
from typing import Any
from urllib.parse import quote

from app import billing
from app.billing_pdf import day, indian, invoice_pdf, month, statement_pdf
from app.config import env
from app.database import db_cursor
from app.mail import send_mail

logger = logging.getLogger(__name__)

# (first day, last day or None, label). The age is counted from the bill date.
BUCKETS: tuple[tuple[int, int | None, str], ...] = (
    (0, 30, "0–30 days"),
    (31, 60, "31–60 days"),
    (61, 90, "61–90 days"),
    (91, None, "Over 90 days"),
)
ZERO = Decimal("0")
_EMAIL = re.compile(r"^[^@\s,;]+@[^@\s,;]+\.[^@\s,;]+$")
MAX_RECIPIENTS = 5


class ShareError(ValueError):
    """The message cannot be sent. The text is safe to show to the user."""


# --------------------------------------------------------------------------- ageing


def bucket_index(days: int) -> int:
    for index, (low, high, _label) in enumerate(BUCKETS):
        if days >= low and (high is None or days <= high):
            return index
    return 0


def _money(value: Decimal) -> float:
    return float(value)


def build_receivables(rows: list[dict[str, Any]], as_of: date) -> dict[str, Any]:
    """Group unpaid bills by client and sort each one into an age bucket.

    ``rows`` are issued, case-tagged bills with ``grand_total`` and ``received``. A bill that
    is paid in full is left out. A bill dated after ``as_of`` counts as 0 days old.
    """
    clients: dict[str, dict[str, Any]] = {}
    for row in rows:
        balance = Decimal(str(row["grand_total"])) - Decimal(str(row.get("credited") or 0)) - Decimal(str(row["received"]))
        if balance <= 0:
            continue
        days = max((as_of - row["bill_date"]).days, 0)
        bucket = bucket_index(days)
        entry = clients.setdefault(
            row["client_code"],
            {
                "client_code": row["client_code"],
                "client_name": row["client_name"],
                "billing_name": row.get("billing_name"),
                "total": ZERO,
                "buckets": [ZERO] * len(BUCKETS),
                "bills": [],
                "last_reminder": None,
            },
        )
        entry["total"] += balance
        entry["buckets"][bucket] += balance
        reminded = row.get("last_reminder")
        if reminded and (entry["last_reminder"] is None or reminded > entry["last_reminder"]):
            entry["last_reminder"] = reminded
        entry["bills"].append(
            {
                "id": row["id"],
                "bill_number": row["bill_number"],
                "bill_date": row["bill_date"].isoformat(),
                "service_month": row["service_month"].isoformat(),
                "case_code": row["case_code"],
                "case_name": row["case_name"],
                "location": row.get("location"),
                "grand_total": _money(Decimal(str(row["grand_total"]))),
                "received": _money(Decimal(str(row["received"]))),
                "credited": _money(Decimal(str(row.get("credited") or 0))),
                "balance": _money(balance),
                "days": days,
                "bucket": bucket,
                "last_reminder": reminded.isoformat() if reminded else None,
                "reminders": row.get("reminders") or 0,
            }
        )

    out = []
    totals = [ZERO] * len(BUCKETS)
    for entry in clients.values():
        entry["bills"].sort(key=lambda bill: (bill["bill_date"], bill["bill_number"]))
        for index, value in enumerate(entry["buckets"]):
            totals[index] += value
        out.append(
            {
                **entry,
                "total": _money(entry["total"]),
                "buckets": [_money(value) for value in entry["buckets"]],
                "oldest_days": max(bill["days"] for bill in entry["bills"]),
                "last_reminder": entry["last_reminder"].isoformat() if entry["last_reminder"] else None,
            }
        )
    out.sort(key=lambda entry: (-entry["total"], entry["client_name"] or ""))
    return {
        "as_of": as_of.isoformat(),
        "bucket_labels": [label for _low, _high, label in BUCKETS],
        "clients": out,
        "totals": {
            "total": _money(sum(totals, ZERO)),
            "buckets": [_money(value) for value in totals],
            "clients": len(out),
            "bills": sum(len(entry["bills"]) for entry in out),
        },
    }


def list_receivables(as_of: date | None = None) -> dict[str, Any]:
    as_of = as_of or date.today()
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT b.bill_code AS id, b.bill_number, b.bill_date, b.service_month, b.grand_total,
                   b.case_code, cs.case_name, b.client_code, cl.client_name,
                   NULLIF(BTRIM(cl.billing_name), '') AS billing_name, b.location,
                   COALESCE((
                       SELECT SUM(t.amount_after_tax_gst) FROM orion_ods.case_transaction t
                        WHERE t.bill_code = b.bill_code AND t.transaction_status = 'Committed'
                   ), 0) AS received,
                   b.credited_amount AS credited,
                   (SELECT MAX(m.sent_timestamp) FROM orion_ods.bill_message m
                     WHERE m.kind = 'reminder' AND b.bill_code = ANY(m.bill_codes)) AS last_reminder,
                   (SELECT COUNT(*) FROM orion_ods.bill_message m
                     WHERE m.kind = 'reminder' AND b.bill_code = ANY(m.bill_codes)) AS reminders
              FROM orion_ods.bill b
              JOIN orion_ods.case cs ON cs.case_code = b.case_code
              JOIN orion_ods.client cl ON cl.client_code = b.client_code
             WHERE b.status = 'Issued'
             ORDER BY b.bill_date, b.bill_seq
            """
        )
        columns = [col.name for col in cur.description]
        rows = [dict(zip(columns, row)) for row in cur.fetchall()]
        cur.execute("SELECT COUNT(*) FROM orion_ods.bill WHERE status = 'Issued' AND case_code IS NULL")
        untagged = cur.fetchone()[0]
    report = build_receivables(rows, as_of)
    report["untagged_bills"] = untagged
    return report


def client_statement(client_code: str, as_of: date | None = None) -> dict[str, Any] | None:
    """One client's entry of the receivables report, with what the statement needs to print."""
    report = list_receivables(as_of)
    for entry in report["clients"]:
        if entry["client_code"] == client_code:
            return {**entry, "as_of": report["as_of"], "bucket_labels": report["bucket_labels"]}
    return None


# --------------------------------------------------------------------------- contacts and history


def email_enabled() -> bool:
    return bool(env("ORION_SMTP_HOST").strip())


def last_contact(client_code: str | None) -> dict[str, str | None]:
    """The email address and WhatsApp number last used for this client."""
    found: dict[str, str | None] = {"email": None, "phone": None}
    if not client_code:
        return found
    with db_cursor() as cur:
        for channel, key in (("email", "email"), ("whatsapp", "phone")):
            cur.execute(
                """
                SELECT recipient FROM orion_ods.bill_message
                 WHERE client_code = %s AND channel = %s
                 ORDER BY sent_timestamp DESC, id DESC LIMIT 1
                """,
                (client_code, channel),
            )
            row = cur.fetchone()
            found[key] = row[0] if row else None
    return found


def history(client_code: str | None, bill_code: str | None = None, limit: int = 5) -> list[dict[str, Any]]:
    """The latest messages sent to a client, or about one bill."""
    if not client_code:
        return []
    where, params = "m.client_code = %s", [client_code]
    if bill_code:
        where += " AND %s = ANY(m.bill_codes)"
        params.append(bill_code)
    with db_cursor() as cur:
        cur.execute(
            f"""
            SELECT m.kind, m.channel, m.recipient, m.sent_timestamp, u.display_name AS sent_by
              FROM orion_ods.bill_message m
              LEFT JOIN orion_ods.app_user u ON u.id = m.sent_by
             WHERE {where}
             ORDER BY m.sent_timestamp DESC, m.id DESC
             LIMIT %s
            """,
            [*params, limit],
        )
        return [{col.name: billing._plain(value) for col, value in zip(cur.description, row)} for row in cur.fetchall()]


def _log(kind: str, channel: str, client_code: str | None, bill_codes: list[str], recipient: str, subject: str | None,
         outstanding: Decimal | None, user_id: int | None) -> None:
    """Record a message that was sent. A failure here must not undo a message that already went."""
    try:
        with db_cursor(commit=True) as cur:
            cur.execute(
                """
                INSERT INTO orion_ods.bill_message
                    (kind, channel, client_code, bill_codes, recipient, subject, outstanding_total, sent_by)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (kind, channel, client_code, bill_codes, recipient, subject, outstanding, user_id),
            )
    except Exception:
        logger.exception("Could not record the %s %s that was sent to %s", channel, kind, recipient)


# --------------------------------------------------------------------------- recipients


def parse_emails(value: Any) -> str:
    """Up to five addresses separated by commas or semicolons, returned as one header value."""
    parts = [part.strip() for part in re.split(r"[,;\s]+", str(value or "")) if part.strip()]
    if not parts:
        raise ShareError("Enter the email address to send it to.")
    if len(parts) > MAX_RECIPIENTS:
        raise ShareError(f"Send to at most {MAX_RECIPIENTS} addresses at a time.")
    for part in parts:
        if not _EMAIL.match(part):
            raise ShareError(f"“{part}” is not a valid email address.")
    return ", ".join(parts)


def whatsapp_number(value: Any) -> str:
    """Digits with the country code. A ten-digit Indian mobile number gets 91 in front."""
    digits = re.sub(r"\D", "", str(value or ""))
    digits = digits.lstrip("0") if len(digits) == 11 and digits.startswith("0") else digits
    if len(digits) == 10:
        digits = "91" + digits
    if not 11 <= len(digits) <= 15:
        raise ShareError("Enter the WhatsApp number with its country code, for example 98765 43210 or +91 98765 43210.")
    return digits


def whatsapp_url(phone: str, text: str) -> str:
    return f"https://wa.me/{phone}?text={quote(text)}"


# --------------------------------------------------------------------------- wording


def _rupees(value: Any) -> str:
    return f"₹{indian(value)}"


def _bank_lines(profile: dict[str, Any]) -> list[str]:
    if not (profile.get("bank_name") or profile.get("bank_account")):
        return []
    return [
        "",
        "Bank details:",
        f"{profile.get('bank_name', '')}, A/c No. {profile.get('bank_account', '')}, IFSC {profile.get('bank_ifsc', '')}",
    ]


def invoice_subject(bill: dict[str, Any], profile: dict[str, Any]) -> str:
    return f"Tax invoice {bill['bill_number']} for {month(bill['service_month'])} - {profile.get('company_name', '')}".strip(" -")


def invoice_message(bill: dict[str, Any], profile: dict[str, Any]) -> str:
    where = f" ({bill['location']})" if bill.get("location") else ""
    lines = [
        f"Dear {bill['party_name']},",
        "",
        f"Please find attached our tax invoice {bill['bill_number']} dated {day(bill['bill_date'])} "
        f"for {month(bill['service_month'])}{where}, for {_rupees(bill['grand_total'])}.",
        *_bank_lines(profile),
        "",
        "Kindly arrange the payment at the earliest and let us know once it is made.",
        "",
        "Regards,",
        profile.get("company_name", ""),
    ]
    return "\n".join(lines)


def reminder_subject(statement: dict[str, Any], profile: dict[str, Any]) -> str:
    return f"Payment reminder: {_rupees(statement['total'])} outstanding as on {day(statement['as_of'])} - {profile.get('company_name', '')}".strip(" -")


def reminder_message(statement: dict[str, Any], profile: dict[str, Any]) -> str:
    name = statement.get("billing_name") or statement["client_name"]
    bills = [
        f"{number}. Bill {bill['bill_number']} dated {day(bill['bill_date'])} ({month(bill['service_month'])}): "
        f"{_rupees(bill['balance'])}, {bill['days']} days old"
        for number, bill in enumerate(statement["bills"], start=1)
    ]
    lines = [
        f"Dear {name},",
        "",
        f"This is a gentle reminder that the following bills are still unpaid as on {day(statement['as_of'])}:",
        "",
        *bills,
        "",
        f"Total outstanding: {_rupees(statement['total'])}",
        *_bank_lines(profile),
        "",
        "Kindly arrange the payment at the earliest. If you have already paid, please share the payment details "
        "so that we can update our records.",
        "",
        "Regards,",
        profile.get("company_name", ""),
    ]
    return "\n".join(lines)


# --------------------------------------------------------------------------- sending


def _email(to: str, subject: str, message: str, pdf: bytes, filename: str, user: dict[str, Any]) -> None:
    if not email_enabled():
        raise ShareError("Email is not set up on this server (ORION_SMTP_HOST is empty). Download the PDF and send it yourself.")
    if not message.strip():
        raise ShareError("Write a message to send with it.")
    try:
        send_mail(
            to,
            subject,
            message.strip() + "\n",
            attachments=[(filename, pdf, "application/pdf")],
            reply_to=(user.get("email") or "").strip() or None,
            raise_on_error=True,
        )
    except RuntimeError as exc:
        raise ShareError(str(exc)) from exc


def _bill_for_sending(bill_code: str) -> dict[str, Any]:
    bill = billing.get_bill(bill_code)
    if not bill:
        raise ShareError("That bill does not exist.")
    if bill["status"] != "Issued":
        raise ShareError("A cancelled bill is not sent to the client.")
    return bill


def invoice_share(bill_code: str) -> dict[str, Any]:
    """What the Send dialog starts with for a bill."""
    bill = _bill_for_sending(bill_code)
    profile = bill["profile"]
    return {
        "subject": invoice_subject(bill, profile),
        "message": invoice_message(bill, profile),
        "email_enabled": email_enabled(),
        **last_contact(bill["client_code"]),
        "history": history(bill["client_code"], bill_code),
    }


def _letterhead(wanted: bool):
    """The company letterhead to draw a PDF on, or None for the document's own typed heading."""
    if not wanted:
        return None
    from app import letterhead
    from app.letterhead_page import Letterhead

    return Letterhead(letterhead.load_design())


def email_invoice(bill_code: str, to: str, message: str, user: dict[str, Any], on_letterhead: bool = False) -> dict[str, Any]:
    bill = _bill_for_sending(bill_code)
    recipient = parse_emails(to)
    subject = invoice_subject(bill, bill["profile"])
    filename = f"Invoice {bill['bill_number'].replace('/', '-')}.pdf"
    _email(recipient, subject, message, invoice_pdf(bill, _letterhead(on_letterhead)), filename, user)
    _log("invoice", "email", bill["client_code"], [bill_code], recipient, subject, None, user["id"])
    return {"ok": True, "to": recipient}


def whatsapp_invoice(bill_code: str, phone: str, message: str, user: dict[str, Any]) -> dict[str, Any]:
    bill = _bill_for_sending(bill_code)
    number = whatsapp_number(phone)
    if not message.strip():
        raise ShareError("Write a message to send with it.")
    _log("invoice", "whatsapp", bill["client_code"], [bill_code], number, None, None, user["id"])
    return {"url": whatsapp_url(number, message.strip())}


def invoice_document(bill_code: str, on_letterhead: bool = False) -> tuple[str, bytes] | None:
    bill = billing.get_bill(bill_code)
    if not bill:
        return None
    return f"Invoice {bill['bill_number'].replace('/', '-')}.pdf", invoice_pdf(bill, _letterhead(on_letterhead))


def _statement_for_sending(client_code: str) -> dict[str, Any]:
    statement = client_statement(client_code)
    if not statement:
        raise ShareError("That client has nothing outstanding.")
    return statement


def reminder_share(client_code: str) -> dict[str, Any]:
    statement = _statement_for_sending(client_code)
    profile = billing.get_profile()
    return {
        "subject": reminder_subject(statement, profile),
        "message": reminder_message(statement, profile),
        "email_enabled": email_enabled(),
        **last_contact(client_code),
        "history": history(client_code),
    }


def statement_document(client_code: str, on_letterhead: bool = False) -> tuple[str, bytes] | None:
    statement = client_statement(client_code)
    if not statement:
        return None
    name = re.sub(r"[^A-Za-z0-9 _-]+", "", statement["client_name"] or "client").strip() or "client"
    return (f"Statement {name} {statement['as_of']}.pdf",
            statement_pdf(statement, billing.get_profile(), _letterhead(on_letterhead)))


def _reminded_bills(statement: dict[str, Any]) -> list[str]:
    return [bill["id"] for bill in statement["bills"]]


def email_reminder(client_code: str, to: str, message: str, user: dict[str, Any], on_letterhead: bool = False) -> dict[str, Any]:
    statement = _statement_for_sending(client_code)
    profile = billing.get_profile()
    recipient = parse_emails(to)
    subject = reminder_subject(statement, profile)
    filename, pdf = statement_document(client_code, on_letterhead) or ("Statement.pdf", b"")
    _email(recipient, subject, message, pdf, filename, user)
    _log("reminder", "email", client_code, _reminded_bills(statement), recipient, subject,
         Decimal(str(statement["total"])), user["id"])
    return {"ok": True, "to": recipient}


def whatsapp_reminder(client_code: str, phone: str, message: str, user: dict[str, Any]) -> dict[str, Any]:
    statement = _statement_for_sending(client_code)
    number = whatsapp_number(phone)
    if not message.strip():
        raise ShareError("Write a message to send with it.")
    _log("reminder", "whatsapp", client_code, _reminded_bills(statement), number, None,
         Decimal(str(statement["total"])), user["id"])
    return {"url": whatsapp_url(number, message.strip())}

