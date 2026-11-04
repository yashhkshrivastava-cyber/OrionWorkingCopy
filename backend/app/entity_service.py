"""Creating, changing and deleting an operational record, with every rule that applies.

This is the one place those three operations are done. The HTTP routes in ``routers/entities_router.py`` and the AI
assistant's tools (``ai/tools``) both call it, so a record is held to the same rules whoever asks for the change: the
payload is cleaned and range-checked (``payload.clean_payload``), a record locked by its bill cannot be touched,
the database's own rules are turned into plain messages, and the who-changed-it columns are filled in.

Failures are ``EntityError`` with an HTTP-style status and a message that is safe to show to a person.
"""

from __future__ import annotations

import math
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import psycopg2
from psycopg2 import errors as pg_errors

from app import documents_filing, entities, opportunity_followups, payables
from app.database import db_cursor
from app.db_utils import delete_record, fetch_by_id, fetch_display_label, insert, update
from app.entities import ENTITIES, create_fields, duplicate_note, find_possible_duplicates, invalid_reason, locked_reason, with_create_fields
from app.payload import PayloadError, clean_payload


class EntityError(Exception):
    """A refusal, with the status an HTTP route would give it."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


DATABASE_REFUSALS = (pg_errors.CheckViolation, psycopg2.DataError)


def get_entity(name: str) -> dict:
    if name not in ENTITIES:
        raise EntityError(404, "Unknown entity")
    return ENTITIES[name]


# The rules the database holds (migrate_client_group.sql, migrate_data_rules.sql), as a person should hear them.
CONSTRAINT_MESSAGES = {
    "client_group_not_self": "A client cannot be its own group. Leave Client Group empty for a client that stands on its own.",
    "client_group_no_loop": (
        "That group already belongs to this client, directly or through other groups, so the groups would go round in a circle."
    ),
    "employee_manager_not_self": "An employee cannot be their own manager. Leave Manager empty, or pick someone else.",
    "employee_manager_no_loop": (
        "That manager already reports to this employee, directly or through other managers, so the managers would go "
        "round in a circle."
    ),
    "car_transaction_readings_not_negative": "Odometer readings cannot be negative.",
    "car_transaction_final_not_below_initial": "The final reading cannot be lower than the initial reading.",
    "car_transaction_driven_km_not_negative": "Driven KM cannot be negative.",
    "case_monthly_allowed_km_not_negative": "Monthly Allowed KM cannot be negative.",
    "car_per_km_price_not_negative": "Per KM Price cannot be negative.",
    "contact_end_after_start": "The day they left cannot be before the day you came to know them.",
    "contact_primary_must_be_active": "A primary contact must be Active.",
    "contact_role_known": "Choose one of the roles in the list.",
    "contact_status_known": "Choose Active, Inactive or Left organisation.",
    "contact_primary_known": "Primary contact is Yes or No.",
    "contact_method_known": "Choose one of the ways of reaching them in the list.",
    "emd_amount_positive": "The EMD amount must be more than zero.",
    "emd_refund_not_negative": "The refund amount cannot be negative.",
    "emd_deduction_not_negative": "The deduction cannot be negative.",
    "emd_returned_within_amount": "The refund and the deduction together cannot be more than the EMD.",
    "emd_valid_until_after_deposit": "Valid until cannot be before the day the document was issued or the EMD was deposited.",
    "emd_refunded_needs_date": "Say the day the refund was received (Refund received on), or leave the status as Refund requested.",
    "emd_mode_known": "Choose one of the modes of payment in the list.",
    "emd_status_known": "Choose one of the statuses in the list.",
    "salary_paid_needs_run": (
        "Salary is marked paid in Bank > Payroll (Mark salary paid), which pays a month's lines in one pay run from an account, so the bank balance is right. Enter the salary line as not paid, then mark the month paid there."
    ),
    "salary_line_paid_is_locked": (
        "This salary line has been paid in a pay run and can no longer be changed. To correct it, reverse the pay run in Bank > Payroll (with a reason), change the line, and mark the month paid again."
    ),
    "salary_line_paid_cannot_be_deleted": (
        "This salary line has been paid in a pay run, so it cannot be deleted. Reverse the pay run in Bank > Payroll (with a reason) first."
    ),
    "expense_paid_stays_committed": (
        "An expense that has payments on it stays Committed. Reverse its payments first (Bank > Payables), with a reason, if it was entered by mistake."
    ),
    "expense_amount_covers_payments": (
        "An expense cannot be less than what has already been paid on it. Reverse a payment first (Bank > Payables), with a reason, to lower it."
    ),
    "case_transaction_committed_needs_bill": (
        "Money received is recorded on its bill: open the bill in Utility > Billing and choose Record payment. Money that has no bill (an advance, a deposit) is entered in Bank > Ledger > Add entry, as a receipt with no bill."
    ),
}


def database_refusal(exc: Exception) -> EntityError:
    """A value the database rules out, as a message a person can act on rather than an internal error."""
    if isinstance(exc, pg_errors.CheckViolation):
        constraint = exc.diag.constraint_name or ""
        if constraint in CONSTRAINT_MESSAGES:
            return EntityError(400, CONSTRAINT_MESSAGES[constraint])
        rule = constraint.replace("_", " ")
        return EntityError(400, f"A value is not allowed here ({rule}). Check the dropdowns and dates.")
    return EntityError(400, "A value is too large, or not valid, for this field.")


def validate(entity: dict, payload: dict, *, for_update: bool = False, existing: dict | None = None) -> dict:
    try:
        return clean_payload(entity, payload, for_update=for_update, existing=existing)
    except PayloadError as exc:
        raise EntityError(400, str(exc)) from exc


def possible_duplicates(name: str, data: dict[str, Any]) -> list[dict]:
    """What is already recorded that the record about to be added looks like (for a kind of record that checks), each with a sentence saying so. Used by the
    form before it saves, and by the Copilot before it asks for confirmation; adding is never refused because of it."""
    entity = get_entity(name)
    if not entity.get("duplicate_check"):
        return []
    cleaned = validate(with_create_fields(entity), data)
    found = find_possible_duplicates(name, cleaned)
    return [{**match, "note": duplicate_note(match)} for match in found]


def split_payment(entity: dict, cleaned: dict) -> dict:
    """Take the extra questions (``create_fields``: who paid it, from where) out of what was cleaned, so only the record's own columns are written."""
    return {key: cleaned.pop(key) for key in list(cleaned) if key in create_fields(entity)}


