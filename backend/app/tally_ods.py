"""SCD Type 1 Tally ODS loads.

Working copy of Tally Prime. Natural keys stay stable; surrogate keys are
assigned once. Each load upserts current Tally rows and deletes anything
Tally no longer returns.
"""

from __future__ import annotations

import hashlib
import json
import logging
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable

import psycopg2
from psycopg2.extras import execute_values

from app.config import db_settings, env
from app import db_grants
from app.database import get_connection
from app.tally_client import (
    TallyError,
    TallySession,
    list_companies,
    list_companies_on_disk,
    match_company_name,
    ping,
    tally_settings,
)

logger = logging.getLogger(__name__)

SCHEMA_FILE = Path(__file__).resolve().parents[2] / ".cursor" / "db" / "tally_ods_schema.sql"
GRANTS_FILE = Path(__file__).resolve().parents[2] / ".cursor" / "db" / "grants.sql"

EMPTY_STATS = {"inserted": 0, "updated": 0, "deleted": 0, "unchanged": 0}

GUID_FETCH = "Name, Parent, GUID, MasterID, AlterID"


def _run_sql(sql: str, settings: dict | None = None) -> None:
    conn = psycopg2.connect(**(settings or db_settings()))
    cur = conn.cursor()
    try:
        cur.execute(sql)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


def _superuser_settings() -> dict | None:
    password = env("ORION_POSTGRES_SUPER_PASSWORD")
    if not password:
        return None
    return {
        **db_settings(),
        "user": env("ORION_POSTGRES_SUPERUSER", "postgres"),
        "password": password,
    }


def ensure_tally_ods_privileges() -> None:
    if not db_grants.needed():
        return
    sql = GRANTS_FILE.read_text(encoding="utf-8")
    settings = _superuser_settings()
    if not settings:
        return
    try:
        _run_sql(sql, settings)
    except Exception:
        logger.exception("Could not apply Tally ODS grants as the Postgres superuser")


def reset_tally_tables() -> None:
    """Empty tally_ods and tally_dw and restart surrogate-key sequences."""
    sql = """
    DO $$
    DECLARE
        stmt text;
    BEGIN
        SELECT 'TRUNCATE TABLE ' || string_agg(format('%I.%I', schemaname, tablename), ', ')
               || ' RESTART IDENTITY CASCADE'
          INTO stmt
          FROM pg_tables
         WHERE schemaname IN ('tally_ods', 'tally_dw')
           -- Bills raised in the application are not Tally data and cannot be reloaded from Tally.
           AND tablename NOT LIKE 'application\\_%';
        IF stmt IS NOT NULL THEN
            EXECUTE stmt;
        END IF;
    END $$;

    DO $$
    DECLARE
        seq record;
    BEGIN
        FOR seq IN
            SELECT n.nspname, c.relname
              FROM pg_class c
              JOIN pg_namespace n ON n.oid = c.relnamespace
             WHERE n.nspname IN ('tally_ods', 'tally_dw')
               AND c.relkind = 'S'
               AND c.relname NOT LIKE 'application\\_%'
        LOOP
            EXECUTE format('ALTER SEQUENCE %I.%I RESTART WITH 1', seq.nspname, seq.relname);
        END LOOP;
    END $$;
    """
    try:
        _run_sql(sql)
        return
    except Exception as exc:
        text = str(exc).lower()
        if "permission denied" not in text and "must be owner" not in text:
            raise
        refused = exc
    settings = _superuser_settings()
    if not settings:
        raise refused  # the owner is needed and there is no way to become it: say what the database said
    _run_sql(sql, settings)


def ensure_tally_ods_schema() -> None:
    ensure_tally_ods_privileges()
    sql = SCHEMA_FILE.read_text(encoding="utf-8")
    try:
        _run_sql(sql)
        return
    except Exception as exc:
        if "permission denied" not in str(exc).lower():
            raise
        logger.warning("Tally ODS schema apply failed; retrying after grants: %s", exc)
    ensure_tally_ods_privileges()
    _run_sql(sql)


def _norm(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, Decimal):
        return format(value, "f")
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, bool):
        return value
    return value


