"""Credit notes and bad-debt write-offs against an issued bill.

A credit note takes money off what a client still owes: the revenue and the GST that go with it come off too. It never changes the bill as it was
issued. The only things it touches are its own row here, and (through ``billing.apply_credit`` / ``unapply_credit``, in the same transaction) the
bill's open revenue entry, the bill's running credited figures and the GST due on it.

A credit note is MADE (status Pending), then APPROVED by someone other than the person who made it, or by an admin; only then does it take effect and
get its number (``CN 2026-27/1``, from a counter that never gives a number twice). A write-off (a bad debt) is approved by an admin only. A pending
note can be refused or withdrawn; an approved one can be reversed by an admin, with a reason. Nothing here is ever deleted.

This is the only writer of ``orion_ods.credit_note`` and ``credit_note_counter``.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from app import billing
from app.database import db_cursor, get_connection
from app.idempotency import Idempotency

KINDS = ("Credit note", "Bad debt write-off")
STATUSES = ("Pending", "Approved", "Rejected", "Withdrawn", "Reversed")
REASON_MIN = 5
REASON_MAX = 400
MAX_ROWS = 2000


class CreditNoteError(billing.BillError):
    """Something the person can fix: said in words."""


def cn_number(fy_start_year: int, seq: int) -> str:
    return f"CN {billing.bill_number(fy_start_year, seq)}"


def _reason(value: Any, what: str = "the reason") -> str:
    text = " ".join(str(value or "").split())
    if len(text) < REASON_MIN:
        raise CreditNoteError(f"Say {what}, in a few words.")
    return text[:REASON_MAX]


def can_approve(note: dict[str, Any], user_id: int | None, admin: bool) -> str | None:
    """Why this person cannot approve the note, or None when they can: a write-off needs an admin; anything else needs someone other than its maker,
    unless the person is an admin (a team of one still has to be able to issue a credit note)."""
    if note["kind"] == "Bad debt write-off" and not admin:
        return "A write-off is approved by an admin."
    if note["created_by"] == user_id and not admin:
        return "A credit note is approved by someone other than the person who made it, or by an admin."
    return None


def _row(cur, row) -> dict[str, Any]:
    note = {col.name: value for col, value in zip(cur.description, row)}
    for key in ("total", "taxable", "cgst", "sgst"):
        note[key] = float(note[key])
    for key in ("note_date", "created_timestamp", "decided_timestamp", "reversed_timestamp"):
        note[key] = note[key].isoformat() if note.get(key) else None
    return note


_SELECT = """
    SELECT n.credit_note_id AS id, n.bill_code, b.bill_number, b.client_code, cl.client_name, b.party_name, n.kind, n.status, n.note_date, n.total,
           n.taxable, n.cgst, n.sgst, n.reason, n.cn_number, n.created_by, cu.display_name AS created_by_name, n.created_timestamp,
           n.decided_by, du.display_name AS decided_by_name, n.decided_timestamp, n.decision_note, ru.display_name AS reversed_by_name,
           n.reversed_timestamp, n.reversal_reason
      FROM orion_ods.credit_note n
      JOIN orion_ods.bill b ON b.bill_code = n.bill_code
      LEFT JOIN orion_ods.client cl ON cl.client_code = b.client_code
      LEFT JOIN orion_ods.app_user cu ON cu.id = n.created_by
      LEFT JOIN orion_ods.app_user du ON du.id = n.decided_by
      LEFT JOIN orion_ods.app_user ru ON ru.id = n.reversed_by
