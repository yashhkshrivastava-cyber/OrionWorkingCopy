"""SCD Type 2 warehouse loads from ODS.

Dimensions version when attributes change. Facts version when the source
transaction changes. Fact dimension keys are the versions that were current
on the transaction date (point-in-time).
"""

from __future__ import annotations

import hashlib
import logging
import math
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable

import psycopg2
from psycopg2.extras import execute_values

from app.config import db_settings, env
from app import db_grants
from app.database import db_cursor, get_connection

logger = logging.getLogger(__name__)

SCHEMA_FILE = Path(__file__).resolve().parents[2] / ".cursor" / "db" / "dw_schema.sql"
GRANTS_FILE = Path(__file__).resolve().parents[2] / ".cursor" / "db" / "grants.sql"

EMPTY_STATS = {"inserted": 0, "versioned": 0, "expired": 0, "unchanged": 0}

_SCD_COLUMNS = [
    "effective_from",
    "effective_to",
    "is_current",
    "is_expired",
    "source_created_timestamp",
    "source_last_updated_timestamp",
    "dw_created_timestamp",
    "dw_last_updated_timestamp",
    # Who made the version: the ODS row's created_by / last_updated_by (bills: created_by / version_by).
    "source_created_by",
    "source_last_updated_by",
]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _as_ts(value: Any) -> datetime:
    if value is None:
        return _utcnow()
    if isinstance(value, datetime):
        return _aware(value) or _utcnow()
    if isinstance(value, date):
        return datetime.combine(value, time.min, tzinfo=timezone.utc)
    return _utcnow()


def _first_effective(ods: dict) -> datetime:
    candidates: list[datetime] = []
    for key in (
        "created_timestamp",
        "client_start_date",
        "case_start_date",
        "emp_start_date",
        "opportunity_start_date",
        "transaction_date",
        "driving_date",
        "bill_date",
    ):
        value = ods.get(key)
        if value is not None:
            candidates.append(_as_ts(value))
    return min(candidates) if candidates else _utcnow()


def _norm(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, Decimal):
        value = float(value)
    if isinstance(value, float) and not math.isfinite(value):
        # NaN is never equal to itself, so a stored NaN would look changed on every load and gain a version each time
        return str(value)
    if isinstance(value, float):
        return value
    if isinstance(value, datetime):
        return _aware(value).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, bool):
        return value
    return value


def _changed(left: dict, right: dict, columns: list[str]) -> bool:
    return any(_norm(left.get(col)) != _norm(right.get(col)) for col in columns)


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


def ensure_dw_privileges() -> None:
    """Give orion_user CREATE/DML on orion_dw when the schema is owned by postgres."""
    if not db_grants.needed():
        return
    sql = GRANTS_FILE.read_text(encoding="utf-8")
    settings = _superuser_settings()
    if not settings:
        return
    try:
        _run_sql(sql, settings)
    except Exception:
        logger.exception("Could not apply warehouse grants as the Postgres superuser")


def ensure_dw_schema() -> None:
    ensure_dw_privileges()
    sql = SCHEMA_FILE.read_text(encoding="utf-8")
    try:
        _run_sql(sql)
        return
    except Exception as exc:
        if "permission denied" not in str(exc).lower():
            raise
        logger.warning("Warehouse schema apply failed; retrying after grants: %s", exc)
    ensure_dw_privileges()
    _run_sql(sql)


