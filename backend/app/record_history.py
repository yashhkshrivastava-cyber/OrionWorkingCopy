"""The history of one record, read from the warehouse.

The warehouse keeps a version of a record each time one of its values changed between two loads
(``dw_sync``), with who saved it and when. This module turns those versions into a list of what
changed, newest first. It reads only; nothing here writes.

What it can and cannot say:

* A record changed twice between two loads shows one change, with its final values.
* "Who" is the user who last saved the version. Rows saved before the audit columns existed
  have none, and are shown without a name.
* Only fields on the record's form are compared, so a change to something the form does not show
  appears as a change with no listed fields.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from app import dw_sync
from app.database import db_cursor
from app.entities import ENTITIES


def _plain(value: Any) -> Any:
    """A value as the browser should see it: JSON-safe, with money and dates in plain form."""
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def _comparable(value: Any) -> Any:
    """Two values that mean the same thing compare equal: 100 and 100.00, text with stray spaces."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float, Decimal)):
        return round(float(value), 6)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    text = str(value).strip()
    return text or None


def diff_versions(versions: list[dict[str, Any]], labels: dict[str, str]) -> list[dict[str, Any]]:
    """History entries, newest first, from a record's warehouse versions (oldest first).

    ``labels`` maps a column to the name shown for it and also says which columns to compare.
    Each version carries ``source_created_timestamp``, ``source_last_updated_timestamp``,
    ``source_created_by``, ``source_last_updated_by`` and, if it was deleted, ``is_expired``,
    ``expired_by`` and ``expired_when``.
    """
    entries: list[dict[str, Any]] = []
    previous: dict[str, Any] | None = None
    for version in versions:
        if previous is None:
            entries.append(
                {
                    "kind": "created",
                    "when": _plain(version.get("source_created_timestamp") or version.get("effective_from")),
                    "by_id": version.get("source_created_by"),
                    "changes": [],
                }
            )
        else:
            changes = [
                {"field": column, "label": label, "from": _plain(previous.get(column)), "to": _plain(version.get(column))}
                for column, label in labels.items()
                if _comparable(previous.get(column)) != _comparable(version.get(column))
            ]
            entries.append(
                {
                    "kind": "changed",
                    "when": _plain(version.get("source_last_updated_timestamp") or version.get("effective_from")),
                    "by_id": version.get("source_last_updated_by"),
                    "changes": changes,
                }
            )
        previous = version
    if previous is not None and previous.get("is_expired"):
        entries.append(
            {
                "kind": "deleted",
                "when": _plain(previous.get("expired_when") or previous.get("effective_to")),
                "by_id": previous.get("expired_by"),
                "changes": [],
            }
        )
    entries.reverse()
    return entries


def apply_lookup_labels(entries: list[dict[str, Any]], names: dict[str, dict[str, str]]) -> None:
    """Add ``from_label`` / ``to_label`` to changes on a lookup field, so a code reads as a name.

    ``names`` maps a field to {code: name}. The stored code stays in ``from`` / ``to``. A code with no
    row any more (the employee was deleted) is labelled as such rather than shown bare.
    """
    for entry in entries:
        for change in entry["changes"]:
            known = names.get(change["field"])
            if known is None:
                continue
            for side in ("from", "to"):
                code = change[side]
                if code is None:
                    continue
                if code not in known:
                    change[f"{side}_label"] = f"{code} (no longer exists)"
                elif str(code) in known[code]:
                    # A name that already ends with the code (a client's group reads "name — CL-0001").
                    change[f"{side}_label"] = known[code]
                else:
                    change[f"{side}_label"] = f"{known[code]} ({code})"


def _spec_for(entity_name: str) -> tuple[dict[str, Any], dict[str, Any]] | None:
    entity = ENTITIES.get(entity_name)
    if not entity:
        return None
    spec = next((s for s in dw_sync.TABLES.values() if s.get("ods") == entity["table"]), None)
    return (entity, spec) if spec else None


def _lookup_names(cur, entity: dict[str, Any], entries: list[dict[str, Any]]) -> dict[str, dict[str, str]]:
    """For each lookup field that changed, the current name of every code that appears in it."""
    wanted: dict[str, set[str]] = {}
    for entry in entries:
        for change in entry["changes"]:
            field = entity["form_fields"].get(change["field"], {})
            if field.get("source_table"):
                wanted.setdefault(change["field"], set()).update(
                    str(value) for value in (change["from"], change["to"]) if value not in (None, "")
                )
    names: dict[str, dict[str, str]] = {}
    for key, codes in wanted.items():
        field = entity["form_fields"][key]
        pk, display = field["source_pk_column"], field["source_display_column"]
        # table, pk and display come from the ENTITIES registry, never from a request
        cur.execute(
            f"""
            SELECT BTRIM({pk}::text), COALESCE(NULLIF(BTRIM(({display})::text), ''), BTRIM({pk}::text))
              FROM {field["source_table"]}
             WHERE BTRIM({pk}::text) = ANY(%s)
            """,
            (sorted(codes),),
        )
        names[key] = {row[0]: row[1] for row in cur.fetchall()}
    return names


def record_history(entity_name: str, record_id: str, hide: frozenset[str] | set[str] = frozenset()) -> dict[str, Any] | None:
    """The history of one record, or None when the entity has no warehouse table.

    ``hide`` names fields to leave out of what changed, for a reader who is not allowed to see them.
    """
    found = _spec_for(entity_name)
    if not found:
        return None
    entity, spec = found
    labels = {
        key: field.get("label") or key
        for key, field in entity["form_fields"].items()
        if key in spec["dw_cols"] and key != spec["nk"] and key not in hide
    }
    with db_cursor() as cur:
        cur.execute(
            f"SELECT * FROM {spec['dw']} WHERE {spec['nk']} = %s ORDER BY effective_from, {spec['sk']}",
            (record_id,),
        )
        columns = [col.name for col in cur.description]
        versions = [dict(zip(columns, row)) for row in cur.fetchall()]
        if versions and versions[-1].get("is_expired"):
            cur.execute(
                """
                SELECT deleted_timestamp FROM orion_ods.record_deleted
                 WHERE table_name = %s AND record_code = %s
                 ORDER BY deleted_timestamp DESC, id DESC LIMIT 1
                """,
                (spec["ods"], record_id),
            )
            row = cur.fetchone()
            versions[-1]["expired_when"] = row[0] if row else None
        cur.execute(
            f"SELECT last_updated_timestamp FROM {spec['ods']} WHERE {spec['nk']} = %s", (record_id,)
        )
        live = cur.fetchone()
        entries = diff_versions(versions, labels)
        names = _lookup_names(cur, entity, entries)
        apply_lookup_labels(entries, names)
        ids = sorted({entry["by_id"] for entry in entries if entry["by_id"] is not None})
        names: dict[int, str] = {}
        if ids:
            cur.execute("SELECT id, display_name FROM orion_ods.app_user WHERE id = ANY(%s)", (ids,))
            names = {row[0]: row[1] for row in cur.fetchall()}
    status = dw_sync.load_status()
    last = status["last_success"]
    # The record was saved after the last load began, so its newest change is not in the list yet.
    pending = bool(
        live and live[0] and last and last["started"] and live[0] > datetime.fromisoformat(last["started"])
    ) or bool(live and not versions)
    for entry in entries:
        by_id = entry.pop("by_id")
        entry["by"] = names.get(by_id, "A former user") if by_id is not None else None
    return {
        "entries": entries,
        "loaded": last["finished"] if last else None,
        "pending": pending,
    }