def source_hash(row: dict, columns: list[str]) -> str:
    payload = {col: _norm(row.get(col)) for col in columns if col not in {"source_hash"}}
    blob = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _sql_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def scd1_apply(cur, table: str, pk: str, columns: list[str], rows: list[dict]) -> dict[str, int]:
    """Upsert by natural_key and delete rows Tally no longer returns."""
    business = [col for col in columns if col != "natural_key"]
    incoming: dict[str, dict] = {}
    for row in rows:
        key = row.get("natural_key")
        if not key:
            continue
        prepared = {col: row.get(col) for col in columns}
        prepared["source_hash"] = source_hash(prepared, columns)
        incoming[key] = prepared

    cur.execute(f"SELECT natural_key, source_hash FROM {table}")
    existing = {key: digest for key, digest in cur.fetchall()}

    to_insert = []
    to_update = []
    unchanged = 0
    for key, row in incoming.items():
        if key not in existing:
            to_insert.append(row)
        elif existing[key] != row["source_hash"]:
            to_update.append(row)
        else:
            unchanged += 1

    insert_cols = columns + ["source_hash"]
    if to_insert:
        sql = f"INSERT INTO {table} ({', '.join(insert_cols)}) VALUES %s"
        execute_values(
            cur,
            sql,
            [[row.get(col) for col in insert_cols] for row in to_insert],
        )

    if to_update:
        assignments = ", ".join(f"{_sql_ident(col)} = %s" for col in business)
        assignments += ", source_hash = %s, last_updated_timestamp = CURRENT_TIMESTAMP"
        sql = f"UPDATE {table} SET {assignments} WHERE natural_key = %s"
        for row in to_update:
            values = [row.get(col) for col in business]
            values.append(row["source_hash"])
            values.append(row["natural_key"])
            cur.execute(sql, values)

    stale = [key for key in existing if key not in incoming]
    deleted = 0
    if stale:
        cur.execute(f"DELETE FROM {table} WHERE natural_key = ANY(%s)", (stale,))
        deleted = cur.rowcount if cur.rowcount and cur.rowcount > 0 else len(stale)

    return {
        "inserted": len(to_insert),
        "updated": len(to_update),
        "deleted": deleted,
        "unchanged": unchanged,
    }


def voucher_sk_map(cur) -> dict[str, int]:
    cur.execute("SELECT natural_key, voucher_sk FROM tally_ods.voucher")
    return {key: int(sk) for key, sk in cur.fetchall()}


def ledger_entry_sk_map(cur) -> dict[str, int]:
    cur.execute("SELECT natural_key, voucher_ledger_entry_sk FROM tally_ods.voucher_ledger_entry")
    return {key: int(sk) for key, sk in cur.fetchall()}


COMMON_ID_FIELDS = {
    "tally_guid": ("GUID",),
    "tally_master_id": ("MASTERID",),
    "tally_alter_id": ("ALTERID",),
    "parent_name": ("PARENT",),
}


def _master_loader(
    key: str,
    tally_type: str,
    tag: str,
    fetch: str,
    table: str,
    pk: str,
    columns: list[str],
    extra_fields: dict[str, tuple[str, ...]] | None = None,
) -> Callable[[TallySession, Any], dict[str, int]]:
    fields = {**COMMON_ID_FIELDS, **(extra_fields or {})}

    def _load(session: TallySession, cur) -> dict[str, int]:
        rows = session.masters(key, tally_type, fetch, tag, fields)
        return scd1_apply(cur, table, pk, columns, rows)

    return _load