def check_payment_on_entry(cleaned: dict, paid: dict) -> bool:
    """Whether the record being added is also paid. Refuses a payment that cannot be made, in words a person can act on."""
    answered = {key: value for key, value in paid.items() if value not in (None, "")}
    if not answered:
        return False
    if answered.get("paid_on") is None:
        raise EntityError(400, "Say the day it was paid (Paid On), or leave Paid From and Payment Reference empty.")
    if cleaned.get("transaction_status") != "Committed":
        raise EntityError(400, "Only an expense with the status Incurred can be marked as paid. A planned expense has not happened yet.")
    total = cleaned.get("amount_after_tax_gst")
    if total is None:
        total = cleaned.get("transaction_amount")
    if total is None or float(total) <= 0:
        raise EntityError(400, "An expense with no amount cannot be marked as paid.")
    return True


def pay_new_record(cur, name: str, code: Any, paid: dict, user_id: int | None) -> None:
    """Record the payment of a record that has just been added, in the same transaction (so both are saved, or neither)."""
    try:
        payables.pay_on_entry(cur, str(code), user_id, paid_date=paid.get("paid_on"), account_id=paid.get("paid_from"), reference=paid.get("payment_reference"))
    except payables.PayableError as exc:
        raise EntityError(400, str(exc)) from exc


