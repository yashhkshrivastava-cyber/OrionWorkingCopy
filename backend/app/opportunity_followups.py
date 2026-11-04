"""What has to be done once an opportunity is won: create its case, and record the EMD against it.

Every opportunity that is Closed Won has two follow-ups, one to create the **case** and one to record the **EMD**
(``orion_ods.opportunity_followup``, created by ``.cursor/db/migrate_followups.sql``). They behave like a task that is handed to
the people who can change operational data:

* **open** from the moment the opportunity is saved as won, and it stays open (and in everyone's notifications) until it is settled;
* **done** by itself as soon as the case (or the EMD) exists, however it was made: the follow-up form, the ordinary record form, an Excel
  upload or the assistant. It is worked out from the records, not from who clicked what;
* **dismissed** only by a person who decides the case or the EMD is not required, with an optional reason. Nothing else dismisses
  one, and a dismissed one can be reopened;
* **withdrawn** by itself while the opportunity is not won (it was changed back), and open again if it is won again.

Every change is kept in ``opportunity_followup_event``. The set-based statements in ``sync`` are the only thing that creates, settles
or withdraws a follow-up, and they are safe to run at any time and as often as wanted. ``sync`` runs after the records that matter are saved
(``entity_service``), after an Excel upload, and whenever the notifications are read.

An EMD belongs to a case, so recording the EMD needs the case to exist first; the EMD follow-up says so until it does.
"""

from __future__ import annotations

import logging
from typing import Any

from app.database import db_cursor

logger = logging.getLogger(__name__)

KINDS = ("case", "emd")
NOTE_LIMIT = 300
DISMISSED_SHOWN = 50

# The opportunity has a case: one that names it, or the one it became (the opportunity's own link).
CASE_EXISTS = """(EXISTS (SELECT 1 FROM orion_ods."case" c WHERE c.opportunity_code = o.opportunity_code)
                  OR o.opportunity_case_code IS NOT NULL)"""
# The opportunity has an EMD: one that names it, or one against its case.
EMD_EXISTS = """EXISTS (SELECT 1 FROM orion_ods.emd e
                         WHERE e.opportunity_code = o.opportunity_code
                            OR e.case_code = o.opportunity_case_code
                            OR e.case_code IN (SELECT c.case_code FROM orion_ods."case" c WHERE c.opportunity_code = o.opportunity_code))"""
SETTLED = f"(CASE f.kind WHEN 'case' THEN {CASE_EXISTS} ELSE {EMD_EXISTS} END)"
WON = "o.opportunity_status = 'Closed Won'"


class FollowupError(ValueError):
    """The request cannot be carried out. The message is safe to show to the user."""


def _event(cur, ids: list[int], action: str, note: str | None = None, user_id: int | None = None) -> None:
    for followup_id in ids:
        cur.execute(
            "INSERT INTO orion_ods.opportunity_followup_event (followup_id, action, note, by_user) VALUES (%s, %s, %s, %s)",
            (followup_id, action, note, user_id),
        )


