"""SCD Type 2 Tally warehouse loads from tally_ods.

Dimensions version when master attributes change. Facts version when the
source voucher or line changes. Fact keys are the dimension versions that
were current on voucher_date (point-in-time).
"""

from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable

import psycopg2
from psycopg2.extras import execute_values

from app.config import db_settings, env
from app import db_grants
from app.database import get_connection

logger = logging.getLogger(__name__)

SCHEMA_FILE = Path(__file__).resolve().parents[2] / ".cursor" / "db" / "tally_dw_schema.sql"
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
]

LEDGER_CLASS_SQL = """
CASE
    WHEN parent_name = 'Sundry Debtors' THEN 'client'
    WHEN parent_name IN ('Direct Incomes', 'Indirect Incomes', 'Sales Accounts') THEN 'income'
    WHEN parent_name IN ('Direct Expenses', 'Indirect Expenses', 'Purchase Accounts') THEN 'expense'
    WHEN parent_name = 'Duties & Taxes' THEN 'tax'
    WHEN parent_name IN ('Cash-in-Hand', 'Bank Accounts') THEN 'cash'
    WHEN parent_name IN (
        'Fixed Assets', 'Current Assets', 'Loans & Advances (Asset)',
        'Deposits (Asset)', 'Investments', 'Stock-in-Hand', 'Misc. Expenses (ASSET)'
    ) THEN 'asset'
    WHEN parent_name IN (
        'Loans (Liability)', 'Bank OD A/c', 'Secured Loans', 'Unsecured Loans'
    ) THEN 'loan'
    WHEN parent_name IN ('Sundry Creditors', 'Current Liabilities', 'Provisions') THEN 'liability'
    WHEN parent_name IN ('Capital Account', 'Reserves & Surplus') THEN 'capital'
    ELSE 'other'
END
"""

INCOME_GROUPS = "('Direct Incomes', 'Indirect Incomes', 'Sales Accounts')"
SALES_TYPES = "('Sales', 'Credit Note', 'Debit Note')"


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
    for key in ("created_timestamp", "voucher_date", "month_start", "starting_from", "books_from"):
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
        return float(value)
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


def ensure_tally_dw_privileges() -> None:
    if not db_grants.needed():
        return
    sql = GRANTS_FILE.read_text(encoding="utf-8")
    settings = _superuser_settings()
    if not settings:
        return
    try:
        _run_sql(sql, settings)
    except Exception:
        logger.exception("Could not apply Tally DW grants as the Postgres superuser")


def ensure_tally_dw_schema() -> None:
    ensure_tally_dw_privileges()
    sql = SCHEMA_FILE.read_text(encoding="utf-8")
    try:
        _run_sql(sql)
        return
    except Exception as exc:
        if "permission denied" not in str(exc).lower():
            raise
        logger.warning("Tally DW schema apply failed; retrying after grants: %s", exc)
    ensure_tally_dw_privileges()
    _run_sql(sql)


def _fetch_dicts(cur, sql: str, params=()) -> list[dict]:
    cur.execute(sql, params)
    cols = [desc[0] for desc in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def _close_and_insert(cur, spec: dict, current: dict | None, payload: dict, now: datetime, ods: dict) -> None:
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
            f"""
            UPDATE {spec["dw"]}
            SET is_expired = TRUE, is_current = FALSE,
                effective_to = COALESCE(effective_to, %s),
                dw_last_updated_timestamp = %s
            WHERE {spec["sk"]} = %s
            """,
            (now, now, row[spec["sk"]]),
        )
        expired += 1
    return expired


class _NamedIndex:
    def __init__(self, rows: list[dict], sk: str, name_col: str = "name"):
        self.sk = sk
        self.by_key: dict[tuple[Any, Any], list[dict]] = {}
        for row in rows:
            key = (row.get("company_name"), row.get(name_col))
            self.by_key.setdefault(key, []).append(row)
        for versions in self.by_key.values():
            versions.sort(
                key=lambda item: _aware(item["effective_from"]) or datetime.min.replace(tzinfo=timezone.utc)
            )

    def at(self, company: Any, name: Any, when: datetime) -> dict | None:
        if not name:
            return None
        versions = self.by_key.get((company, name)) or []
        if not versions and company is not None:
            versions = self.by_key.get((None, name)) or []
        if not versions:
            return None
        when = _aware(when) or when
        for row in reversed(versions):
            start = _aware(row["effective_from"])
            end = _aware(row["effective_to"])
            if start and start <= when and (end is None or end > when):
                return row
        return versions[0]


class _TallyPIT:
    def __init__(self, cur):
        self.company = _NamedIndex(
            [{**row, "name": row["company_name"]} for row in _fetch_dicts(cur, "SELECT * FROM tally_dw.dim_company")],
            "company_dw_sk",
        )
        self.ledger = _NamedIndex(_fetch_dicts(cur, "SELECT * FROM tally_dw.dim_ledger"), "ledger_dw_sk")
        self.account_group = _NamedIndex(
            _fetch_dicts(cur, "SELECT * FROM tally_dw.dim_account_group"),
            "account_group_dw_sk",
        )
        self.voucher_type = _NamedIndex(
            _fetch_dicts(cur, "SELECT * FROM tally_dw.dim_voucher_type"),
            "voucher_type_dw_sk",
        )
        self.cost_centre = _NamedIndex(
            _fetch_dicts(cur, "SELECT * FROM tally_dw.dim_cost_centre"),
            "cost_centre_dw_sk",
        )
        self.cost_category = _NamedIndex(
            _fetch_dicts(cur, "SELECT * FROM tally_dw.dim_cost_category"),
            "cost_category_dw_sk",
        )
        self.stock_item = _NamedIndex(
            _fetch_dicts(cur, "SELECT * FROM tally_dw.dim_stock_item"),
            "stock_item_dw_sk",
        )
        self.godown = _NamedIndex(_fetch_dicts(cur, "SELECT * FROM tally_dw.dim_godown"), "godown_dw_sk")

    def sk(self, index: _NamedIndex, company: Any, name: Any, when: datetime) -> Any:
        row = index.at(company, name, when)
        return row[index.sk] if row else None

    def header_keys(self, ods: dict, when: datetime) -> dict:
        company = ods.get("company_name")
        return {
            "date_sk": _date_sk(ods.get("voucher_date") or ods.get("month_start")),
            "company_sk": self.sk(self.company, company, company, when),
            "voucher_type_sk": self.sk(self.voucher_type, company, ods.get("voucher_type_name"), when),
            "party_ledger_sk": self.sk(self.ledger, company, ods.get("party_ledger_name") or ods.get("client_name"), when),
        }