def _fetch_dicts(cur, sql: str, params=()) -> list[dict]:
    cur.execute(sql, params)
    cols = [desc[0] for desc in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def _close_and_insert(
    cur,
    spec: dict,
    current: dict | None,
    payload: dict,
    now: datetime,
    ods: dict,
) -> None:
    cols = spec["dw_cols"]
    if current:
        cur.execute(
            f"""
            UPDATE {spec["dw"]}
            SET effective_to = %s, is_current = FALSE, is_expired = FALSE,
                dw_last_updated_timestamp = %s
            WHERE {spec["sk"]} = %s
            """,
            (now, now, current[spec["sk"]]),
        )
        effective_from = now
    else:
        effective_from = _first_effective(ods)

    values = [payload.get(col) for col in cols] + [
        effective_from,
        None,
        True,
        False,
        payload.get("created_timestamp"),
        payload.get("last_updated_timestamp"),
        now,
        now,
        payload.get("source_created_by"),
        payload.get("source_last_updated_by"),
    ]
    col_sql = ", ".join(cols + _SCD_COLUMNS)
    placeholders = ", ".join(["%s"] * len(values))
    cur.execute(f"INSERT INTO {spec['dw']} ({col_sql}) VALUES ({placeholders})", values)


def _expire_deleted(cur, spec: dict, now: datetime, ods_keys: set) -> int:
    current = _fetch_dicts(
        cur,
        f"SELECT {spec['sk']}, {spec['nk']} FROM {spec['dw']} WHERE is_current = TRUE",
    )
    expired = 0
    for row in current:
        if row[spec["nk"]] in ods_keys:
            continue
        cur.execute(
            """
            SELECT deleted_by FROM orion_ods.record_deleted
             WHERE table_name = %s AND record_code = %s
             ORDER BY deleted_timestamp DESC, id DESC LIMIT 1
            """,
            (spec["ods"], str(row[spec["nk"]])),
        )
        deleted = cur.fetchone()
        cur.execute(
            f"""
            UPDATE {spec["dw"]}
            SET is_expired = TRUE, is_current = FALSE,
                effective_to = COALESCE(effective_to, %s),
                expired_by = %s,
                dw_last_updated_timestamp = %s
            WHERE {spec["sk"]} = %s
            """,
            (now, deleted[0] if deleted else None, now, row[spec["sk"]]),
        )
        expired += 1
    return expired


class _DimIndex:
    def __init__(self, rows: list[dict], nk: str, sk: str):
        self.nk = nk
        self.sk = sk
        self.by_nk: dict[Any, list[dict]] = {}
        for row in rows:
            self.by_nk.setdefault(row[nk], []).append(row)
        for versions in self.by_nk.values():
            versions.sort(key=lambda item: _aware(item["effective_from"]) or datetime.min.replace(tzinfo=timezone.utc))

    def at(self, code: Any, when: datetime) -> dict | None:
        if code is None or code == "":
            return None
        versions = self.by_nk.get(code) or []
        if not versions:
            return None
        when = _aware(when) or when
        for row in reversed(versions):
            start = _aware(row["effective_from"])
            end = _aware(row["effective_to"])
            if start and start <= when and (end is None or end > when):
                return row
        return versions[0]

    def latest(self, code: Any) -> dict | None:
        """The version that is current now, or the last one there was when the record has since been deleted."""
        if code is None or code == "":
            return None
        versions = self.by_nk.get(code) or []
        for row in reversed(versions):
            if row.get("is_current"):
                return row
        return versions[-1] if versions else None


class _PIT:
    def __init__(self, cur):
        self.case = _DimIndex(_fetch_dicts(cur, "SELECT * FROM orion_dw.dim_case"), "case_code", "case_sk")
        self.client = _DimIndex(_fetch_dicts(cur, "SELECT * FROM orion_dw.dim_client"), "client_code", "client_sk")
        self.capability = _DimIndex(
            _fetch_dicts(cur, "SELECT * FROM orion_dw.dim_capability"),
            "capability_code",
            "capability_sk",
        )
        self.domain = _DimIndex(
            _fetch_dicts(cur, "SELECT * FROM orion_dw.dim_business_domain"),
            "business_domain_code",
            "business_domain_sk",
        )
        self.expense = _DimIndex(
            _fetch_dicts(cur, "SELECT * FROM orion_dw.dim_expense_type"),
            "expense_type_code",
            "expense_type_sk",
        )
        self.employee = _DimIndex(
            _fetch_dicts(cur, "SELECT * FROM orion_dw.dim_employee"),
            "employee_code",
            "employee_sk",
        )
        self.car = _DimIndex(_fetch_dicts(cur, "SELECT * FROM orion_dw.dim_car"), "car_code", "car_sk")
        self.bill = _DimIndex(_fetch_dicts(cur, "SELECT * FROM orion_dw.fact_bill"), "bill_code", "bill_sk")

    def case_keys(self, case_code, when: datetime) -> dict:
        case_row = self.case.at(case_code, when)
        out = {
            "case_sk": case_row["case_sk"] if case_row else None,
            "client_sk": None,
            "capability_sk": None,
            "business_domain_sk": None,
        }
        if not case_row:
            return out
        client = self.client.at(case_row.get("client_code"), when)
        capability = self.capability.at(case_row.get("capability_code"), when)
        domain = self.domain.at(case_row.get("business_domain_code"), when)
        out["client_sk"] = client["client_sk"] if client else None
        out["capability_sk"] = capability["capability_sk"] if capability else None
        out["business_domain_sk"] = domain["business_domain_sk"] if domain else None
        return out


def _date_sk(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        value = value.date()
    if not isinstance(value, date):
        return None
    return int(value.strftime("%Y%m%d"))


def _event_time(ods: dict, now: datetime, *keys: str) -> datetime:
    for key in keys:
        if ods.get(key) is not None:
            value = ods[key]
            if isinstance(value, datetime):
                return _aware(value) or now
            if isinstance(value, date):
                return datetime.combine(value, time(23, 59, 59), tzinfo=timezone.utc)
    if ods.get("created_timestamp") is not None:
        return _as_ts(ods["created_timestamp"])
    return now


CALENDAR_FIRST_YEAR = 2015
#: Dates a person can type are not trusted to size the calendar: a typo (year 0202 or 9999) must not add a century of rows.
CALENDAR_LIMITS = (date(1990, 1, 1), date(2100, 12, 31))

# The date every fact is linked to the calendar by: a fact whose date has no calendar row drops out of every report
# that joins to it, so the calendar must reach the earliest and latest of these.
_FACT_DATES = (
    ("orion_ods.case_transaction", "transaction_date"),
    ("orion_ods.expense_transaction", "transaction_date"),
    ("orion_ods.employee_transaction", "transaction_date"),
    ("orion_ods.car_transaction", "driving_date"),
    ("orion_ods.bill", "bill_date"),
    ("orion_ods.emd", "deposit_date"),
)


def calendar_bounds(first: date, last: date, found: list[tuple[date | None, date | None]]) -> tuple[date, date]:
    """The calendar's first and last day: at least ``first``..``last``, and wide enough for every date found in the data
    (within CALENDAR_LIMITS)."""
    low, high = CALENDAR_LIMITS
    start, end = first, last
    for earliest, latest in found:
        if earliest is not None:
            start = min(start, max(earliest, low))
        if latest is not None:
            end = max(end, min(latest, high))
    return start, end


def _calendar_bounds(cur) -> tuple[date, date]:
    found = []
    for table, column in _FACT_DATES:
        cur.execute(f"SELECT MIN({column}), MAX({column}) FROM {table}")
        found.append(cur.fetchone())
    return calendar_bounds(date(CALENDAR_FIRST_YEAR, 1, 1), date(_utcnow().year + 3, 12, 31), found)


def _sync_date() -> dict[str, int]:
    conn = get_connection()
    cur = conn.cursor()
    stats = dict(EMPTY_STATS)
    try:
        start, end = _calendar_bounds(cur)
        cur.execute("SELECT date_sk FROM orion_dw.dim_date")
        have = {row[0] for row in cur.fetchall()}
        rows = []
        day = start
        while day <= end:
            sk = int(day.strftime("%Y%m%d"))
            if sk not in have:
                rows.append(
                    (
                        sk,
                        day,
                        day.year,
                        (day.month - 1) // 3 + 1,
                        day.month,
                        day.strftime("%B"),
                        int(day.strftime("%U")),
                        day.day,
                        day.isoweekday(),
                        day.strftime("%A"),
                        day.isoweekday() >= 6,
                    )
                )
            day += timedelta(days=1)
        if rows:
            execute_values(
                cur,
                """
                INSERT INTO orion_dw.dim_date (
                    date_sk, date_value, year_number, quarter_number, month_number,
                    month_name, week_of_year, day_of_month, day_of_week, day_name, is_weekend
                ) VALUES %s
                """,
                rows,
                page_size=1000,
            )
            stats["inserted"] = len(rows)
        stats["unchanged"] = len(have)
        conn.commit()
        return stats
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


def _sync_scd(spec: dict) -> dict[str, int]:
    conn = get_connection()
    cur = conn.cursor()
    stats = dict(EMPTY_STATS)
    now = _utcnow()
    try:
        pit = _PIT(cur) if spec.get("pit") else None
        ods_rows = _fetch_dicts(cur, f"SELECT {', '.join(spec['ods_cols'])} FROM {spec['ods']}")
        current_rows = {
            row[spec["nk"]]: row
            for row in _fetch_dicts(cur, f"SELECT * FROM {spec['dw']} WHERE is_current = TRUE")
        }
        ods_keys: set = set()
        for ods in ods_rows:
            key = ods[spec["nk"]]
            ods_keys.add(key)
            payload = {col: ods.get(col) for col in spec["ods_cols"]}
            created_by, updated_by = spec["audit"]
            payload["source_created_by"] = ods.get(created_by)
            payload["source_last_updated_by"] = ods.get(updated_by)
            if pit and spec.get("pit"):
                payload.update(spec["pit"](pit, ods, now))
            current = current_rows.get(key)
            if current is None:
                _close_and_insert(cur, spec, None, payload, now, ods)
                stats["inserted"] += 1
                continue
            if not _changed(current, payload, spec["compare"]):
                stats["unchanged"] += 1
                continue
            _close_and_insert(cur, spec, current, payload, now, ods)
            stats["versioned"] += 1
        stats["expired"] = _expire_deleted(cur, spec, now, ods_keys)
        conn.commit()
        return stats
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


def _pit_case_txn(pit: _PIT, ods: dict, now: datetime) -> dict:
    when = _event_time(ods, now, "transaction_date")
    keys = pit.case_keys(ods.get("case_code"), when)
    # The entry belongs to its bill as the bill stands now, not as it stood on the entry's date: editing a bill makes a new
    # version of it, and the entry's amounts are rewritten with it, so it must follow the version it now agrees with.
    bill = pit.bill.latest(ods.get("bill_code"))
    keys["date_sk"] = _date_sk(ods.get("transaction_date"))
    keys["bill_sk"] = bill["bill_sk"] if bill else None
    return keys


def _pit_expense_txn(pit: _PIT, ods: dict, now: datetime) -> dict:
    when = _event_time(ods, now, "transaction_date")
    keys = pit.case_keys(ods.get("case_code"), when)
    expense = pit.expense.at(ods.get("expense_type_code"), when)
    keys["expense_type_sk"] = expense["expense_type_sk"] if expense else None
    keys["date_sk"] = _date_sk(ods.get("transaction_date"))
    return keys


def _pit_emd(pit: _PIT, ods: dict, now: datetime) -> dict:
    when = _event_time(ods, now, "deposit_date", "instrument_date")
    keys = pit.case_keys(ods.get("case_code"), when)
    keys["date_sk"] = _date_sk(ods.get("deposit_date"))
    return keys


def _pit_employee_txn(pit: _PIT, ods: dict, now: datetime) -> dict:
    when = _event_time(ods, now, "transaction_date")
    emp = pit.employee.at(ods.get("employee_code"), when)
    manager = pit.employee.at(emp.get("manager_code") if emp else None, when)
    # The case the salary was worked at (an attendance register names it), else the employee's own case at the time.
    keys = pit.case_keys(ods.get("case_code") or (emp.get("employee_case_code") if emp else None), when)
    keys["employee_sk"] = emp["employee_sk"] if emp else None
    keys["manager_sk"] = manager["employee_sk"] if manager else None
    keys["date_sk"] = _date_sk(ods.get("transaction_date"))
    return keys


def _pit_car_txn(pit: _PIT, ods: dict, now: datetime) -> dict:
    when = _event_time(ods, now, "driving_date")
    car = pit.car.at(ods.get("car_code"), when)
    driver = pit.employee.at(car.get("car_driven_by") if car else None, when)
    keys = pit.case_keys(car.get("case_code") if car else None, when)
    keys["car_sk"] = car["car_sk"] if car else None
    keys["driver_sk"] = driver["employee_sk"] if driver else None
    keys["date_sk"] = _date_sk(ods.get("driving_date"))
    return keys


def _pit_bill(pit: _PIT, ods: dict, now: datetime) -> dict:
    when = _event_time(ods, now, "bill_date")
    keys = pit.case_keys(ods.get("case_code"), when)
    # The bill carries its own client: the case's client when the bill was saved, and the
    # only link to a client on bills raised before bills were tagged to cases.
    client = pit.client.at(ods.get("client_code"), when)
    if client:
        keys["client_sk"] = client["client_sk"]
    keys["date_sk"] = _date_sk(ods.get("bill_date"))
    return keys


def _status_case(alias: str = "") -> str:
    prefix = f"{alias}." if alias else ""
    return (
        f"CASE WHEN {prefix}is_expired THEN 'Deleted from ODS' WHEN {prefix}is_current THEN 'Current' "
        "ELSE 'Historical' END AS record_status"
    )


# What the loader keeps about a version, besides the table's own columns (see _close_and_insert and _expire_deleted).
_VERSION_COLUMNS = [*_SCD_COLUMNS, "expired_by"]


def _listing(
    alias: str,
    table: str,
    sk: str,
    columns: list[str],
    *,
    order: str,
    names: str = "",
    joins: str = "",
    hide: list[str] | tuple[str, ...] = (),
) -> str:
    """The SQL a warehouse page lists a table with: every column of it (surrogate keys, point-in-time links, version dates
    and audit columns included), the names of the records the keys point at, and the status of the version.

    Every version is listed, the current one first, because a fact's key may point at a version of a client or a case that is
    no longer the current one, and that can only be checked if the older versions can be seen too. ``hide`` leaves out
    columns a reader may not see (the Employee's salary)."""
    shown = ", ".join(f"{alias}.{col}" for col in [sk, *columns, *_VERSION_COLUMNS] if col not in hide)
    extra = f", {names}" if names else ""
    return f"""
            SELECT {shown}{extra},
                   {_status_case(alias)}
            FROM {table} {alias}
            {joins}
            ORDER BY {order}
        """


AUDIT = ("created_by", "last_updated_by")
# Bills keep their own record of who: created_by, and version_by for whoever saved the current version.
BILL_AUDIT = ("created_by", "version_by")


def _dim_spec(
    name: str,
    ods: str,
    dw: str,
    sk: str,
    nk: str,
    attrs: list[str],
    names: str = "",
    joins: str = "",
    private: list[str] | None = None,
) -> dict:
    ods_cols = [nk, *attrs, "created_timestamp", "last_updated_timestamp", *AUDIT]
    dw_cols = [nk, *attrs]
    order = f"d.{nk}, d.effective_from DESC"
    spec: dict = {
        "name": name,
        "kind": "dimension",
        "ods": ods,
        "dw": dw,
        "sk": sk,
        "nk": nk,
        "ods_cols": ods_cols,
        "audit": AUDIT,
        "dw_cols": dw_cols,
        "compare": attrs,
        "preview": _listing("d", dw, sk, dw_cols, order=order, names=names, joins=joins),
    }
    if private:
        # Only people who can change operational data may see these; for everyone else the column is not in the SQL at all.
        spec["private_columns"] = private
        spec["preview_public"] = _listing("d", dw, sk, dw_cols, order=order, names=names, joins=joins, hide=private)
    spec["load"] = lambda s=spec: _sync_scd(s)
    return spec


DIMS: dict[str, dict] = {
    "Business Domain": _dim_spec(
        "Business Domain",
        ods="orion_ods.business_domain",
        dw="orion_dw.dim_business_domain",
        sk="business_domain_sk",
        nk="business_domain_code",
        attrs=["business_domain_name"],
    ),
    "Capability": _dim_spec(
        "Capability",
        ods="orion_ods.capability",
        dw="orion_dw.dim_capability",
        sk="capability_sk",
        nk="capability_code",
        attrs=["capability_name", "capability_head_code"],
        names="h.employee_name AS capability_head_name",
        joins="LEFT JOIN orion_dw.dim_employee h ON h.employee_code = d.capability_head_code AND h.is_current = TRUE",
    ),
    "Expense Type": _dim_spec(
        "Expense Type",
        ods="orion_ods.expense_type",
        dw="orion_dw.dim_expense_type",
        sk="expense_type_sk",
        nk="expense_type_code",
        attrs=["expense_type_name"],
    ),
    "Client": _dim_spec(
        "Client",
        ods="orion_ods.client",
        dw="orion_dw.dim_client",
        sk="client_sk",
        nk="client_code",
        attrs=[
            "client_name",
            "client_status",
            "client_start_date",
            "client_end_date",
            "client_location_state",
            "client_location_city",
            "client_type",
            "firm_priority",
            "client_onboarded",
            "billing_name",
            "gstin",
            "billing_address",
            "client_group_code",
        ],
        names="g.client_name AS client_group_name",
        joins="LEFT JOIN orion_dw.dim_client g ON g.client_code = d.client_group_code AND g.is_current = TRUE",
    ),
    "Case": _dim_spec(
        "Case",
        ods="orion_ods.case",
        dw="orion_dw.dim_case",
        sk="case_sk",
        nk="case_code",
        attrs=[
            "case_name",
            "client_code",
            "capability_code",
            "business_domain_code",
            "opportunity_code",
            "case_start_date",
            "case_end_date",
            "case_status",
            "monthly_expected_revenue",
            "monthly_allowed_km",
            "case_onboarded",
        ],
    ),
    "Opportunity": _dim_spec(
        "Opportunity",
        ods="orion_ods.opportunity",
        dw="orion_dw.dim_opportunity",
        sk="opportunity_sk",
        nk="opportunity_code",
        attrs=[
            "opportunity_name",
            "tender_id",
            "opportunity_case_code",
            "opportunity_start_date",
            "opportunity_end_date",
            "opportunity_status",
            "required_quantity",
            "last_sub_stage_change_date",
            "state",
            "city",
            "reason",
            "workers",
            "opportunity_type",
        ],
    ),
    "Employee": _dim_spec(
        "Employee",
        ods="orion_ods.employee",
        dw="orion_dw.dim_employee",
        sk="employee_sk",
        nk="employee_code",
        attrs=[
            "employee_name",
            "employee_status",
            "emp_start_date",
            "emp_end_date",
            "employee_type",
            "client_facing",
            "employee_designation",
            "manager_code",
            "employee_case_code",
            "monthly_salary",
        ],
        private=["monthly_salary"],
    ),
    "Contact": _dim_spec(
        "Contact",
        ods="orion_ods.contact",
        dw="orion_dw.dim_contact",
        sk="contact_sk",
        nk="contact_code",
        attrs=[
            "client_code",
            "case_code",
            "contact_name",
            "designation",
            "department",
            "contact_role",
            "contact_status",
            "is_primary_contact",
            "contact_start_date",
            "contact_end_date",
            "preferred_contact_method",
            "location_state",
            "location_city",
            "relationship_owner_code",
            "last_contacted_date",
            "next_follow_up_date",
        ],
        names="cl.client_name",
        joins="LEFT JOIN orion_dw.dim_client cl ON cl.client_code = d.client_code AND cl.is_current = TRUE",
    ),
    "Car": _dim_spec(
        "Car",
        ods="orion_ods.car",
        dw="orion_dw.dim_car",
        sk="car_sk",
        nk="car_code",
        attrs=["car_number", "car_model", "case_code", "per_km_price", "car_driven_by"],
    ),
}


def _fact_spec(
    name: str,
    ods: str,
    dw: str,
    sk: str,
    nk: str,
    attrs: list[str],
    dw_cols: list[str],
    compare: list[str],
    pit: Callable,
    order: str,
    names: str = "",
    joins: str = "",
    audit: tuple[str, str] = AUDIT,
) -> dict:
    spec: dict = {
        "name": name,
        "kind": "fact",
        "ods": ods,
        "dw": dw,
        "sk": sk,
        "nk": nk,
        "ods_cols": [nk, *attrs, "created_timestamp", "last_updated_timestamp", *audit],
        "audit": audit,
        "dw_cols": dw_cols,
        "compare": compare,
        "pit": pit,
        "preview": _listing("f", dw, sk, dw_cols, order=f"{order}, f.effective_from DESC", names=names, joins=joins),
    }
    spec["load"] = lambda s=spec: _sync_scd(s)
    return spec


FACTS: dict[str, dict] = {
    "Case Transaction": _fact_spec(
        "Case Transaction",
        ods="orion_ods.case_transaction",
        dw="orion_dw.fact_case_transaction",
        sk="case_transaction_sk",
        nk="transaction_code",
        attrs=[
            "case_code",
            "bill_code",
            "transaction_date",
            "received_date",
            "transaction_status",
            "transaction_amount",
            "tax",
            "gst",
            "amount_after_tax_gst",
            "deducted_amount",
            "transaction_description",
        ],
        dw_cols=[
            "transaction_code",
            "date_sk",
            "case_sk",
            "client_sk",
            "capability_sk",
            "business_domain_sk",
            "bill_sk",
            "case_code",
            "bill_code",
            "transaction_date",
            "received_date",
            "transaction_status",
            "transaction_amount",
            "tax",
            "gst",
            "amount_after_tax_gst",
            "deducted_amount",
            "transaction_description",
        ],
        compare=[
            "date_sk",
            "case_sk",
            "client_sk",
            "capability_sk",
            "business_domain_sk",
            "bill_sk",
            "case_code",
            "bill_code",
            "transaction_date",
            "received_date",
            "transaction_status",
            "transaction_amount",
            "tax",
            "gst",
            "amount_after_tax_gst",
            "deducted_amount",
            "transaction_description",
        ],
        pit=_pit_case_txn,
        order="f.transaction_date DESC NULLS LAST, f.transaction_code",
        names="cs.case_name, cl.client_name",
        joins="LEFT JOIN orion_dw.dim_case cs ON cs.case_sk = f.case_sk LEFT JOIN orion_dw.dim_client cl ON cl.client_sk = f.client_sk",
    ),
    "Expense Transaction": _fact_spec(
        "Expense Transaction",
        ods="orion_ods.expense_transaction",
        dw="orion_dw.fact_expense_transaction",
        sk="expense_transaction_sk",
        nk="expense_code",
        attrs=[
            "case_code",
            "expense_type_code",
            "transaction_date",
            "due_date",
            "vendor_gstin",
            "vendor_invoice_no",
            "transaction_status",
            "is_regular_expense",
            "transaction_amount",
            "tax",
            "gst",
            "amount_after_tax_gst",
            "transaction_description",
        ],
        dw_cols=[
            "expense_code",
            "date_sk",
            "case_sk",
            "client_sk",
            "capability_sk",
            "business_domain_sk",
            "expense_type_sk",
            "case_code",
            "expense_type_code",
            "transaction_date",
            "due_date",
            "vendor_gstin",
            "vendor_invoice_no",
            "transaction_status",
            "is_regular_expense",
            "transaction_amount",
            "tax",
            "gst",
            "amount_after_tax_gst",
            "transaction_description",
        ],
        compare=[
            "date_sk",
            "case_sk",
            "client_sk",
            "capability_sk",
            "business_domain_sk",
            "expense_type_sk",
            "case_code",
            "expense_type_code",
            "transaction_date",
            "due_date",
            "vendor_gstin",
            "vendor_invoice_no",
            "transaction_status",
            "is_regular_expense",
            "transaction_amount",
            "tax",
            "gst",
            "amount_after_tax_gst",
            "transaction_description",
        ],
        pit=_pit_expense_txn,
        order="f.transaction_date DESC NULLS LAST, f.expense_code",
        names="cs.case_name, et.expense_type_name",
        joins="LEFT JOIN orion_dw.dim_case cs ON cs.case_sk = f.case_sk LEFT JOIN orion_dw.dim_expense_type et ON et.expense_type_sk = f.expense_type_sk",
    ),
    "EMD": _fact_spec(
        "EMD",
        ods="orion_ods.emd",
        dw="orion_dw.fact_emd",
        sk="emd_sk",
        nk="emd_code",
        attrs=[
            "case_code",
            "opportunity_code",
            "tender_reference",
            "beneficiary",
            "payment_mode",
            "instrument_number",
            "instrument_date",
            "deposit_date",
            "valid_until",
            "emd_status",
            "refund_due_date",
            "refund_requested_date",
            "refund_received_date",
            "emd_amount",
            "refund_amount",
            "deduction_amount",
        ],
        dw_cols=[
            "emd_code",
            "date_sk",
            "case_sk",
            "client_sk",
            "capability_sk",
            "business_domain_sk",
            "case_code",
            "opportunity_code",
            "tender_reference",
            "beneficiary",
            "payment_mode",
            "instrument_number",
            "instrument_date",
            "deposit_date",
            "valid_until",
            "emd_status",
            "refund_due_date",
            "refund_requested_date",
            "refund_received_date",
            "emd_amount",
            "refund_amount",
            "deduction_amount",
        ],
        compare=[
            "date_sk",
            "case_sk",
            "client_sk",
            "capability_sk",
            "business_domain_sk",
            "case_code",
            "opportunity_code",
            "tender_reference",
            "beneficiary",
            "payment_mode",
            "instrument_number",
            "instrument_date",
            "deposit_date",
            "valid_until",
            "emd_status",
            "refund_due_date",
            "refund_requested_date",
            "refund_received_date",
            "emd_amount",
            "refund_amount",
            "deduction_amount",
        ],
        pit=_pit_emd,
        order="f.deposit_date DESC NULLS LAST, f.emd_code",
        names="cs.case_name, cl.client_name",
        joins="LEFT JOIN orion_dw.dim_case cs ON cs.case_sk = f.case_sk LEFT JOIN orion_dw.dim_client cl ON cl.client_sk = f.client_sk",
    ),
    "Employee Transaction": _fact_spec(
        "Employee Transaction",
        ods="orion_ods.employee_transaction",
        dw="orion_dw.fact_employee_transaction",
        sk="employee_transaction_sk",
        nk="employee_transaction_code",
        attrs=["employee_code", "case_code", "transaction_date", "month_year", "days_worked", "salary_amount", "salary_paid"],
        dw_cols=[
            "employee_transaction_code",
            "date_sk",
            "employee_sk",
            "manager_sk",
            "case_sk",
            "client_sk",
            "capability_sk",
            "business_domain_sk",
            "employee_code",
            "case_code",
            "transaction_date",
            "month_year",
            "days_worked",
            "salary_amount",
            "salary_paid",
        ],
        compare=[
            "date_sk",
            "employee_sk",
            "manager_sk",
            "case_sk",
            "client_sk",
            "capability_sk",
            "business_domain_sk",
            "employee_code",
            "transaction_date",
            "month_year",
            "days_worked",
            "salary_amount",
            "salary_paid",
        ],
        pit=_pit_employee_txn,
        order="f.transaction_date DESC NULLS LAST, f.employee_transaction_code",
        names="e.employee_name, cs.case_name",
        joins="LEFT JOIN orion_dw.dim_employee e ON e.employee_sk = f.employee_sk LEFT JOIN orion_dw.dim_case cs ON cs.case_sk = f.case_sk",
    ),
    "Car Transaction": _fact_spec(
        "Car Transaction",
        ods="orion_ods.car_transaction",
        dw="orion_dw.fact_car_transaction",
        sk="car_transaction_sk",
        nk="car_transaction_code",
        attrs=["car_code", "driving_date", "initial_reading", "final_reading", "driven_km"],
        dw_cols=[
            "car_transaction_code",
            "date_sk",
            "car_sk",
            "driver_sk",
            "case_sk",
            "client_sk",
            "capability_sk",
            "business_domain_sk",
            "car_code",
            "driving_date",
            "initial_reading",
            "final_reading",
            "driven_km",
        ],
        compare=[
            "date_sk",
            "car_sk",
            "driver_sk",
            "case_sk",
            "client_sk",
            "capability_sk",
            "business_domain_sk",
            "car_code",
            "driving_date",
            "initial_reading",
            "final_reading",
            "driven_km",
        ],
        pit=_pit_car_txn,
        order="f.driving_date DESC NULLS LAST, f.car_transaction_code",
        names="c.car_number, c.car_model, e.employee_name AS driver, cs.case_name",
        joins="LEFT JOIN orion_dw.dim_car c ON c.car_sk = f.car_sk LEFT JOIN orion_dw.dim_employee e ON e.employee_sk = f.driver_sk LEFT JOIN orion_dw.dim_case cs ON cs.case_sk = f.case_sk",
    ),
    "Bill": _fact_spec(
        "Bill",
        ods="orion_ods.bill",
        dw="orion_dw.fact_bill",
        sk="bill_sk",
        nk="bill_code",
        attrs=[
            "case_code",
            "client_code",
            "bill_number",
            "version_no",
            "bill_date",
            "service_month",
            "status",
            "gst_paid",
            "gst_paid_amount",
            "epf_amount",
            "esic_amount",
            "epf_paid_amount",
            "esic_paid_amount",
            "credited_taxable",
            "credited_cgst",
            "credited_sgst",
            "credited_amount",
            "taxable_total",
            "cgst_amount",
            "sgst_amount",
            "grand_total",
        ],
        dw_cols=[
            "bill_code",
            "date_sk",
            "case_sk",
            "client_sk",
            "capability_sk",
            "business_domain_sk",
            "case_code",
            "client_code",
            "bill_number",
            "version_no",
            "bill_date",
            "service_month",
            "status",
            "gst_paid",
            "gst_paid_amount",
            "epf_amount",
            "esic_amount",
            "epf_paid_amount",
            "esic_paid_amount",
            "credited_taxable",
            "credited_cgst",
            "credited_sgst",
            "credited_amount",
            "taxable_total",
            "cgst_amount",
            "sgst_amount",
            "grand_total",
        ],
        compare=[
            "date_sk",
            "case_sk",
            "client_sk",
            "capability_sk",
            "business_domain_sk",
            "case_code",
            "client_code",
            "bill_number",
            "version_no",
            "bill_date",
            "service_month",
            "status",
            "gst_paid",
            "gst_paid_amount",
            "epf_amount",
            "esic_amount",
            "epf_paid_amount",
            "esic_paid_amount",
            "credited_taxable",
            "credited_cgst",
            "credited_sgst",
            "credited_amount",
            "taxable_total",
            "cgst_amount",
            "sgst_amount",
            "grand_total",
        ],
        pit=_pit_bill,
        audit=BILL_AUDIT,
        order="f.bill_date DESC NULLS LAST, f.bill_code",
        names="cs.case_name, cl.client_name",
        joins="LEFT JOIN orion_dw.dim_case cs ON cs.case_sk = f.case_sk LEFT JOIN orion_dw.dim_client cl ON cl.client_sk = f.client_sk",
    ),
}

DATE_TABLE = {
    "name": "Date",
    "kind": "dimension",
    "dw": "orion_dw.dim_date",
    "preview": """
        SELECT date_sk, date_value, year_number, quarter_number, month_number, month_name, week_of_year,
               day_of_month, day_of_week, day_name, is_weekend
        FROM orion_dw.dim_date
        WHERE date_value <= CURRENT_DATE
        ORDER BY date_value DESC
    """,
    "load": _sync_date,
}

REFRESH_ORDER = [
    "Date",
    "Business Domain",
    "Capability",
    "Expense Type",
    "Client",
    "Case",
    "Opportunity",
    "Employee",
    "Car",
    "Contact",
    "Bill",
    "Case Transaction",
    "Expense Transaction",
    "EMD",
    "Employee Transaction",
    "Car Transaction",
]

# Columns of a warehouse table that only people who can change operational data may see, and the preview they get
# instead. The warehouse pages (routers/dw_router.py) choose with `dw_preview`.

TABLES: dict[str, dict] = {"Date": DATE_TABLE, **DIMS, **FACTS}
DW_SYNC: dict[str, Callable[[], dict]] = {name: TABLES[name]["load"] for name in REFRESH_ORDER}
DW_TABLES = TABLES


def dw_preview(meta: dict, can_see_private: bool) -> str:
    """The SQL a warehouse page lists a table with: the one without its private columns, unless the reader may see them."""
    return meta["preview"] if can_see_private or not meta.get("private_columns") else meta["preview_public"]


def table_list() -> list[dict]:
    items = [{"name": name, "kind": TABLES[name]["kind"], "rows": 0, "current": 0} for name in REFRESH_ORDER]
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT c.relname
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'orion_dw' AND c.relkind = 'r'
            """
        )
        existing = {row[0] for row in cur.fetchall()}
        for item in items:
            qualified = TABLES[item["name"]].get("dw", "orion_dw.dim_date")
            bare = qualified.split(".")[-1]
            if bare not in existing:
                continue
            if item["name"] == "Date":
                cur.execute("SELECT COUNT(*) FROM orion_dw.dim_date")
                total = int(cur.fetchone()[0])
                item["rows"] = total
                item["current"] = total
            else:
                cur.execute(f"SELECT COUNT(*), COUNT(*) FILTER (WHERE is_current) FROM {qualified}")
                total, current = cur.fetchone()
                item["rows"] = int(total)
                item["current"] = int(current)
    except Exception:
        logger.exception("Could not read warehouse table counts")
    finally:
        cur.close()
        conn.close()
    return items


# --------------------------------------------------------------------------- freshness
#
# Loads are started and recorded by app.etl, which calls each table's ``load`` above. These two
# read that record: what the ODS looks like (so the automatic loader can tell whether anything
# changed), and when the warehouse was last loaded (shown on the dashboards).


def source_fingerprint(cur) -> str:
    """A short digest of what the ODS looks like: row count and newest change per loaded table,
    and how many deletions are on record. It differs after any insert, edit or delete."""
    parts = []
    for name in REFRESH_ORDER:
        table = TABLES[name].get("ods")
        if not table:  # the date dimension is generated, not copied
            continue
        cur.execute(f"SELECT COUNT(*), MAX(last_updated_timestamp) FROM {table}")
        count, newest = cur.fetchone()
        parts.append(f"{table}:{count}:{newest.isoformat() if newest else ''}")
    cur.execute("SELECT COUNT(*) FROM orion_ods.record_deleted")
    parts.append(f"deleted:{cur.fetchone()[0]}")
    return hashlib.sha1("|".join(parts).encode()).hexdigest()


def load_status() -> dict[str, Any]:
    """When the warehouse was last loaded, and how the most recent run went.

    The warehouse is as current as its stalest table, so "last success" is the oldest of every
    table's last successful load. If any table has never been loaded there is no last success.
    """

    def entry(row: tuple | None) -> dict[str, Any] | None:
        if not row:
            return None
        trigger, status, started, finished, error, who = row
        return {
            "trigger": trigger,
            "status": status,
            "started": started.isoformat() if started else None,
            "finished": finished.isoformat() if finished else None,
            "error": error,
            "by": who,
        }

    with db_cursor() as cur:
        cur.execute(
            """
            SELECT t.name, (
                SELECT MAX(s.finished_timestamp)
                  FROM orion_ods.etl_run_step s JOIN orion_ods.etl_run r ON r.id = s.run_id
                 WHERE r.pipeline = 'orion_dw' AND s.status = 'succeeded' AND s.name = t.name
            )
              FROM unnest(%s::text[]) AS t(name)
            """,
            (list(REFRESH_ORDER),),
        )
        loaded = [row[1] for row in cur.fetchall()]
        oldest = None if (not loaded or any(value is None for value in loaded)) else min(loaded)
        success = None
        if oldest is not None:
            cur.execute(
                """
                SELECT r.trigger, r.status, r.started_timestamp, s.finished_timestamp, r.error, u.display_name
                  FROM orion_ods.etl_run_step s
                  JOIN orion_ods.etl_run r ON r.id = s.run_id
                  LEFT JOIN orion_ods.app_user u ON u.id = r.started_by
                 WHERE r.pipeline = 'orion_dw' AND s.status = 'succeeded' AND s.finished_timestamp = %s
                 ORDER BY r.id DESC LIMIT 1
                """,
                (oldest,),
            )
            success = entry(cur.fetchone())
        cur.execute(
            """
            SELECT r.trigger, r.status, r.started_timestamp, r.finished_timestamp, r.error, u.display_name
              FROM orion_ods.etl_run r
              LEFT JOIN orion_ods.app_user u ON u.id = r.started_by
             WHERE r.pipeline = 'orion_dw'
             ORDER BY r.started_timestamp DESC, r.id DESC LIMIT 1
            """
        )
        latest = entry(cur.fetchone())
    return {"last_success": success, "latest": latest}