def _load_company(session: TallySession, cur) -> dict[str, int]:
    from app.tally_client import fetch_collection, list_companies, mapped_master

    listed = {row["name"]: row for row in list_companies()}
    fields = {
        "tally_guid": ("GUID",),
        "starting_from": ("STARTINGFROM",),
        "books_from": ("BOOKSFROM",),
        "state_name": ("STATENAME",),
        "country_name": ("COUNTRYNAME",),
        "gst_on": ("ISGSTON",),
        "gst_tax_unit_count": ("NUMGSTTAXUNIT",),
    }
    rows = []
    extra = []
    for company in session.companies:
        extra.extend(
            fetch_collection(
                company,
                "Company",
                "Name, GUID, StartingFrom, BooksFrom, StateName, CountryName, IsGstOn, NumGstTaxUnit",
                "COMPANY",
            )
        )
    seen = set()
    for el in extra:
        row = mapped_master(el, session.company, fields)
        if not row:
            continue
        listed_row = listed.get(row["name"], {})
        if row.get("gst_on") is None:
            row["gst_on"] = listed_row.get("gst_on")
        if row.get("gst_tax_unit_count") is None:
            row["gst_tax_unit_count"] = listed_row.get("gst_tax_unit_count")
        if row.get("state_name") is None:
            row["state_name"] = listed_row.get("state_name")
        rows.append(row)
        seen.add(row["name"])
    for name, listed_row in listed.items():
        if name in seen:
            continue
        if name not in session.companies:
            continue
        rows.append(
            {
                "natural_key": f"{name}|{name}",
                "company_name": name,
                "name": name,
                "tally_guid": None,
                "starting_from": None,
                "books_from": None,
                "state_name": listed_row.get("state_name"),
                "country_name": None,
                "gst_on": listed_row.get("gst_on"),
                "gst_tax_unit_count": listed_row.get("gst_tax_unit_count"),
            }
        )
    # company table uses company_name, not name
    normalized = []
    for row in rows:
        normalized.append(
            {
                "natural_key": row["natural_key"],
                "company_name": row.get("name") or row.get("company_name") or session.company,
                "tally_guid": row.get("tally_guid"),
                "starting_from": row.get("starting_from"),
                "books_from": row.get("books_from"),
                "state_name": row.get("state_name"),
                "country_name": row.get("country_name"),
                "gst_on": row.get("gst_on"),
                "gst_tax_unit_count": row.get("gst_tax_unit_count"),
            }
        )
    return scd1_apply(
        cur,
        "tally_ods.company",
        "company_sk",
        [
            "natural_key",
            "company_name",
            "tally_guid",
            "starting_from",
            "books_from",
            "state_name",
            "country_name",
            "gst_on",
            "gst_tax_unit_count",
        ],
        normalized,
    )


def _load_vouchers(session: TallySession, cur) -> dict[str, int]:
    rows = [item.header for item in session.vouchers()]
    return scd1_apply(
        cur,
        "tally_ods.voucher",
        "voucher_sk",
        [
            "natural_key",
            "company_name",
            "tally_guid",
            "remote_id",
            "vch_key",
            "voucher_type_name",
            "voucher_number",
            "voucher_date",
            "effective_date",
            "party_ledger_name",
            "narration",
            "reference",
            "persisted_view",
            "is_invoice",
            "is_optional",
        ],
        rows,
    )


def _attach_voucher_sk(rows: list[dict], mapping: dict[str, int], required: bool = True) -> list[dict]:
    attached = []
    for row in rows:
        voucher_sk = mapping.get(row.get("voucher_natural_key"))
        if voucher_sk is None and required:
            continue
        item = dict(row)
        item["voucher_sk"] = voucher_sk
        attached.append(item)
    return attached


def _load_ledger_entries(session: TallySession, cur) -> dict[str, int]:
    mapping = voucher_sk_map(cur)
    rows = []
    for voucher in session.vouchers():
        rows.extend(voucher.ledger_entries)
    rows = _attach_voucher_sk(rows, mapping)
    return scd1_apply(
        cur,
        "tally_ods.voucher_ledger_entry",
        "voucher_ledger_entry_sk",
        [
            "natural_key",
            "voucher_sk",
            "company_name",
            "line_no",
            "ledger_name",
            "amount",
            "is_deemed_positive",
            "is_party_ledger",
        ],
        rows,
    )


def _load_inventory_entries(session: TallySession, cur) -> dict[str, int]:
    mapping = voucher_sk_map(cur)
    rows = []
    for voucher in session.vouchers():
        rows.extend(voucher.inventory_entries)
    rows = _attach_voucher_sk(rows, mapping)
    return scd1_apply(
        cur,
        "tally_ods.voucher_inventory_entry",
        "voucher_inventory_entry_sk",
        [
            "natural_key",
            "voucher_sk",
            "company_name",
            "line_no",
            "stock_item_name",
            "godown_name",
            "actual_qty",
            "billed_qty",
            "rate",
            "amount",
        ],
        rows,
    )