def _date_sk(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        value = value.date()
    if not isinstance(value, date):
        return None
    return int(value.strftime("%Y%m%d"))


def _event_time(ods: dict, now: datetime) -> datetime:
    for key in ("voucher_date", "month_start", "effective_date"):
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
#: Dates in the books are not trusted to size the calendar: a mistyped year must not add a century of rows.
CALENDAR_LIMITS = (date(1990, 1, 1), date(2100, 12, 31))


def calendar_bounds(first: date, last: date, found: list[tuple[date | None, date | None]]) -> tuple[date, date]:
    """The calendar's first and last day: at least ``first``..``last``, and wide enough for every voucher date (within
    CALENDAR_LIMITS). The first day is the first of the month, because monthly facts are dated on the month's first day."""
    low, high = CALENDAR_LIMITS
    start, end = first, last
    for earliest, latest in found:
        if earliest is not None:
            start = min(start, max(earliest, low).replace(day=1))
        if latest is not None:
            end = max(end, min(latest, high))
    return start, end


def _calendar_bounds(cur) -> tuple[date, date]:
    cur.execute("SELECT MIN(voucher_date), MAX(voucher_date) FROM tally_ods.voucher")
    return calendar_bounds(date(CALENDAR_FIRST_YEAR, 1, 1), date(_utcnow().year + 3, 12, 31), [cur.fetchone()])


def _sync_date() -> dict[str, int]:
    conn = get_connection()
    cur = conn.cursor()
    stats = dict(EMPTY_STATS)
    try:
        start, end = _calendar_bounds(cur)
        cur.execute("SELECT date_sk FROM tally_dw.dim_date")
        have = {row[0] for row in cur.fetchall()}
        rows = []
        day = start
        while day <= end:
            sk = int(day.strftime("%Y%m%d"))
            if sk not in have:
                fy_start = day.year if day.month >= 4 else day.year - 1
                fy_month = day.month - 3 if day.month >= 4 else day.month + 9
                last = (day.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
                rows.append(
                    (
                        sk,
                        day,
                        day.year,
                        (day.month - 1) // 3 + 1,
                        day.month,
                        day.strftime("%B"),
                        day.strftime("%Y-%m"),
                        fy_start,
                        fy_start + 1,
                        fy_month,
                        int(day.strftime("%U")),
                        day.day,
                        day.isoweekday(),
                        day.strftime("%A"),
                        day.isoweekday() >= 6,
                        day == last,
                    )
                )
            day += timedelta(days=1)
        if rows:
            execute_values(
                cur,
                """
                INSERT INTO tally_dw.dim_date (
                    date_sk, date_value, year_number, quarter_number, month_number,
                    month_name, month_year, fy_start_year, fy_end_year, fy_month_number,
                    week_of_year, day_of_month, day_of_week, day_name, is_weekend, is_month_end
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
        pit = _TallyPIT(cur) if spec.get("pit") else None
        ods_rows = _fetch_dicts(cur, spec["ods_sql"])
        current_rows = {
            row[spec["nk"]]: row
            for row in _fetch_dicts(cur, f"SELECT * FROM {spec['dw']} WHERE is_current = TRUE")
        }
        ods_keys: set = set()
        for ods in ods_rows:
            key = ods[spec["nk"]]
            if key is None:
                continue
            ods_keys.add(key)
            payload = dict(ods)
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


def _status_case(alias: str = "") -> str:
    prefix = f"{alias}." if alias else ""
    return (
        f"CASE WHEN {prefix}is_expired THEN 'Deleted from ODS' "
        f"WHEN {prefix}is_current THEN 'Current' ELSE 'Historical' END AS record_status"
    )


def _dim_spec(
    name: str,
    dw: str,
    sk: str,
    ods_sql: str,
    dw_cols: list[str],
    compare: list[str],
    preview: str,
) -> dict:
    spec: dict = {
        "name": name,
        "kind": "dimension",
        "dw": dw,
        "sk": sk,
        "nk": "source_sk",
        "ods_sql": ods_sql,
        "dw_cols": dw_cols,
        "compare": compare,
        "preview": preview,
    }
    spec["load"] = lambda s=spec: _sync_scd(s)
    return spec


def _master_select(table: str, pk: str, extra: str = "") -> str:
    return f"""
        SELECT {pk} AS source_sk, natural_key, company_name, tally_guid,
               tally_master_id, tally_alter_id, name{extra},
               created_timestamp, last_updated_timestamp
        FROM {table}
    """


def _pit_header(pit: _TallyPIT, ods: dict, now: datetime) -> dict:
    return pit.header_keys(ods, _event_time(ods, now))


def _pit_ledger_line(pit: _TallyPIT, ods: dict, now: datetime) -> dict:
    when = _event_time(ods, now)
    keys = pit.header_keys(ods, when)
    company = ods.get("company_name")
    keys["line_ledger_sk"] = pit.sk(pit.ledger, company, ods.get("ledger_name"), when)
    keys["account_group_sk"] = pit.sk(pit.account_group, company, ods.get("ledger_group"), when)
    return keys


def _pit_inventory(pit: _TallyPIT, ods: dict, now: datetime) -> dict:
    when = _event_time(ods, now)
    keys = pit.header_keys(ods, when)
    company = ods.get("company_name")
    keys["stock_item_sk"] = pit.sk(pit.stock_item, company, ods.get("stock_item_name"), when)
    keys["godown_sk"] = pit.sk(pit.godown, company, ods.get("godown_name"), when)
    return keys


def _pit_bill(pit: _TallyPIT, ods: dict, now: datetime) -> dict:
    when = _event_time(ods, now)
    keys = pit.header_keys(ods, when)
    keys["line_ledger_sk"] = pit.sk(pit.ledger, ods.get("company_name"), ods.get("ledger_name"), when)
    return keys


def _pit_cost_centre(pit: _TallyPIT, ods: dict, now: datetime) -> dict:
    when = _event_time(ods, now)
    keys = pit.header_keys(ods, when)
    company = ods.get("company_name")
    keys["line_ledger_sk"] = pit.sk(pit.ledger, company, ods.get("ledger_name"), when)
    keys["cost_centre_sk"] = pit.sk(pit.cost_centre, company, ods.get("cost_centre_name"), when)
    keys["cost_category_sk"] = pit.sk(pit.cost_category, company, ods.get("category_name"), when)
    return keys


def _pit_client_month(pit: _TallyPIT, ods: dict, now: datetime) -> dict:
    when = _event_time(ods, now)
    company = ods.get("company_name")
    return {
        "date_sk": _date_sk(ods.get("month_start")),
        "company_sk": pit.sk(pit.company, company, company, when),
        "client_sk": pit.sk(pit.ledger, company, ods.get("client_name"), when),
    }


DATE_TABLE = {
    "name": "Date",
    "kind": "dimension",
    "dw": "tally_dw.dim_date",
    "preview": """
        SELECT date_sk, date_value, month_year, fy_start_year, fy_month_number,
               month_name, day_name, is_weekend, is_month_end
        FROM tally_dw.dim_date
        WHERE date_value <= CURRENT_DATE
        ORDER BY date_value DESC
    """,
    "load": _sync_date,
}


def _dim_preview(table: str, cols: str) -> str:
    return f"""
        SELECT {cols},
               {_status_case()}, effective_from, COALESCE(effective_to::TEXT, 'Open') AS effective_to
        FROM {table}
        WHERE is_current = TRUE
        ORDER BY name
    """


DIMS: dict[str, dict] = {
    "Company": _dim_spec(
        "Company",
        dw="tally_dw.dim_company",
        sk="company_dw_sk",
        ods_sql="""
            SELECT company_sk AS source_sk, natural_key, company_name, tally_guid,
                   starting_from, books_from, state_name, country_name, gst_on, gst_tax_unit_count,
                   created_timestamp, last_updated_timestamp
            FROM tally_ods.company
        """,
        dw_cols=[
            "source_sk",
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
        compare=[
            "company_name",
            "tally_guid",
            "starting_from",
            "books_from",
            "state_name",
            "country_name",
            "gst_on",
            "gst_tax_unit_count",
        ],
        preview=f"""
            SELECT company_dw_sk, source_sk, company_name, state_name, gst_on, starting_from, books_from,
                   {_status_case()}, effective_from, COALESCE(effective_to::TEXT, 'Open') AS effective_to
            FROM tally_dw.dim_company
            WHERE is_current = TRUE
            ORDER BY company_name
        """,
    ),
    "Account Group": _dim_spec(
        "Account Group",
        dw="tally_dw.dim_account_group",
        sk="account_group_dw_sk",
        ods_sql=_master_select("tally_ods.account_group", "account_group_sk", ", parent_name"),
        dw_cols=[
            "source_sk",
            "natural_key",
            "company_name",
            "tally_guid",
            "tally_master_id",
            "tally_alter_id",
            "name",
            "parent_name",
        ],
        compare=["name", "parent_name", "tally_guid", "tally_alter_id"],
        preview=_dim_preview(
            "tally_dw.dim_account_group",
            "account_group_dw_sk, source_sk, name, parent_name, company_name",
        ),
    ),
    "Ledger": _dim_spec(
        "Ledger",
        dw="tally_dw.dim_ledger",
        sk="ledger_dw_sk",
        ods_sql=f"""
            SELECT ledger_sk AS source_sk, natural_key, company_name, tally_guid,
                   tally_master_id, tally_alter_id, name, parent_name,
                   {LEDGER_CLASS_SQL} AS ledger_class,
                   mailing_name, opening_balance, closing_balance,
                   is_bill_wise, is_revenue, tax_type, country_name, pincode,
                   created_timestamp, last_updated_timestamp
            FROM tally_ods.ledger
        """,
        dw_cols=[
            "source_sk",
            "natural_key",
            "company_name",
            "tally_guid",
            "tally_master_id",
            "tally_alter_id",
            "name",
            "parent_name",
            "ledger_class",
            "mailing_name",
            "opening_balance",
            "closing_balance",
            "is_bill_wise",
            "is_revenue",
            "tax_type",
            "country_name",
            "pincode",
        ],
        compare=[
            "name",
            "parent_name",
            "ledger_class",
            "mailing_name",
            "opening_balance",
            "closing_balance",
            "is_bill_wise",
            "is_revenue",
            "tax_type",
            "country_name",
            "pincode",
            "tally_alter_id",
        ],
        preview=f"""
            SELECT ledger_dw_sk, source_sk, name, ledger_class, parent_name, mailing_name,
                   closing_balance, pincode, company_name,
                   {_status_case()}, effective_from, COALESCE(effective_to::TEXT, 'Open') AS effective_to
            FROM tally_dw.dim_ledger
            WHERE is_current = TRUE
            ORDER BY ledger_class, name
        """,
    ),
    "Cost Category": _dim_spec(
        "Cost Category",
        dw="tally_dw.dim_cost_category",
        sk="cost_category_dw_sk",
        ods_sql=_master_select("tally_ods.cost_category", "cost_category_sk"),
        dw_cols=["source_sk", "natural_key", "company_name", "tally_guid", "tally_master_id", "tally_alter_id", "name"],
        compare=["name", "tally_alter_id"],
        preview=_dim_preview("tally_dw.dim_cost_category", "cost_category_dw_sk, source_sk, name, company_name"),
    ),
    "Cost Centre": _dim_spec(
        "Cost Centre",
        dw="tally_dw.dim_cost_centre",
        sk="cost_centre_dw_sk",
        ods_sql=_master_select("tally_ods.cost_centre", "cost_centre_sk", ", parent_name, category_name"),
        dw_cols=[
            "source_sk",
            "natural_key",
            "company_name",
            "tally_guid",
            "tally_master_id",
            "tally_alter_id",
            "name",
            "parent_name",
            "category_name",
        ],
        compare=["name", "parent_name", "category_name", "tally_alter_id"],
        preview=_dim_preview(
            "tally_dw.dim_cost_centre",
            "cost_centre_dw_sk, source_sk, name, category_name, parent_name, company_name",
        ),
    ),
    "Voucher Type": _dim_spec(
        "Voucher Type",
        dw="tally_dw.dim_voucher_type",
        sk="voucher_type_dw_sk",
        ods_sql=_master_select("tally_ods.voucher_type", "voucher_type_sk", ", parent_name"),
        dw_cols=[
            "source_sk",
            "natural_key",
            "company_name",
            "tally_guid",
            "tally_master_id",
            "tally_alter_id",
            "name",
            "parent_name",
        ],
        compare=["name", "parent_name", "tally_alter_id"],
        preview=_dim_preview(
            "tally_dw.dim_voucher_type",
            "voucher_type_dw_sk, source_sk, name, parent_name, company_name",
        ),
    ),
    "Currency": _dim_spec(
        "Currency",
        dw="tally_dw.dim_currency",
        sk="currency_dw_sk",
        ods_sql="""
            SELECT currency_sk AS source_sk, natural_key, company_name, tally_guid,
                   name, original_name, mailing_name,
                   created_timestamp, last_updated_timestamp
            FROM tally_ods.currency
        """,
        dw_cols=["source_sk", "natural_key", "company_name", "tally_guid", "name", "original_name", "mailing_name"],
        compare=["name", "original_name", "mailing_name"],
        preview=_dim_preview(
            "tally_dw.dim_currency",
            "currency_dw_sk, source_sk, name, original_name, mailing_name, company_name",
        ),
    ),
    "Unit": _dim_spec(
        "Unit",
        dw="tally_dw.dim_unit",
        sk="unit_dw_sk",
        ods_sql="""
            SELECT unit_sk AS source_sk, natural_key, company_name, tally_guid, tally_master_id,
                   name, original_name, decimal_places,
                   created_timestamp, last_updated_timestamp
            FROM tally_ods.unit
        """,
        dw_cols=[
            "source_sk",
            "natural_key",
            "company_name",
            "tally_guid",
            "tally_master_id",
            "name",
            "original_name",
            "decimal_places",
        ],
        compare=["name", "original_name", "decimal_places"],
        preview=_dim_preview(
            "tally_dw.dim_unit",
            "unit_dw_sk, source_sk, name, original_name, decimal_places, company_name",
        ),
    ),
    "Godown": _dim_spec(
        "Godown",
        dw="tally_dw.dim_godown",
        sk="godown_dw_sk",
        ods_sql=_master_select("tally_ods.godown", "godown_sk", ", parent_name"),
        dw_cols=[
            "source_sk",
            "natural_key",
            "company_name",
            "tally_guid",
            "tally_master_id",
            "tally_alter_id",
            "name",
            "parent_name",
        ],
        compare=["name", "parent_name", "tally_alter_id"],
        preview=_dim_preview("tally_dw.dim_godown", "godown_dw_sk, source_sk, name, parent_name, company_name"),
    ),
    "Stock Group": _dim_spec(
        "Stock Group",
        dw="tally_dw.dim_stock_group",
        sk="stock_group_dw_sk",
        ods_sql=_master_select("tally_ods.stock_group", "stock_group_sk", ", parent_name"),
        dw_cols=[
            "source_sk",
            "natural_key",
            "company_name",
            "tally_guid",
            "tally_master_id",
            "tally_alter_id",
            "name",
            "parent_name",
        ],
        compare=["name", "parent_name", "tally_alter_id"],
        preview=_dim_preview(
            "tally_dw.dim_stock_group",
            "stock_group_dw_sk, source_sk, name, parent_name, company_name",
        ),
    ),
    "Stock Category": _dim_spec(
        "Stock Category",
        dw="tally_dw.dim_stock_category",
        sk="stock_category_dw_sk",
        ods_sql=_master_select("tally_ods.stock_category", "stock_category_sk", ", parent_name"),
        dw_cols=[
            "source_sk",
            "natural_key",
            "company_name",
            "tally_guid",
            "tally_master_id",
            "tally_alter_id",
            "name",
            "parent_name",
        ],
        compare=["name", "parent_name", "tally_alter_id"],
        preview=_dim_preview(
            "tally_dw.dim_stock_category",
            "stock_category_dw_sk, source_sk, name, parent_name, company_name",
        ),
    ),
    "Stock Item": _dim_spec(
        "Stock Item",
        dw="tally_dw.dim_stock_item",
        sk="stock_item_dw_sk",
        ods_sql=_master_select(
            "tally_ods.stock_item",
            "stock_item_sk",
            ", parent_name, base_units, closing_balance",
        ),
        dw_cols=[
            "source_sk",
            "natural_key",
            "company_name",
            "tally_guid",
            "tally_master_id",
            "tally_alter_id",
            "name",
            "parent_name",
            "base_units",
            "closing_balance",
        ],
        compare=["name", "parent_name", "base_units", "closing_balance", "tally_alter_id"],
        preview=_dim_preview(
            "tally_dw.dim_stock_item",
            "stock_item_dw_sk, source_sk, name, parent_name, base_units, closing_balance, company_name",
        ),
    ),
    "GST Classification": _dim_spec(
        "GST Classification",
        dw="tally_dw.dim_gst_classification",
        sk="gst_classification_dw_sk",
        ods_sql="""
            SELECT gst_classification_sk AS source_sk, natural_key, company_name, tally_guid,
                   tally_master_id, name, hsn_code, gst_rate,
                   created_timestamp, last_updated_timestamp
            FROM tally_ods.gst_classification
        """,
        dw_cols=[
            "source_sk",
            "natural_key",
            "company_name",
            "tally_guid",
            "tally_master_id",
            "name",
            "hsn_code",
            "gst_rate",
        ],
        compare=["name", "hsn_code", "gst_rate"],
        preview=_dim_preview(
            "tally_dw.dim_gst_classification",
            "gst_classification_dw_sk, source_sk, name, hsn_code, gst_rate, company_name",
        ),
    ),
    "Tax Unit": _dim_spec(
        "Tax Unit",
        dw="tally_dw.dim_tax_unit",
        sk="tax_unit_dw_sk",
        ods_sql="""
            SELECT tax_unit_sk AS source_sk, natural_key, company_name, tally_guid,
                   tally_master_id, name,
                   created_timestamp, last_updated_timestamp
            FROM tally_ods.tax_unit
        """,
        dw_cols=["source_sk", "natural_key", "company_name", "tally_guid", "tally_master_id", "name"],
        compare=["name"],
        preview=_dim_preview("tally_dw.dim_tax_unit", "tax_unit_dw_sk, source_sk, name, company_name"),
    ),
    "Attendance Type": _dim_spec(
        "Attendance Type",
        dw="tally_dw.dim_attendance_type",
        sk="attendance_type_dw_sk",
        ods_sql="""
            SELECT attendance_type_sk AS source_sk, natural_key, company_name, tally_guid,
                   tally_master_id, name, parent_name,
                   created_timestamp, last_updated_timestamp
            FROM tally_ods.attendance_type
        """,
        dw_cols=[
            "source_sk",
            "natural_key",
            "company_name",
            "tally_guid",
            "tally_master_id",
            "name",
            "parent_name",
        ],
        compare=["name", "parent_name"],
        preview=_dim_preview(
            "tally_dw.dim_attendance_type",
            "attendance_type_dw_sk, source_sk, name, parent_name, company_name",
        ),
    ),
}


def _fact_spec(
    name: str,
    dw: str,
    sk: str,
    nk: str,
    ods_sql: str,
    dw_cols: list[str],
    compare: list[str],
    pit: Callable,
    preview: str,
) -> dict:
    spec: dict = {
        "name": name,
        "kind": "fact",
        "dw": dw,
        "sk": sk,
        "nk": nk,
        "ods_sql": ods_sql,
        "dw_cols": dw_cols,
        "compare": compare,
        "pit": pit,
        "preview": preview,
    }
    spec["load"] = lambda s=spec: _sync_scd(s)
    return spec


VOUCHER_MEASURES_SQL = f"""
    SELECT
        v.voucher_sk AS source_voucher_sk,
        v.natural_key,
        v.company_name,
        v.voucher_type_name,
        v.voucher_number,
        v.voucher_date,
        v.effective_date,
        v.party_ledger_name,
        v.narration,
        v.reference,
        v.tally_guid,
        v.remote_id,
        v.is_invoice,
        v.is_optional,
        v.voucher_type_name IN {SALES_TYPES} AS is_sales_document,
        COUNT(e.voucher_ledger_entry_sk)::INTEGER AS ledger_line_count,
        COALESCE(ROUND(SUM(-e.amount) FILTER (WHERE e.is_party_ledger), 2), 0) AS invoice_value_incl_gst,
        COALESCE(ROUND(SUM(e.amount) FILTER (WHERE l.parent_name IN {INCOME_GROUPS}), 2), 0) AS revenue_ex_gst,
        COALESCE(ROUND(SUM(e.amount) FILTER (WHERE l.parent_name = 'Duties & Taxes'), 2), 0) AS gst,
        COALESCE(ROUND(SUM(e.amount) FILTER (WHERE e.ledger_name = 'CGST'), 2), 0) AS cgst,
        COALESCE(ROUND(SUM(e.amount) FILTER (WHERE e.ledger_name = 'SGST'), 2), 0) AS sgst,
        COALESCE(ROUND(SUM(e.amount) FILTER (WHERE e.ledger_name = 'Man Power Supply'), 2), 0) AS manpower_supply,
        COALESCE(ROUND(SUM(e.amount) FILTER (WHERE e.ledger_name ILIKE 'Rental Service of Vehicles%%'), 2), 0) AS vehicle_rental,
        COALESCE(ROUND(SUM(e.amount) FILTER (WHERE e.ledger_name = 'Service Charges Recivable'), 2), 0) AS service_charges,
        COALESCE(ROUND(SUM(e.amount) FILTER (WHERE e.ledger_name ILIKE 'EPF%%'), 2), 0) AS epf_billed,
        COALESCE(ROUND(SUM(e.amount) FILTER (WHERE e.ledger_name ILIKE 'ESIC%%'), 2), 0) AS esic_billed,
        COALESCE(ROUND(SUM(e.amount) FILTER (
            WHERE e.ledger_name ILIKE 'SECURITY%%' OR e.ledger_name ILIKE '%%Science Collage%%'
        ), 2), 0) AS other_income,
        v.created_timestamp,
        v.last_updated_timestamp
    FROM tally_ods.voucher v
    LEFT JOIN tally_ods.voucher_ledger_entry e ON e.voucher_sk = v.voucher_sk
    LEFT JOIN tally_ods.ledger l
      ON l.name = e.ledger_name AND l.company_name = e.company_name
    WHERE COALESCE(v.is_optional, FALSE) = FALSE
    GROUP BY v.voucher_sk
"""

VOUCHER_DW_COLS = [
    "source_voucher_sk",
    "natural_key",
    "date_sk",
    "company_sk",
    "voucher_type_sk",
    "party_ledger_sk",
    "company_name",
    "voucher_type_name",
    "voucher_number",
    "voucher_date",
    "effective_date",
    "party_ledger_name",
    "narration",
    "reference",
    "tally_guid",
    "remote_id",
    "is_invoice",
    "is_optional",
    "is_sales_document",
    "ledger_line_count",
    "invoice_value_incl_gst",
    "revenue_ex_gst",
    "gst",
    "cgst",
    "sgst",
    "manpower_supply",
    "vehicle_rental",
    "service_charges",
    "epf_billed",
    "esic_billed",
    "other_income",
]

VOUCHER_COMPARE = [
    col
    for col in VOUCHER_DW_COLS
    if col not in {"source_voucher_sk", "natural_key", "tally_guid", "remote_id"}
]


FACTS: dict[str, dict] = {
    "Voucher": _fact_spec(
        "Voucher",
        dw="tally_dw.fact_voucher",
        sk="voucher_dw_sk",
        nk="source_voucher_sk",
        ods_sql=VOUCHER_MEASURES_SQL,
        dw_cols=VOUCHER_DW_COLS,
        compare=VOUCHER_COMPARE,
        pit=_pit_header,
        preview=f"""
            SELECT f.voucher_dw_sk, f.voucher_date, f.voucher_number, f.voucher_type_name,
                   f.party_ledger_name, f.invoice_value_incl_gst, f.revenue_ex_gst, f.gst,
                   f.is_sales_document, cl.name AS client_name,
                   {_status_case('f')}
            FROM tally_dw.fact_voucher f
            LEFT JOIN tally_dw.dim_ledger cl ON cl.ledger_dw_sk = f.party_ledger_sk
            WHERE f.is_current = TRUE
            ORDER BY f.voucher_date DESC NULLS LAST, f.voucher_number
        """,
    ),
    "Ledger Line": _fact_spec(
        "Ledger Line",
        dw="tally_dw.fact_ledger_line",
        sk="ledger_line_dw_sk",
        nk="source_ledger_entry_sk",
        ods_sql=f"""
            SELECT
                e.voucher_ledger_entry_sk AS source_ledger_entry_sk,
                e.natural_key,
                e.voucher_sk AS source_voucher_sk,
                v.company_name,
                v.voucher_number,
                v.voucher_date,
                v.voucher_type_name,
                v.party_ledger_name,
                e.line_no,
                e.ledger_name,
                l.parent_name AS ledger_group,
                {LEDGER_CLASS_SQL.replace("parent_name", "l.parent_name")} AS ledger_class,
                CASE
                    WHEN e.is_party_ledger THEN 'party'
                    WHEN l.parent_name IN {INCOME_GROUPS} THEN 'income'
                    WHEN l.parent_name = 'Duties & Taxes' THEN 'tax'
                    WHEN l.parent_name IN ('Direct Expenses', 'Indirect Expenses') THEN 'expense'
                    ELSE 'other'
                END AS line_role,
                e.amount,
                CASE WHEN e.is_deemed_positive THEN ABS(e.amount) ELSE 0 END AS debit_amount,
                CASE WHEN COALESCE(e.is_deemed_positive, FALSE) = FALSE THEN ABS(e.amount) ELSE 0 END AS credit_amount,
                e.is_deemed_positive,
                e.is_party_ledger,
                e.created_timestamp,
                e.last_updated_timestamp
            FROM tally_ods.voucher_ledger_entry e
            JOIN tally_ods.voucher v ON v.voucher_sk = e.voucher_sk
            LEFT JOIN tally_ods.ledger l
              ON l.name = e.ledger_name AND l.company_name = e.company_name
            WHERE COALESCE(v.is_optional, FALSE) = FALSE
        """,
        dw_cols=[
            "source_ledger_entry_sk",
            "natural_key",
            "source_voucher_sk",
            "date_sk",
            "company_sk",
            "voucher_type_sk",
            "party_ledger_sk",
            "line_ledger_sk",
            "account_group_sk",
            "company_name",
            "voucher_number",
            "voucher_date",
            "voucher_type_name",
            "party_ledger_name",
            "line_no",
            "ledger_name",
            "ledger_group",
            "ledger_class",
            "line_role",
            "amount",
            "debit_amount",
            "credit_amount",
            "is_deemed_positive",
            "is_party_ledger",
        ],
        compare=[
            "date_sk",
            "company_sk",
            "voucher_type_sk",
            "party_ledger_sk",
            "line_ledger_sk",
            "account_group_sk",
            "voucher_number",
            "voucher_date",
            "voucher_type_name",
            "party_ledger_name",
            "line_no",
            "ledger_name",
            "ledger_group",
            "ledger_class",
            "line_role",
            "amount",
            "debit_amount",
            "credit_amount",
            "is_deemed_positive",
            "is_party_ledger",
        ],
        pit=_pit_ledger_line,
        preview=f"""
            SELECT f.ledger_line_dw_sk, f.voucher_date, f.voucher_number, f.line_no,
                   f.ledger_name, f.line_role, f.ledger_class, f.amount, f.debit_amount, f.credit_amount,
                   f.party_ledger_name, {_status_case('f')}
            FROM tally_dw.fact_ledger_line f
            WHERE f.is_current = TRUE
            ORDER BY f.voucher_date DESC NULLS LAST, f.voucher_number, f.line_no
        """,
    ),
    "Inventory Line": _fact_spec(
        "Inventory Line",
        dw="tally_dw.fact_inventory_line",
        sk="inventory_line_dw_sk",
        nk="source_inventory_entry_sk",
        ods_sql="""
            SELECT
                i.voucher_inventory_entry_sk AS source_inventory_entry_sk,
                i.natural_key,
                i.voucher_sk AS source_voucher_sk,
                v.company_name,
                v.voucher_number,
                v.voucher_date,
                v.voucher_type_name,
                v.party_ledger_name,
                i.line_no,
                i.stock_item_name,
                i.godown_name,
                i.actual_qty,
                i.billed_qty,
                i.rate,
                i.amount,
                i.created_timestamp,
                i.last_updated_timestamp
            FROM tally_ods.voucher_inventory_entry i
            JOIN tally_ods.voucher v ON v.voucher_sk = i.voucher_sk
            WHERE COALESCE(v.is_optional, FALSE) = FALSE
        """,
        dw_cols=[
            "source_inventory_entry_sk",
            "natural_key",
            "source_voucher_sk",
            "date_sk",
            "company_sk",
            "voucher_type_sk",
            "party_ledger_sk",
            "stock_item_sk",
            "godown_sk",
            "company_name",
            "voucher_number",
            "voucher_date",
            "party_ledger_name",
            "line_no",
            "stock_item_name",
            "godown_name",
            "actual_qty",
            "billed_qty",
            "rate",
            "amount",
        ],
        compare=[
            "date_sk",
            "company_sk",
            "voucher_type_sk",
            "party_ledger_sk",
            "stock_item_sk",
            "godown_sk",
            "voucher_number",
            "voucher_date",
            "party_ledger_name",
            "line_no",
            "stock_item_name",
            "godown_name",
            "actual_qty",
            "billed_qty",
            "rate",
            "amount",
        ],
        pit=_pit_inventory,
        preview=f"""
            SELECT f.inventory_line_dw_sk, f.voucher_date, f.voucher_number, f.stock_item_name,
                   f.godown_name, f.billed_qty, f.rate, f.amount, f.party_ledger_name,
                   {_status_case('f')}
            FROM tally_dw.fact_inventory_line f
            WHERE f.is_current = TRUE
            ORDER BY f.voucher_date DESC NULLS LAST, f.voucher_number, f.line_no
        """,
    ),
    "Bill Allocation": _fact_spec(
        "Bill Allocation",
        dw="tally_dw.fact_bill_allocation",
        sk="bill_allocation_dw_sk",
        nk="source_bill_allocation_sk",
        ods_sql="""
            SELECT
                b.voucher_bill_allocation_sk AS source_bill_allocation_sk,
                b.natural_key,
                b.voucher_sk AS source_voucher_sk,
                b.voucher_ledger_entry_sk AS source_ledger_entry_sk,
                v.company_name,
                v.voucher_number,
                v.voucher_date,
                v.voucher_type_name,
                v.party_ledger_name,
                e.ledger_name,
                b.line_no,
                b.bill_name,
                b.bill_type,
                b.amount,
                b.created_timestamp,
                b.last_updated_timestamp
            FROM tally_ods.voucher_bill_allocation b
            JOIN tally_ods.voucher v ON v.voucher_sk = b.voucher_sk
            LEFT JOIN tally_ods.voucher_ledger_entry e
              ON e.voucher_ledger_entry_sk = b.voucher_ledger_entry_sk
            WHERE COALESCE(v.is_optional, FALSE) = FALSE
        """,
        dw_cols=[
            "source_bill_allocation_sk",
            "natural_key",
            "source_voucher_sk",
            "source_ledger_entry_sk",
            "date_sk",
            "company_sk",
            "voucher_type_sk",
            "party_ledger_sk",
            "line_ledger_sk",
            "company_name",
            "voucher_number",
            "voucher_date",
            "party_ledger_name",
            "ledger_name",
            "line_no",
            "bill_name",
            "bill_type",
            "amount",
        ],
        compare=[
            "date_sk",
            "company_sk",
            "voucher_type_sk",
            "party_ledger_sk",
            "line_ledger_sk",
            "voucher_number",
            "voucher_date",
            "party_ledger_name",
            "ledger_name",
            "line_no",
            "bill_name",
            "bill_type",
            "amount",
        ],
        pit=_pit_bill,
        preview=f"""
            SELECT f.bill_allocation_dw_sk, f.voucher_date, f.voucher_number, f.bill_name, f.bill_type,
                   f.amount, f.party_ledger_name, f.ledger_name, {_status_case('f')}
            FROM tally_dw.fact_bill_allocation f
            WHERE f.is_current = TRUE
            ORDER BY f.voucher_date DESC NULLS LAST, f.voucher_number, f.line_no
        """,
    ),
    "Cost Centre Allocation": _fact_spec(
        "Cost Centre Allocation",
        dw="tally_dw.fact_cost_centre_allocation",
        sk="cost_centre_allocation_dw_sk",
        nk="source_cost_centre_alloc_sk",
        ods_sql=f"""
            SELECT
                a.voucher_cost_centre_allocation_sk AS source_cost_centre_alloc_sk,
                a.natural_key,
                a.voucher_sk AS source_voucher_sk,
                a.voucher_ledger_entry_sk AS source_ledger_entry_sk,
                v.company_name,
                v.voucher_number,
                v.voucher_date,
                v.voucher_type_name,
                v.party_ledger_name,
                e.ledger_name,
                l.parent_name AS ledger_group,
                {LEDGER_CLASS_SQL.replace("parent_name", "l.parent_name")} AS ledger_class,
                a.line_no,
                a.category_name,
                a.cost_centre_name,
                a.amount,
                a.created_timestamp,
                a.last_updated_timestamp
            FROM tally_ods.voucher_cost_centre_allocation a
            JOIN tally_ods.voucher v ON v.voucher_sk = a.voucher_sk
            LEFT JOIN tally_ods.voucher_ledger_entry e
              ON e.voucher_ledger_entry_sk = a.voucher_ledger_entry_sk
            LEFT JOIN tally_ods.ledger l
              ON l.name = e.ledger_name AND l.company_name = e.company_name
            WHERE COALESCE(v.is_optional, FALSE) = FALSE
        """,
        dw_cols=[
            "source_cost_centre_alloc_sk",
            "natural_key",
            "source_voucher_sk",
            "source_ledger_entry_sk",
            "date_sk",
            "company_sk",
            "voucher_type_sk",
            "party_ledger_sk",
            "line_ledger_sk",
            "cost_centre_sk",
            "cost_category_sk",
            "company_name",
            "voucher_number",
            "voucher_date",
            "party_ledger_name",
            "ledger_name",
            "ledger_group",
            "ledger_class",
            "line_no",
            "category_name",
            "cost_centre_name",
            "amount",
        ],
        compare=[
            "date_sk",
            "company_sk",
            "voucher_type_sk",
            "party_ledger_sk",
            "line_ledger_sk",
            "cost_centre_sk",
            "cost_category_sk",
            "voucher_number",
            "voucher_date",
            "party_ledger_name",
            "ledger_name",
            "ledger_group",
            "ledger_class",
            "line_no",
            "category_name",
            "cost_centre_name",
            "amount",
        ],
        pit=_pit_cost_centre,
        preview=f"""
            SELECT f.cost_centre_allocation_dw_sk, f.voucher_date, f.cost_centre_name, f.category_name,
                   f.ledger_name, f.ledger_class, f.amount, f.party_ledger_name, {_status_case('f')}
            FROM tally_dw.fact_cost_centre_allocation f
            WHERE f.is_current = TRUE
            ORDER BY f.voucher_date DESC NULLS LAST, f.cost_centre_name
        """,
    ),
    "Client Month": _fact_spec(
        "Client Month",
        dw="tally_dw.fact_client_month",
        sk="client_month_dw_sk",
        nk="source_key",
        ods_sql=f"""
            SELECT
                v.company_name || '|' || COALESCE(v.party_ledger_name, '') || '|'
                    || TO_CHAR(DATE_TRUNC('month', v.voucher_date)::date, 'YYYY-MM-DD') AS source_key,
                v.company_name,
                v.party_ledger_name AS client_name,
                MAX(COALESCE(party.mailing_name, v.party_ledger_name)) AS client_mailing_name,
                MAX(party.pincode) AS client_pincode,
                DATE_TRUNC('month', v.voucher_date)::date AS month_start,
                TO_CHAR(DATE_TRUNC('month', v.voucher_date)::date, 'YYYY-MM') AS month_year,
                CASE
                    WHEN EXTRACT(MONTH FROM DATE_TRUNC('month', v.voucher_date)::date) >= 4
                        THEN EXTRACT(YEAR FROM DATE_TRUNC('month', v.voucher_date)::date)::int
                    ELSE EXTRACT(YEAR FROM DATE_TRUNC('month', v.voucher_date)::date)::int - 1
                END AS fy_start_year,
                COUNT(DISTINCT v.voucher_sk)::INTEGER AS invoice_count,
                MIN(v.voucher_date) AS first_invoice_date,
                MAX(v.voucher_date) AS last_invoice_date,
                COALESCE(ROUND(SUM(-e.amount) FILTER (WHERE e.is_party_ledger), 2), 0) AS invoice_value_incl_gst,
                COALESCE(ROUND(SUM(e.amount) FILTER (WHERE l.parent_name IN {INCOME_GROUPS}), 2), 0) AS revenue_ex_gst,
                COALESCE(ROUND(SUM(e.amount) FILTER (WHERE l.parent_name = 'Duties & Taxes'), 2), 0) AS gst,
                COALESCE(ROUND(SUM(e.amount) FILTER (WHERE e.ledger_name = 'CGST'), 2), 0) AS cgst,
                COALESCE(ROUND(SUM(e.amount) FILTER (WHERE e.ledger_name = 'SGST'), 2), 0) AS sgst,
                COALESCE(ROUND(SUM(e.amount) FILTER (WHERE e.ledger_name = 'Man Power Supply'), 2), 0) AS manpower_supply,
                COALESCE(ROUND(SUM(e.amount) FILTER (WHERE e.ledger_name ILIKE 'Rental Service of Vehicles%%'), 2), 0) AS vehicle_rental,
                COALESCE(ROUND(SUM(e.amount) FILTER (WHERE e.ledger_name = 'Service Charges Recivable'), 2), 0) AS service_charges,
                COALESCE(ROUND(SUM(e.amount) FILTER (WHERE e.ledger_name ILIKE 'EPF%%'), 2), 0) AS epf_billed,
                COALESCE(ROUND(SUM(e.amount) FILTER (WHERE e.ledger_name ILIKE 'ESIC%%'), 2), 0) AS esic_billed,
                COALESCE(ROUND(SUM(e.amount) FILTER (
                    WHERE e.ledger_name ILIKE 'SECURITY%%' OR e.ledger_name ILIKE '%%Science Collage%%'
                ), 2), 0) AS other_income,
                STRING_AGG(DISTINCT v.voucher_number, ', ' ORDER BY v.voucher_number) AS voucher_numbers,
                STRING_AGG(DISTINCT cc.cost_centres, ', ' ORDER BY cc.cost_centres) AS cost_centres,
                MIN(v.created_timestamp) AS created_timestamp,
                MAX(v.last_updated_timestamp) AS last_updated_timestamp
            FROM tally_ods.voucher v
            JOIN tally_ods.voucher_ledger_entry e ON e.voucher_sk = v.voucher_sk
            LEFT JOIN tally_ods.ledger l
              ON l.name = e.ledger_name AND l.company_name = e.company_name
            LEFT JOIN tally_ods.ledger party
              ON party.name = v.party_ledger_name AND party.company_name = v.company_name
            LEFT JOIN (
                SELECT voucher_sk,
                       STRING_AGG(DISTINCT cost_centre_name, ', ' ORDER BY cost_centre_name) AS cost_centres
                FROM tally_ods.voucher_cost_centre_allocation
                GROUP BY voucher_sk
            ) cc ON cc.voucher_sk = v.voucher_sk
            WHERE COALESCE(v.is_optional, FALSE) = FALSE
              AND v.voucher_type_name IN {SALES_TYPES}
            GROUP BY
                v.company_name,
                v.party_ledger_name,
                DATE_TRUNC('month', v.voucher_date)::date
        """,
        dw_cols=[
            "source_key",
            "date_sk",
            "company_sk",
            "client_sk",
            "company_name",
            "client_name",
            "client_mailing_name",
            "client_pincode",
            "month_start",
            "month_year",
            "fy_start_year",
            "invoice_count",
            "first_invoice_date",
            "last_invoice_date",
            "invoice_value_incl_gst",
            "revenue_ex_gst",
            "gst",
            "cgst",
            "sgst",
            "manpower_supply",
            "vehicle_rental",
            "service_charges",
            "epf_billed",
            "esic_billed",
            "other_income",
            "voucher_numbers",
            "cost_centres",
        ],
        compare=[
            "date_sk",
            "company_sk",
            "client_sk",
            "client_mailing_name",
            "client_pincode",
            "month_start",
            "month_year",
            "fy_start_year",
            "invoice_count",
            "first_invoice_date",
            "last_invoice_date",
            "invoice_value_incl_gst",
            "revenue_ex_gst",
            "gst",
            "cgst",
            "sgst",
            "manpower_supply",
            "vehicle_rental",
            "service_charges",
            "epf_billed",
            "esic_billed",
            "other_income",
            "voucher_numbers",
            "cost_centres",
        ],
        pit=_pit_client_month,
        preview=f"""
            SELECT f.client_month_dw_sk, f.month_year, f.fy_start_year, f.client_name,
                   f.invoice_count, f.invoice_value_incl_gst, f.revenue_ex_gst, f.gst,
                   f.manpower_supply, f.vehicle_rental, f.service_charges, f.cost_centres,
                   {_status_case('f')}
            FROM tally_dw.fact_client_month f
            WHERE f.is_current = TRUE
            ORDER BY f.month_start DESC, f.invoice_value_incl_gst DESC NULLS LAST
        """,
    ),
}

REFRESH_ORDER = [
    "Date",
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
    "Ledger Line",
    "Inventory Line",
    "Bill Allocation",
    "Cost Centre Allocation",
    "Client Month",
]

TABLES: dict[str, dict] = {"Date": DATE_TABLE, **DIMS, **FACTS}


def dw_preview(meta: dict) -> str:
    """The SQL a Tally warehouse page lists a table with: the curated columns first, then every other column of the table
    (surrogate keys and point-in-time links, version dates, audit columns), and every version, the current one first.

    Without the keys a fact cannot be checked against the dimension versions it points at; without the older versions a
    key that points at a version that is no longer current cannot be found. The curated SQL is kept as it is, so the
    names and groupings it adds are still there."""
    import re

    from app.database import db_cursor

    curated = meta["preview"].strip()
    sk = meta.get("sk") or "date_sk"
    match = re.search(r"\sORDER\s+BY\s+.+$", curated, flags=re.IGNORECASE | re.DOTALL)
    base, order = (curated[: match.start()], match.group(0).strip()) if match else (curated, "")
    # The order is applied outside the curated query, where its table aliases no longer exist.
    order = re.sub(r"\b[A-Za-z_][A-Za-z0-9_]*\.", "", order)
    # Every version, not only the current one.
    base = re.sub(r"\s+WHERE\s+(?:\w+\.)?is_current\s*=\s*TRUE", "", base, flags=re.IGNORECASE)
    schema, _, table = meta["dw"].partition(".")
    with db_cursor() as cur:
        cur.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_schema = %s AND table_name = %s ORDER BY ordinal_position",
            (schema, table),
        )
        table_columns = [row[0] for row in cur.fetchall()]
        cur.execute(f"SELECT * FROM ({base}) curated LIMIT 0")
        shown = [desc[0] for desc in cur.description]
    missing = [col for col in table_columns if col not in shown]
    if sk not in shown or not missing:
        return f"{base} {order}".strip()
    extra = ", ".join(f't."{col}"' for col in missing)
    history = ", effective_from DESC" if "effective_from" in table_columns and order else ""
    return f"SELECT p.*, {extra} FROM ({base}) p JOIN {meta['dw']} t ON t.{sk} = p.{sk} {order}{history}".strip()


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
            WHERE n.nspname = 'tally_dw' AND c.relkind = 'r'
            """
        )
        existing = {row[0] for row in cur.fetchall()}
        for item in items:
            qualified = TABLES[item["name"]].get("dw", "tally_dw.dim_date")
            bare = qualified.split(".")[-1]
            if bare not in existing:
                continue
            if item["name"] == "Date":
                cur.execute("SELECT COUNT(*) FROM tally_dw.dim_date")
                total = int(cur.fetchone()[0])
                item["rows"] = total
                item["current"] = total
            else:
                cur.execute(f"SELECT COUNT(*), COUNT(*) FILTER (WHERE is_current) FROM {qualified}")
                total, current = cur.fetchone()
                item["rows"] = int(total)
                item["current"] = int(current)
    except Exception:
        logger.exception("Could not read Tally DW table counts")
    finally:
        cur.close()
        conn.close()
    return items