def sync() -> dict[str, int]:
    """Bring every follow-up in step with the opportunities, cases and EMDs, and say how many changed."""
    counts = {"created": 0, "reopened": 0, "done": 0, "withdrawn": 0, "linked": 0}
    with db_cursor(commit=True) as cur:
        # A case made for an opportunity is the case that opportunity became, when it has none yet: the dashboards read that link
        # (what the wins now bill), and a person making the case should not have to set it on the opportunity as well.
        cur.execute(
            """
            UPDATE orion_ods.opportunity o
               SET opportunity_case_code = (SELECT MIN(c.case_code) FROM orion_ods."case" c WHERE c.opportunity_code = o.opportunity_code),
                   last_updated_timestamp = CURRENT_TIMESTAMP
             WHERE o.opportunity_case_code IS NULL
               AND EXISTS (SELECT 1 FROM orion_ods."case" c WHERE c.opportunity_code = o.opportunity_code)
            """
        )
        counts["linked"] = cur.rowcount
        # A win with no follow-ups yet, for each of the two things to do. It is open unless it is already settled. Only the missing ones are
        # tried, so the numbers of the table are not used up by every look.
        cur.execute(
            f"""
            INSERT INTO orion_ods.opportunity_followup (opportunity_code, kind, status)
            SELECT o.opportunity_code, k.kind,
                   CASE WHEN (CASE k.kind WHEN 'case' THEN {CASE_EXISTS} ELSE {EMD_EXISTS} END) THEN 'done' ELSE 'open' END
              FROM orion_ods.opportunity o CROSS JOIN (VALUES ('case'), ('emd')) AS k(kind)
             WHERE {WON}
               AND NOT EXISTS (SELECT 1 FROM orion_ods.opportunity_followup x WHERE x.opportunity_code = o.opportunity_code AND x.kind = k.kind)
            ON CONFLICT (opportunity_code, kind) DO NOTHING
            RETURNING followup_id, status
            """
        )
        made = cur.fetchall()
        counts["created"] = len(made)
        _event(cur, [i for i, _status in made], "created")
        # Won again after being withdrawn, or settled and then no longer (the case was deleted): it is open again.
        cur.execute(
            f"""
            UPDATE orion_ods.opportunity_followup f
               SET status = 'open', resolved_timestamp = NULL, resolved_by = NULL, resolution_note = NULL,
                   last_changed_timestamp = CURRENT_TIMESTAMP
              FROM orion_ods.opportunity o
             WHERE o.opportunity_code = f.opportunity_code AND {WON}
               AND f.status IN ('withdrawn', 'done') AND NOT {SETTLED}
            RETURNING f.followup_id
            """
        )
        reopened = [r[0] for r in cur.fetchall()]
        counts["reopened"] = len(reopened)
        _event(cur, reopened, "reopened", "It is not settled")
        # Settled: the case, or the EMD, now exists.
        cur.execute(
            f"""
            UPDATE orion_ods.opportunity_followup f
               SET status = 'done', resolved_timestamp = CURRENT_TIMESTAMP, resolved_by = NULL, resolution_note = NULL,
                   last_changed_timestamp = CURRENT_TIMESTAMP
              FROM orion_ods.opportunity o
             WHERE o.opportunity_code = f.opportunity_code AND f.status IN ('open', 'withdrawn') AND {SETTLED}
            RETURNING f.followup_id
            """
        )
        done = [r[0] for r in cur.fetchall()]
        counts["done"] = len(done)
        _event(cur, done, "done")
        # No longer won: nothing to do for now.
        cur.execute(
            f"""
            UPDATE orion_ods.opportunity_followup f
               SET status = 'withdrawn', last_changed_timestamp = CURRENT_TIMESTAMP
              FROM orion_ods.opportunity o
             WHERE o.opportunity_code = f.opportunity_code AND f.status = 'open' AND NOT ({WON})
            RETURNING f.followup_id
            """
        )
        withdrawn = [r[0] for r in cur.fetchall()]
        counts["withdrawn"] = len(withdrawn)
        _event(cur, withdrawn, "withdrawn", "The opportunity is no longer won")
    return counts


def sync_quietly() -> None:
    """``sync`` for after something else was saved: a problem is logged and never reaches the person who saved it."""
    try:
        sync()
    except Exception:  # noqa: BLE001 - keeping the reminders up to date must never undo or fail the save that caused it; the next read does it
        logger.exception("Updating the follow-ups of won opportunities failed")


def entity_saved(name: str, _record_id: Any = None) -> None:
    """An opportunity, case or EMD was saved or deleted: its follow-ups may have changed."""
    if name in ("Opportunity", "Case", "EMD"):
        sync_quietly()


# --------------------------------------------------------------------------------------------------------------------
# Reading


def _rows(cur) -> list[dict[str, Any]]:
    return [
        {col.name: (value.isoformat() if hasattr(value, "isoformat") else value) for col, value in zip(cur.description, row)}
        for row in cur.fetchall()
    ]


_SELECT = """
    SELECT f.followup_id AS id, f.kind, f.status, f.opportunity_code, o.opportunity_name, o.tender_id,
           o.opportunity_end_date AS won_on, o.state, o.city, f.created_timestamp, f.resolved_timestamp,
           f.resolution_note, u.display_name AS resolved_by_name,
           {case_exists} AS has_case
      FROM orion_ods.opportunity_followup f
      JOIN orion_ods.opportunity o ON o.opportunity_code = f.opportunity_code
      LEFT JOIN orion_ods.app_user u ON u.id = f.resolved_by
"""