def _load_bill_allocations(session: TallySession, cur) -> dict[str, int]:
    vouchers = voucher_sk_map(cur)
    ledgers = ledger_entry_sk_map(cur)
    rows = []
    for voucher in session.vouchers():
        for row in voucher.bill_allocations:
            item = dict(row)
            item["voucher_sk"] = vouchers.get(row.get("voucher_natural_key"))
            item["voucher_ledger_entry_sk"] = ledgers.get(row.get("ledger_entry_natural_key"))
            if item["voucher_sk"] is None:
                continue
            rows.append(item)
    return scd1_apply(
        cur,
        "tally_ods.voucher_bill_allocation",
        "voucher_bill_allocation_sk",
        [
            "natural_key",
            "voucher_sk",
            "voucher_ledger_entry_sk",
            "company_name",
            "line_no",
            "bill_name",
            "bill_type",
            "amount",
        ],
        rows,
    )


def _load_cost_centre_allocations(session: TallySession, cur) -> dict[str, int]:
    vouchers = voucher_sk_map(cur)
    ledgers = ledger_entry_sk_map(cur)
    rows = []
    for voucher in session.vouchers():
        for row in voucher.cost_centre_allocations:
            item = dict(row)
            item["voucher_sk"] = vouchers.get(row.get("voucher_natural_key"))
            item["voucher_ledger_entry_sk"] = ledgers.get(row.get("ledger_entry_natural_key"))
            if item["voucher_sk"] is None:
                continue
            rows.append(item)
    return scd1_apply(
        cur,
        "tally_ods.voucher_cost_centre_allocation",
        "voucher_cost_centre_allocation_sk",
        [
            "natural_key",
            "voucher_sk",
            "voucher_ledger_entry_sk",
            "company_name",
            "line_no",
            "category_name",
            "cost_centre_name",
            "amount",
        ],
        rows,
    )


MASTER_ID_COLS = ["natural_key", "company_name", "tally_guid", "tally_master_id", "tally_alter_id", "name"]
NAMED_PARENT_COLS = MASTER_ID_COLS + ["parent_name"]