def create(name: str, data: dict[str, Any], user_id: int | None, idem: Any = None) -> Any:
    """Insert a record (see ``_create``), then update what depends on it: a won opportunity's follow-ups."""
    code = _create(name, data, user_id, idem)
    opportunity_followups.entity_saved(name, code)
    return code


def _create(name: str, data: dict[str, Any], user_id: int | None, idem: Any = None) -> Any:
    """Insert a record. Returns its key (an employee's code, so documents can be attached straight away).

    An expense may also say it was paid (Paid On, Paid From, Payment Reference): its payment is recorded in the same transaction, and with ``idem`` the
    same request arriving again saves and pays nothing a second time."""
    entity = get_entity(name)
    cleaned = validate(with_create_fields(entity), data)
    paid = split_payment(entity, cleaned)
    if not cleaned:
        raise EntityError(400, "No data provided")
    problem = invalid_reason(name, None, cleaned)
    if problem:
        raise EntityError(400, problem)
    paying = check_payment_on_entry(cleaned, paid)
    try:
        if not paying:
            return insert(entity["table"], list(cleaned.keys()), list(cleaned.values()), user_id=user_id, returning=entity["primary_key"])
        with db_cursor(commit=True) as cur:
            if idem is not None:
                prior = idem.claim(cur)
                if prior is not None:
                    return prior["id"]
            code = insert(entity["table"], list(cleaned.keys()), list(cleaned.values()), user_id=user_id, returning=entity["primary_key"], cur=cur)
            pay_new_record(cur, name, code, paid, user_id)
            if idem is not None:
                idem.remember(cur, {"id": code})
        return code
    except pg_errors.UniqueViolation as exc:
        raise EntityError(400, "A record with this unique key already exists.") from exc
    except pg_errors.ForeignKeyViolation as exc:
        raise EntityError(400, "One of the records you picked no longer exists.") from exc
    except DATABASE_REFUSALS as exc:
        raise database_refusal(exc) from exc


def _who_changed(user_id: Any) -> str:
    """The name of the person who last saved a record, for the message a conflict gives. Empty when it cannot be found."""
    if user_id is None:
        return ""
    try:
        from app.database import db_cursor

        with db_cursor() as cur:
            cur.execute("SELECT display_name FROM orion_ods.app_user WHERE id = %s", (user_id,))
            row = cur.fetchone()
        return str(row[0]).strip() if row and row[0] else ""
    except Exception:
        return ""


def _conflict(record: dict | None) -> EntityError:
    if record is None:
        return EntityError(404, "This record was deleted by someone else after you opened it.")
    who = _who_changed(record.get("last_updated_by"))
    by = f" by {who}" if who else ""
    return EntityError(
        409,
        f"This record was changed{by} after you opened it, so your change was not saved. "
        "Open it again to see what changed, then make your change again.",
    )


def _same_version(stored: Any, given: Any) -> bool:
    """Whether the version a person opened the record with is the one stored. Compared as moments, so the same instant
    written with another offset or precision still matches."""
    if given in (None, ""):
        return stored is None
    if stored is None:
        return False
    try:
        opened = datetime.fromisoformat(str(given).strip().replace("Z", "+00:00"))
    except ValueError:
        return False
    if isinstance(stored, datetime):
        if opened.tzinfo is None and stored.tzinfo is not None:
            opened = opened.replace(tzinfo=stored.tzinfo)
        return opened == stored
    return False