def _shape(item: dict[str, Any]) -> dict[str, Any]:
    code, name = item["opportunity_code"], item["opportunity_name"] or item["opportunity_code"]
    place = ", ".join(x for x in (item.pop("city"), item.pop("state")) if x)
    item["place"] = place
    waiting = item["kind"] == "emd" and not item["has_case"]
    item["waiting_for_case"] = waiting
    if item["kind"] == "case":
        item["title"] = f"Create the case for {name}"
        item["message"] = f"{name} ({code}) was won. Create the case it became."
        item["action"] = {"label": "Create case", "entity": "Case"}
    else:
        item["title"] = f"Record the EMD for {name}"
        item["message"] = f"{name} ({code}) was won. Record the EMD deposited for it." + (" Create its case first." if waiting else "")
        item["action"] = {"label": "Record EMD", "entity": "EMD"}
    item["action"]["path"] = f"/data/operational?intent=change&entity={item['action']['entity']}&mode=create&opportunity={code}"
    return item


def listing() -> dict[str, Any]:
    """What is waiting (oldest first), and what people decided is not needed (newest first, so a mistake can be undone)."""
    sync()
    select = _SELECT.format(case_exists=CASE_EXISTS)
    with db_cursor() as cur:
        cur.execute(f"{select} WHERE f.status = 'open' ORDER BY f.created_timestamp, f.followup_id")
        open_items = [_shape(row) for row in _rows(cur)]
        cur.execute(
            f"{select} WHERE f.status = 'dismissed' AND f.resolved_by IS NOT NULL ORDER BY f.resolved_timestamp DESC LIMIT {DISMISSED_SHOWN}"
        )
        dismissed = [_shape(row) for row in _rows(cur)]
    return {"open": open_items, "dismissed": dismissed, "count": len(open_items)}


def context(opportunity_code: str) -> dict[str, Any] | None:
    """The won opportunity, and the cases made for it, for the form that creates its case or EMD. None when there is no such opportunity."""
    with db_cursor() as cur:
        cur.execute(
            """SELECT opportunity_code, opportunity_name, tender_id, opportunity_status, opportunity_case_code
                 FROM orion_ods.opportunity WHERE opportunity_code = %s""",
            (opportunity_code,),
        )
        found = _rows(cur)
        if not found:
            return None
        cur.execute(
            """SELECT c.case_code AS id, CONCAT_WS(' — ', NULLIF(BTRIM(c.case_name), ''), c.case_code) AS label
                 FROM orion_ods."case" c
                WHERE c.opportunity_code = %s OR c.case_code = %s
                ORDER BY c.case_code""",
            (opportunity_code, found[0]["opportunity_case_code"]),
        )
        cases = _rows(cur)
    return {"opportunity": found[0], "cases": cases}


# --------------------------------------------------------------------------------------------------------------------
# Writing


def _clean_note(note: Any) -> str | None:
    text = " ".join(str(note or "").split())
    if len(text) > NOTE_LIMIT:
        raise FollowupError(f"The reason can be at most {NOTE_LIMIT} characters.")
    return text or None


def dismiss(followup_id: int, user_id: int, note: Any = None) -> bool:
    """Say that the case, or the EMD, is not required. False when there is no such follow-up."""
    text = _clean_note(note)
    with db_cursor(commit=True) as cur:
        cur.execute("SELECT status FROM orion_ods.opportunity_followup WHERE followup_id = %s FOR UPDATE", (followup_id,))
        row = cur.fetchone()
        if row is None:
            return False
        if row[0] != "open":
            raise FollowupError("Only a follow-up that is waiting can be dismissed.")
        cur.execute(
            """UPDATE orion_ods.opportunity_followup SET status = 'dismissed', resolved_timestamp = CURRENT_TIMESTAMP, resolved_by = %s,
                      resolution_note = %s, last_changed_timestamp = CURRENT_TIMESTAMP WHERE followup_id = %s""",
            (user_id, text, followup_id),
        )
        _event(cur, [followup_id], "dismissed", text, user_id)
    return True


def reopen(followup_id: int, user_id: int) -> bool:
    """Take back a dismissal: it is waiting again (and settles itself if the case, or the EMD, exists). False when there is none."""
    with db_cursor(commit=True) as cur:
        cur.execute("SELECT status, resolved_by FROM orion_ods.opportunity_followup WHERE followup_id = %s FOR UPDATE", (followup_id,))
        row = cur.fetchone()
        if row is None:
            return False
        if row[0] != "dismissed":
            raise FollowupError("Only a dismissed follow-up can be reopened.")
        cur.execute(
            """UPDATE orion_ods.opportunity_followup SET status = 'open', resolved_timestamp = NULL, resolved_by = NULL,
                      resolution_note = NULL, last_changed_timestamp = CURRENT_TIMESTAMP WHERE followup_id = %s""",
            (followup_id,),
        )
        _event(cur, [followup_id], "reopened", None, user_id)
    sync_quietly()
    return True