DATASETS: dict[str, dict] = {
    "Company": {
        "kind": "master",
        "table": "tally_ods.company",
        "pk": "company_sk",
        "depends": [],
        "load": _load_company,
        "preview": """
            SELECT company_sk, company_name, tally_guid, starting_from, books_from,
                   state_name, country_name, gst_on, gst_tax_unit_count,
                   created_timestamp, last_updated_timestamp
            FROM tally_ods.company
            ORDER BY last_updated_timestamp DESC, company_sk DESC
        """,
    },
    "Account Group": {
        "kind": "master",
        "table": "tally_ods.account_group",
        "pk": "account_group_sk",
        "depends": ["Company"],
        "load": _master_loader(
            "Account Group",
            "Group",
            "GROUP",
            GUID_FETCH,
            "tally_ods.account_group",
            "account_group_sk",
            NAMED_PARENT_COLS,
        ),
        "preview": """
            SELECT account_group_sk, name, parent_name, tally_guid, company_name,
                   created_timestamp, last_updated_timestamp
            FROM tally_ods.account_group
            ORDER BY name
        """,
    },
    "Ledger": {
        "kind": "master",
        "table": "tally_ods.ledger",
        "pk": "ledger_sk",
        "depends": ["Company"],
        "load": _master_loader(
            "Ledger",
            "Ledger",
            "LEDGER",
            "Name, Parent, GUID, MasterID, AlterID, OpeningBalance, ClosingBalance, "
            "IsBillWiseOn, IsRevenue, TaxType, MailingName, CountryName, Pincode, "
            "Address, LedStateName, PartyGSTIN, GSTRegistrationType",
            "tally_ods.ledger",
            "ledger_sk",
            NAMED_PARENT_COLS
            + [
                "mailing_name",
                "opening_balance",
                "closing_balance",
                "is_bill_wise",
                "is_revenue",
                "tax_type",
                "country_name",
                "pincode",
                "address",
                "state_name",
                "gstin",
                "gst_registration_type",
            ],
            extra_fields={
                "mailing_name": ("MAILINGNAME",),
                "opening_balance": ("OPENINGBALANCE",),
                "closing_balance": ("CLOSINGBALANCE",),
                "is_bill_wise": ("ISBILLWISEON",),
                "is_revenue": ("ISREVENUE",),
                "tax_type": ("TAXTYPE",),
                "country_name": ("COUNTRYNAME",),
                "pincode": ("PINCODE",),
                "address": ("ADDRESS",),
                "state_name": ("LEDSTATENAME",),
                "gstin": ("PARTYGSTIN", "GSTIN"),
                "gst_registration_type": ("GSTREGISTRATIONTYPE",),
            },
        ),
        "preview": """
            SELECT ledger_sk, name, parent_name, mailing_name, address, state_name, gstin,
                   opening_balance, closing_balance,
                   is_bill_wise, is_revenue, tax_type, country_name, pincode, company_name,
                   created_timestamp, last_updated_timestamp
            FROM tally_ods.ledger
            ORDER BY name
        """,
    },
    "Cost Category": {
        "kind": "master",
        "table": "tally_ods.cost_category",
        "pk": "cost_category_sk",
        "depends": ["Company"],
        "load": _master_loader(
            "Cost Category",
            "CostCategory",
            "COSTCATEGORY",
            GUID_FETCH,
            "tally_ods.cost_category",
            "cost_category_sk",
            MASTER_ID_COLS,
        ),
        "preview": """
            SELECT cost_category_sk, name, tally_guid, company_name,
                   created_timestamp, last_updated_timestamp
            FROM tally_ods.cost_category
            ORDER BY name
        """,
    },
    "Cost Centre": {
        "kind": "master",
        "table": "tally_ods.cost_centre",
        "pk": "cost_centre_sk",
        "depends": ["Company"],
        "load": _master_loader(
            "Cost Centre",
            "CostCentre",
            "COSTCENTRE",
            "Name, Parent, GUID, MasterID, AlterID, Category",
            "tally_ods.cost_centre",
            "cost_centre_sk",
            NAMED_PARENT_COLS + ["category_name"],
            extra_fields={"category_name": ("CATEGORY",)},
        ),
        "preview": """
            SELECT cost_centre_sk, name, parent_name, category_name, company_name,
                   created_timestamp, last_updated_timestamp
            FROM tally_ods.cost_centre
            ORDER BY name
        """,
    },
    "Voucher Type": {
        "kind": "master",
        "table": "tally_ods.voucher_type",
        "pk": "voucher_type_sk",
        "depends": ["Company"],
        "load": _master_loader(
            "Voucher Type",
            "VoucherType",
            "VOUCHERTYPE",
            GUID_FETCH,
            "tally_ods.voucher_type",
            "voucher_type_sk",
            NAMED_PARENT_COLS,
        ),
        "preview": """
            SELECT voucher_type_sk, name, parent_name, company_name,
                   created_timestamp, last_updated_timestamp
            FROM tally_ods.voucher_type
            ORDER BY name
        """,
    },
    "Currency": {
        "kind": "master",
        "table": "tally_ods.currency",
        "pk": "currency_sk",
        "depends": ["Company"],
        "load": _master_loader(
            "Currency",
            "Currency",
            "CURRENCY",
            "Name, GUID, MasterID, OriginalName, MailingName",
            "tally_ods.currency",
            "currency_sk",
            ["natural_key", "company_name", "tally_guid", "tally_master_id", "name", "original_name", "mailing_name"],
            extra_fields={"original_name": ("ORIGINALNAME",), "mailing_name": ("MAILINGNAME",)},
        ),
        "preview": """
            SELECT currency_sk, name, original_name, mailing_name, company_name,
                   created_timestamp, last_updated_timestamp
            FROM tally_ods.currency
            ORDER BY name
        """,
    },
    "Unit": {
        "kind": "master",
        "table": "tally_ods.unit",
        "pk": "unit_sk",
        "depends": ["Company"],
        "load": _master_loader(
            "Unit",
            "Unit",
            "UNIT",
            "Name, GUID, MasterID, OriginalName, DecimalPlaces",
            "tally_ods.unit",
            "unit_sk",
            ["natural_key", "company_name", "tally_guid", "tally_master_id", "name", "original_name", "decimal_places"],
            extra_fields={"original_name": ("ORIGINALNAME",), "decimal_places": ("DECIMALPLACES",)},
        ),
        "preview": """
            SELECT unit_sk, name, original_name, decimal_places, company_name,
                   created_timestamp, last_updated_timestamp
            FROM tally_ods.unit
            ORDER BY name
        """,
    },
    "Godown": {
        "kind": "master",
        "table": "tally_ods.godown",
        "pk": "godown_sk",
        "depends": ["Company"],
        "load": _master_loader(
            "Godown",
            "Godown",
            "GODOWN",
            GUID_FETCH,
            "tally_ods.godown",
            "godown_sk",
            NAMED_PARENT_COLS,
        ),
        "preview": """
            SELECT godown_sk, name, parent_name, company_name,
                   created_timestamp, last_updated_timestamp
            FROM tally_ods.godown
            ORDER BY name
        """,
    },
    "Stock Group": {
        "kind": "master",
        "table": "tally_ods.stock_group",
        "pk": "stock_group_sk",
        "depends": ["Company"],
        "load": _master_loader(
            "Stock Group",
            "StockGroup",
            "STOCKGROUP",
            GUID_FETCH,
            "tally_ods.stock_group",
            "stock_group_sk",
            NAMED_PARENT_COLS,
        ),
        "preview": """
            SELECT stock_group_sk, name, parent_name, company_name,
                   created_timestamp, last_updated_timestamp
            FROM tally_ods.stock_group
            ORDER BY name
        """,
    },
    "Stock Category": {
        "kind": "master",
        "table": "tally_ods.stock_category",
        "pk": "stock_category_sk",
        "depends": ["Company"],
        "load": _master_loader(
            "Stock Category",
            "StockCategory",
            "STOCKCATEGORY",
            GUID_FETCH,
            "tally_ods.stock_category",
            "stock_category_sk",
            NAMED_PARENT_COLS,
        ),
        "preview": """
            SELECT stock_category_sk, name, parent_name, company_name,
                   created_timestamp, last_updated_timestamp
            FROM tally_ods.stock_category
            ORDER BY name
        """,
    },
    "Stock Item": {
        "kind": "master",
        "table": "tally_ods.stock_item",
        "pk": "stock_item_sk",
        "depends": ["Company"],
        "load": _master_loader(
            "Stock Item",
            "StockItem",
            "STOCKITEM",
            "Name, Parent, GUID, MasterID, AlterID, BaseUnits, ClosingBalance",
            "tally_ods.stock_item",
            "stock_item_sk",
            NAMED_PARENT_COLS + ["base_units", "closing_balance"],
            extra_fields={"base_units": ("BASEUNITS",), "closing_balance": ("CLOSINGBALANCE",)},
        ),
        "preview": """
            SELECT stock_item_sk, name, parent_name, base_units, closing_balance, company_name,
                   created_timestamp, last_updated_timestamp
            FROM tally_ods.stock_item
            ORDER BY name
        """,
    },
    "GST Classification": {
        "kind": "master",
        "table": "tally_ods.gst_classification",
        "pk": "gst_classification_sk",
        "depends": ["Company"],
        "load": _master_loader(
            "GST Classification",
            "GSTClassification",
            "GSTCLASSIFICATION",
            "Name, GUID, MasterID, HSNCode, GSTRate",
            "tally_ods.gst_classification",
            "gst_classification_sk",
            ["natural_key", "company_name", "tally_guid", "tally_master_id", "name", "hsn_code", "gst_rate"],
            extra_fields={"hsn_code": ("HSNCODE",), "gst_rate": ("GSTRATE",)},
        ),
        "preview": """
            SELECT gst_classification_sk, name, hsn_code, gst_rate, company_name,
                   created_timestamp, last_updated_timestamp
            FROM tally_ods.gst_classification
            ORDER BY name
        """,
    },
    "Tax Unit": {
        "kind": "master",
        "table": "tally_ods.tax_unit",
        "pk": "tax_unit_sk",
        "depends": ["Company"],
        "load": _master_loader(
            "Tax Unit",
            "TaxUnit",
            "TAXUNIT",
            "Name, GUID, MasterID",
            "tally_ods.tax_unit",
            "tax_unit_sk",
            ["natural_key", "company_name", "tally_guid", "tally_master_id", "name"],
        ),
        "preview": """
            SELECT tax_unit_sk, name, company_name, created_timestamp, last_updated_timestamp
            FROM tally_ods.tax_unit
            ORDER BY name
        """,
    },
    "Attendance Type": {
        "kind": "master",
        "table": "tally_ods.attendance_type",
        "pk": "attendance_type_sk",
        "depends": ["Company"],
        "load": _master_loader(
            "Attendance Type",
            "AttendanceType",
            "ATTENDANCETYPE",
            GUID_FETCH,
            "tally_ods.attendance_type",
            "attendance_type_sk",
            NAMED_PARENT_COLS,
        ),
        "preview": """
            SELECT attendance_type_sk, name, parent_name, company_name,
                   created_timestamp, last_updated_timestamp
            FROM tally_ods.attendance_type
            ORDER BY name
        """,
    },
    "Voucher": {
        "kind": "transaction",
        "table": "tally_ods.voucher",
        "pk": "voucher_sk",
        "depends": ["Company"],
        "load": _load_vouchers,
        "preview": """
            SELECT voucher_sk, voucher_date, voucher_type_name, voucher_number, party_ledger_name,
                   narration, reference, is_invoice, remote_id, company_name,
                   created_timestamp, last_updated_timestamp
            FROM tally_ods.voucher
            ORDER BY voucher_date DESC NULLS LAST, voucher_sk DESC
        """,
    },
    "Voucher Ledger Entry": {
        "kind": "transaction",
        "table": "tally_ods.voucher_ledger_entry",
        "pk": "voucher_ledger_entry_sk",
        "depends": ["Voucher"],
        "load": _load_ledger_entries,
        "preview": """
            SELECT e.voucher_ledger_entry_sk, v.voucher_date, v.voucher_type_name, v.voucher_number,
                   e.line_no, e.ledger_name, e.amount, e.is_deemed_positive, e.is_party_ledger,
                   e.created_timestamp, e.last_updated_timestamp
            FROM tally_ods.voucher_ledger_entry e
            LEFT JOIN tally_ods.voucher v ON v.voucher_sk = e.voucher_sk
            ORDER BY v.voucher_date DESC NULLS LAST, e.voucher_sk, e.line_no
        """,
    },
    "Voucher Inventory Entry": {
        "kind": "transaction",
        "table": "tally_ods.voucher_inventory_entry",
        "pk": "voucher_inventory_entry_sk",
        "depends": ["Voucher"],
        "load": _load_inventory_entries,
        "preview": """
            SELECT i.voucher_inventory_entry_sk, v.voucher_date, v.voucher_number,
                   i.line_no, i.stock_item_name, i.godown_name, i.actual_qty, i.billed_qty,
                   i.rate, i.amount, i.created_timestamp, i.last_updated_timestamp
            FROM tally_ods.voucher_inventory_entry i
            LEFT JOIN tally_ods.voucher v ON v.voucher_sk = i.voucher_sk
            ORDER BY v.voucher_date DESC NULLS LAST, i.voucher_sk, i.line_no
        """,
    },
    "Voucher Bill Allocation": {
        "kind": "transaction",
        "table": "tally_ods.voucher_bill_allocation",
        "pk": "voucher_bill_allocation_sk",
        "depends": ["Voucher", "Voucher Ledger Entry"],
        "load": _load_bill_allocations,
        "preview": """
            SELECT b.voucher_bill_allocation_sk, v.voucher_date, v.voucher_number,
                   b.line_no, b.bill_name, b.bill_type, b.amount,
                   b.created_timestamp, b.last_updated_timestamp
            FROM tally_ods.voucher_bill_allocation b
            LEFT JOIN tally_ods.voucher v ON v.voucher_sk = b.voucher_sk
            ORDER BY v.voucher_date DESC NULLS LAST, b.voucher_sk, b.line_no
        """,
    },
    "Voucher Cost Centre Allocation": {
        "kind": "transaction",
        "table": "tally_ods.voucher_cost_centre_allocation",
        "pk": "voucher_cost_centre_allocation_sk",
        "depends": ["Voucher", "Voucher Ledger Entry"],
        "load": _load_cost_centre_allocations,
        "preview": """
            SELECT c.voucher_cost_centre_allocation_sk, v.voucher_date, v.voucher_number,
                   c.line_no, c.category_name, c.cost_centre_name, c.amount,
                   c.created_timestamp, c.last_updated_timestamp
            FROM tally_ods.voucher_cost_centre_allocation c
            LEFT JOIN tally_ods.voucher v ON v.voucher_sk = c.voucher_sk
            ORDER BY v.voucher_date DESC NULLS LAST, c.voucher_sk, c.line_no
        """,
    },
}