"""


def _with_rights(note: dict[str, Any], user_id: int | None, admin: bool) -> dict[str, Any]:
    pending = note["status"] == "Pending"
    refusal = can_approve(note, user_id, admin) if pending else "It is not pending."
    note["can_approve"] = pending and refusal is None
    note["approve_blocked"] = refusal if pending else None
    note["can_withdraw"] = pending and (note["created_by"] == user_id or admin)
    note["can_reverse"] = note["status"] == "Approved" and admin
    return note


def get(credit_note_id: int, user_id: int | None = None, admin: bool = False) -> dict[str, Any] | None:
    with db_cursor() as cur:
        cur.execute(f"{_SELECT} WHERE n.credit_note_id = %s", (credit_note_id,))
        row = cur.fetchone()
        return _with_rights(_row(cur, row), user_id, admin) if row else None


def list_for_bill(bill_code: str, user_id: int | None = None, admin: bool = False) -> list[dict[str, Any]]:
    with db_cursor() as cur:
        cur.execute(f"{_SELECT} WHERE n.bill_code = %s ORDER BY n.created_timestamp DESC, n.credit_note_id DESC", (bill_code,))
        return [_with_rights(_row(cur, row), user_id, admin) for row in cur.fetchall()]


def listing(status: str | None = None, fy: int | None = None, user_id: int | None = None, admin: bool = False) -> dict[str, Any]:
    """Credit notes newest first, with how many wait for a decision (all of them, whatever the filter) and what the approved ones come to."""
    if status and status not in STATUSES:
        raise CreditNoteError("Choose a status from the list.")
    where, params = ["TRUE"], []
    if status:
        where.append("n.status = %s")
        params.append(status)
    if fy:
        where.append("n.fy_start_year = %s")
        params.append(fy)
    with db_cursor() as cur:
        cur.execute(f"{_SELECT} WHERE {' AND '.join(where)} ORDER BY n.created_timestamp DESC, n.credit_note_id DESC LIMIT %s", (*params, MAX_ROWS))
        rows = [_with_rights(_row(cur, row), user_id, admin) for row in cur.fetchall()]
        cur.execute("SELECT COUNT(*) FROM orion_ods.credit_note WHERE status = 'Pending'")
        pending = cur.fetchone()[0]
        cur.execute("SELECT DISTINCT fy_start_year FROM orion_ods.credit_note ORDER BY 1 DESC")
        years = [{"fy_start_year": y, "label": billing.fy_label(y)} for (y,) in cur.fetchall()]
    approved = [row for row in rows if row["status"] == "Approved"]
    return {
        "rows": rows,
        "pending": pending,
        "years": years,
        "totals": {"approved": round(sum(r["total"] for r in approved), 2), "gst": round(sum(r["cgst"] + r["sgst"] for r in approved), 2), "count": len(approved)},
    }


def preview(bill_code: str, total: Any) -> dict[str, Any]:
    """What a credit of ``total`` would be made of (taxable value, CGST, SGST) and what would still be owed, from what is open on the bill now."""
    credit = billing._paisa(billing._dec(total, "The credit"))
    with db_cursor() as cur:
        bill = billing._bill_row(cur, bill_code)
        if not bill:
            raise CreditNoteError("That bill does not exist.")
        open_entry = next((e for e in billing._revenue_entries(cur, bill_code) if e["status"] == "Prospective"), None)
    if not open_entry:
        raise CreditNoteError("Nothing is still to be received on this bill, so there is nothing to credit.")
    if credit <= 0 or credit > open_entry["total"]:
        raise CreditNoteError(f"Enter an amount up to {billing._inr(open_entry['total'])}.")
    parts, left = billing.split_payment(open_entry, credit)
    gst_parts = bill["cgst_amount"] + bill["sgst_amount"]
    cgst = billing._paisa(parts["gst"] * bill["cgst_amount"] / gst_parts) if gst_parts > 0 else Decimal("0")
    return {
        "total": float(credit), "taxable": float(parts["taxable"]), "cgst": float(cgst), "sgst": float(parts["gst"] - cgst),
        "still_owed": float(left["total"]), "open": float(open_entry["total"]),
    }


def create(
    bill_code: str, kind: Any, total: Any, note_date: Any, reason: Any, user_id: int | None, idem: Idempotency | None = None,
) -> dict[str, Any]:
    """Make a credit note (it waits for approval and changes nothing yet). With ``idem`` the same request again answers with the first one's note."""
    if kind not in KINDS:
        raise CreditNoteError(f"Choose what this is: {' or '.join(KINDS)}.")
    credit = billing._paisa(billing._dec(total, "The credit"))
    if credit <= 0:
        raise CreditNoteError("Enter the amount to credit.")
    if not isinstance(note_date, date):
        raise CreditNoteError("Choose the date of the credit note.")
    if note_date > date.today():
        raise CreditNoteError("The date of a credit note cannot be in the future.")
    why = _reason(reason)
    conn = get_connection()
    cur = conn.cursor()
    try:
        if idem is not None:
            prior = idem.claim(cur)
            if prior is not None:
                conn.rollback()
                return get(prior["credit_note_id"], user_id)  # the same request again
        bill = billing._bill_row(cur, bill_code, lock=True)
        if not bill:
            raise CreditNoteError("That bill does not exist.")
        if bill["status"] != "Issued":
            raise CreditNoteError("A cancelled bill cannot be credited.")
        if not bill["case_code"]:
            raise CreditNoteError("Tag this bill to a case first, by editing it. Revenue is recorded against the case.")
        if note_date < bill["bill_date"]:
            raise CreditNoteError(f"A credit note cannot be dated before the bill ({bill['bill_date']:%d %b %Y}).")
        open_entry = next((e for e in billing._revenue_entries(cur, bill_code) if e["status"] == "Prospective"), None)
        if not open_entry:
            raise CreditNoteError("Nothing is still to be received on this bill, so there is nothing to credit.")
        if credit > open_entry["total"]:
            raise CreditNoteError(f"Only {billing._inr(open_entry['total'])} is still to be received on this bill, so a credit note cannot be for more.")
        cur.execute(
            """
            INSERT INTO orion_ods.credit_note (bill_code, kind, note_date, total, reason, fy_start_year, created_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING credit_note_id
            """,
            (bill_code, kind, note_date, credit, why, billing.fy_start_year(note_date), user_id),
        )
        note_id = cur.fetchone()[0]
        if idem is not None:
            idem.remember(cur, {"credit_note_id": note_id})
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()
    return get(note_id, user_id)