def change(
    name: str,
    record_id: str,
    data: dict[str, Any],
    user_id: int | None,
    expected_updated: str | None = None,
) -> None:
    """Update the fields given. A record locked by its bill, or a change that breaks a rule, is refused.

    ``expected_updated`` is the ``last_updated_timestamp`` of the record as the person opened it. If the record has been
    saved by anyone since, nothing is written (409), so one person's save never silently undoes another's. When it is not
    given (a caller that read the record just now, such as the assistant) the version read here is used, which still
    stops a change made between the read below and the write.
    """
    entity = get_entity(name)
    existing = fetch_by_id(entity["table"], record_id, entity["primary_key"])
    if not existing:
        raise EntityError(404, "Record not found")
    reason = locked_reason(name, existing)
    if reason:
        raise EntityError(409, reason)
    stored_version = existing.get("last_updated_timestamp")
    if expected_updated not in (None, ""):
        if not _same_version(stored_version, expected_updated):
            raise _conflict(existing)
    # The stored record goes in so a total is worked out from the fields that were not sent as well as the ones that were.
    cleaned = validate(entity, data, for_update=True, existing=existing)
    if not cleaned:
        raise EntityError(400, "No data provided")
    problem = invalid_reason(name, record_id, cleaned, existing)
    if problem:
        raise EntityError(400, problem)
    try:
        changed = update(
            entity["table"], list(cleaned.keys()), list(cleaned.values()), record_id, entity["primary_key"],
            user_id=user_id, expected_updated=stored_version,
        )
    except pg_errors.ForeignKeyViolation as exc:
        raise EntityError(400, "One of the records you picked no longer exists.") from exc
    except DATABASE_REFUSALS as exc:
        raise database_refusal(exc) from exc
    if not changed:
        raise _conflict(fetch_by_id(entity["table"], record_id, entity["primary_key"]))
    # What is filed in the Document Center follows the names, the client and the case it is filed under.
    documents_filing.entity_saved(name, record_id)
    opportunity_followups.entity_saved(name, record_id)


def remove(name: str, record_id: str, user_id: int | None) -> None:
    """Delete a record, unless its bill locks it or another record still uses it."""
    entity = get_entity(name)
    existing = fetch_by_id(entity["table"], record_id, entity["primary_key"])
    if not existing:
        raise EntityError(404, "Record not found")
    reason = locked_reason(name, existing)
    if reason:
        raise EntityError(409, reason)
    if name == "Expense Transaction" and entities.expense_has_payments(record_id):
        raise EntityError(
            409,
            "A payment has been recorded on this expense. Payments are kept for ever, even when reversed, so it cannot be deleted. "
            "Reverse its payments (Bank > Payables) and set its status to Cancelled instead.",
        )
    try:
        delete_record(entity["table"], record_id, entity["primary_key"], user_id=user_id)
    except pg_errors.ForeignKeyViolation as exc:
        raise EntityError(
            409,
            "Other records still use this one, for example as a manager, a capability head, a case's client "
            "or another client's group. Change or remove those first.",
        ) from exc
    documents_filing.entity_saved(name, record_id)  # an employee's or an EMD's filed papers go to the trash with it
    opportunity_followups.entity_saved(name, record_id)


def serialize_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        value = float(value)
    if isinstance(value, float) and not math.isfinite(value):
        return None  # a NaN stored before it was refused cannot be written as JSON; shown empty, it can be opened and corrected
    if isinstance(value, float):
        return value
    if isinstance(value, bool):
        return value
    return value


def serialize_record(record: dict) -> dict:
    return {k: serialize_value(v) for k, v in record.items()}


def hydrate_lookup_labels(entity: dict, record: dict) -> dict:
    """Attach related-row names so the update form can show Client/Case/… not codes."""
    labels: dict[str, str] = {}
    for key, config in entity["form_fields"].items():
        if "source_table" not in config:
            continue
        raw = record.get(key)
        if isinstance(raw, str):
            raw = raw.strip()
            record[key] = raw or None
        if raw is None or raw == "":
            continue
        label = fetch_display_label(
            config["source_table"],
            config["source_display_column"],
            config.get("source_pk_column", "id"),
            raw,
            from_sql=config.get("source_from"),
        )
        if label:
            labels[key] = label
    if labels:
        record["__labels"] = labels
    return record