REFRESH_ORDER = [
    "Company",
    "Account Group",
    "Ledger",
    "Cost Category",
    "Cost Centre",
    "Voucher Type",
    "Currency",
    "Unit",
    "Godown",
    "Stock Group",
    "Stock Category",
    "Stock Item",
    "GST Classification",
    "Tax Unit",
    "Attendance Type",
    "Voucher",
    "Voucher Ledger Entry",
    "Voucher Inventory Entry",
    "Voucher Bill Allocation",
    "Voucher Cost Centre Allocation",
]


def table_list() -> list[dict]:
    items = [
        {"name": name, "kind": DATASETS[name]["kind"], "rows": 0}
        for name in REFRESH_ORDER
    ]
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT c.relname
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'tally_ods' AND c.relkind = 'r'
            """
        )
        existing = {row[0] for row in cur.fetchall()}
        for item in items:
            qualified = DATASETS[item["name"]]["table"]
            bare = qualified.split(".")[-1]
            if bare not in existing:
                continue
            cur.execute(f"SELECT COUNT(*) FROM {qualified}")
            item["rows"] = int(cur.fetchone()[0])
    except Exception:
        logger.exception("Could not read Tally ODS table counts")
    finally:
        cur.close()
        conn.close()
    return items


def _load_one(name: str, session: TallySession, loaded: dict[str, dict[str, int]]) -> dict[str, int]:
    if name in loaded:
        return loaded[name]
    meta = DATASETS[name]
    for dep in meta.get("depends") or []:
        _load_one(dep, session, loaded)
    conn = get_connection()
    cur = conn.cursor()
    try:
        stats = meta["load"](session, cur)
        conn.commit()
        loaded[name] = stats
        return stats
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


def _iso(value) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def status_payload() -> dict:
    info = ping()
    company = None
    error = None
    warning = None
    loaded_names: list[str] = []
    disk_rows: list[dict] = []
    not_open: list[str] = []
    settings = tally_settings()
    configured = settings["company"]
    from_date = settings["from_date"]
    load_names: list[str] = []
    if info.get("running"):
        try:
            loaded_names = [row["name"] for row in list_companies() if row.get("name")]
            matched = match_company_name(configured, loaded_names) if configured else None
            load_names = [matched] if matched else ([] if configured else loaded_names)
            company = ", ".join(load_names) or (configured or None) or (", ".join(loaded_names) or None)
            disk_rows = []
            for row in list_companies_on_disk():
                name = row["name"]
                open_now = name in loaded_names
                disk_rows.append(
                    {
                        "name": name,
                        "starting_from": _iso(row.get("starting_from")),
                        "ending_at": _iso(row.get("ending_at")),
                        "company_number": row.get("company_number"),
                        "open": open_now,
                    }
                )
                if not open_now:
                    not_open.append(name)
            if configured and not matched:
                warning = (
                    f"Configured company {configured!r} is not open in Tally Prime. "
                    "Press F1 (Select Company), open it, then Load."
                )
            elif not configured and not_open:
                warning = (
                    "Tally has more companies on disk than are open. Orion can only load open companies. "
                    "Not open: "
                    + "; ".join(not_open)
                    + ". In Tally Prime press F1 (Select Company), open them (you can keep several open), then Load all tables."
                )
        except TallyError as exc:
            error = str(exc)
    return {
        **info,
        "company": company,
        "from_date": from_date,
        "configured_company": configured or None,
        "companies_to_load": load_names,
        "companies_loaded": loaded_names,
        "companies_on_disk": disk_rows,
        "companies_not_open": not_open,
        "warning": warning,
        "error": error,
    }