def _pending(cur, credit_note_id: int) -> dict[str, Any]:
    cur.execute(
        "SELECT credit_note_id, bill_code, kind, status, total, created_by, fy_start_year, note_date FROM orion_ods.credit_note WHERE credit_note_id = %s FOR UPDATE",
        (credit_note_id,),
    )
    row = cur.fetchone()
    if not row:
        raise CreditNoteError("That credit note does not exist.")
    return {col.name: value for col, value in zip(cur.description, row)}


def approve(credit_note_id: int, user_id: int | None, admin: bool, *, confirm: bool = False, seen_total: Any = None) -> dict[str, Any]:
    """Approve a pending note: it takes effect (the bill's open amount, revenue and GST come down) and gets its number. Needs the confirmation and the
    amount the person saw, so a note that was changed or already decided is never approved blind."""
    if not confirm:
        raise CreditNoteError("Confirm the credit note on the screen before approving it.")
    with db_cursor(commit=True) as cur:
        note = _pending(cur, credit_note_id)
        if note["status"] != "Pending":
            raise CreditNoteError(f"That credit note is already {note['status'].lower()}.")
        if billing._paisa(billing._dec(seen_total, "The amount you saw")) != note["total"]:
            raise CreditNoteError("The credit note changed while you had it open. Reload it and check the amount.")
        refusal = can_approve(note, user_id, admin)
        if refusal:
            raise CreditNoteError(refusal)
        parts = billing.apply_credit(cur, note["bill_code"], note["total"], user_id)
        cur.execute(
            """
            INSERT INTO orion_ods.credit_note_counter (fy_start_year, last_no) VALUES (%s, 1)
            ON CONFLICT (fy_start_year) DO UPDATE SET last_no = orion_ods.credit_note_counter.last_no + 1
            RETURNING last_no
            """,
            (note["fy_start_year"],),
        )
        seq = cur.fetchone()[0]
        cur.execute(
            """
            UPDATE orion_ods.credit_note
               SET status = 'Approved', taxable = %s, cgst = %s, sgst = %s, cn_seq = %s, cn_number = %s, decided_by = %s, decided_timestamp = CURRENT_TIMESTAMP
             WHERE credit_note_id = %s
            """,
            (parts["taxable"], parts["cgst"], parts["sgst"], seq, cn_number(note["fy_start_year"], seq), user_id, credit_note_id),
        )
    return get(credit_note_id, user_id, admin)


def reject(credit_note_id: int, user_id: int | None, admin: bool, note_text: Any) -> dict[str, Any]:
    """Refuse a pending note, with a reason. It never takes effect and leaves no gap in the numbering."""
    why = _reason(note_text, "why it is refused")
    with db_cursor(commit=True) as cur:
        note = _pending(cur, credit_note_id)
        if note["status"] != "Pending":
            raise CreditNoteError(f"That credit note is already {note['status'].lower()}.")
        cur.execute(
            "UPDATE orion_ods.credit_note SET status = 'Rejected', decided_by = %s, decided_timestamp = CURRENT_TIMESTAMP, decision_note = %s WHERE credit_note_id = %s",
            (user_id, why, credit_note_id),
        )
    return get(credit_note_id, user_id, admin)


def withdraw(credit_note_id: int, user_id: int | None, admin: bool) -> dict[str, Any]:
    """Take back a pending note: its maker (or an admin) when it was made by mistake."""
    with db_cursor(commit=True) as cur:
        note = _pending(cur, credit_note_id)
        if note["status"] != "Pending":
            raise CreditNoteError(f"That credit note is already {note['status'].lower()}.")
        if note["created_by"] != user_id and not admin:
            raise CreditNoteError("Only the person who made a credit note, or an admin, can withdraw it.")
        cur.execute(
            "UPDATE orion_ods.credit_note SET status = 'Withdrawn', decided_by = %s, decided_timestamp = CURRENT_TIMESTAMP WHERE credit_note_id = %s",
            (user_id, credit_note_id),
        )
    return get(credit_note_id, user_id, admin)


def reverse(credit_note_id: int, user_id: int | None, admin: bool, reason: Any) -> dict[str, Any]:
    """Undo an approved note (an admin, with a reason): what it credited is owed again and the GST due goes back up. The note and its number are kept."""
    if not admin:
        raise CreditNoteError("Only an admin can reverse a credit note.")
    why = _reason(reason)
    with db_cursor(commit=True) as cur:
        cur.execute(
            "SELECT bill_code, status, taxable, cgst, sgst, total FROM orion_ods.credit_note WHERE credit_note_id = %s FOR UPDATE", (credit_note_id,)
        )
        row = cur.fetchone()
        if not row:
            raise CreditNoteError("That credit note does not exist.")
        bill_code, status, taxable, cgst, sgst, total = row
        if status != "Approved":
            raise CreditNoteError("Only an approved credit note can be reversed.")
        billing.unapply_credit(cur, bill_code, {"taxable": taxable, "cgst": cgst, "sgst": sgst, "total": total}, user_id)
        cur.execute(
            "UPDATE orion_ods.credit_note SET status = 'Reversed', reversed_by = %s, reversed_timestamp = CURRENT_TIMESTAMP, reversal_reason = %s WHERE credit_note_id = %s",
            (user_id, why, credit_note_id),
        )
    return get(credit_note_id, user_id, admin)
