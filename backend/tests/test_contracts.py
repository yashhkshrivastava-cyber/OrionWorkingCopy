"""Contracts between parts of the app that are written in different places.

A form field, a warehouse load and a dashboard tab are each declared in one file and
relied on in another. These checks read the source files and fail when the two sides
drift apart, without needing a database. docs/change-impact.md lists the same contracts
in words.

Run from the repo root:  .venv\\Scripts\\python.exe -m pytest backend/tests
"""

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app import billing, dw_sync, migrate  # noqa: E402
from app.dashboard.views import VIEWS  # noqa: E402
from app.entities import ENTITIES, merge_columns  # noqa: E402

SQL_DIR = ROOT / ".cursor" / "db"
FRONTEND = ROOT / "frontend" / "src"

CREATE = re.compile(r"CREATE TABLE IF NOT EXISTS\s+([a-z_]+\.[a-z_]+)\s*\((.*?)\n\);", re.S | re.I)
ALTER = re.compile(r"ALTER TABLE\s+([a-z_]+\.[a-z_]+)\s+(.*?);", re.S | re.I)
ADD_COLUMN = re.compile(r"ADD COLUMN IF NOT EXISTS\s+([a-z_]+)", re.I)
NOT_A_COLUMN = {"unique", "primary", "check", "constraint", "foreign"}


def schema_columns() -> dict[str, set[str]]:
    """Every column each table ends up with after all the SQL files have run."""
    tables: dict[str, set[str]] = {}
    for path in sorted(SQL_DIR.glob("*.sql")):
        sql = re.sub(r"--[^\n]*", "", path.read_text(encoding="utf-8"))
        for table, body in CREATE.findall(sql):
            columns = tables.setdefault(table.lower(), set())
            for line in body.split("\n"):
                word = line.strip().split(" ")[0].strip('",').lower()
                if word and word not in NOT_A_COLUMN and re.fullmatch(r"[a-z_]+", word):
                    columns.add(word)
        for table, body in ALTER.findall(sql):
            tables.setdefault(table.lower(), set()).update(name.lower() for name in ADD_COLUMN.findall(body))
    return tables


SCHEMA = schema_columns()


class SchemaFilesAreWired(unittest.TestCase):
    """A SQL file that no init script runs never reaches a new database."""

    def test_every_sql_file_is_run_by_both_init_scripts(self):
        files = {path.name for path in SQL_DIR.glob("*.sql")}
        for script in ("scripts/init_db_windows.ps1", "scripts/init_db_mac.sh"):
            text = (ROOT / script).read_text(encoding="utf-8")
            missing = sorted(name for name in files if name not in text)
            self.assertEqual(missing, [], f"{script} does not run: {missing}")

    def test_init_scripts_only_name_files_that_exist(self):
        files = {path.name for path in SQL_DIR.glob("*.sql")}
        for script in ("scripts/init_db_windows.ps1", "scripts/init_db_mac.sh"):
            text = (ROOT / script).read_text(encoding="utf-8")
            named = set(re.findall(r"([a-z_]+\.sql)", text))
            self.assertEqual(sorted(named - files), [], f"{script} names files that are gone")

    def test_sql_applied_at_startup_exists(self):
        from app import entities, tally_dw, tally_ods

        paths = [
            dw_sync.SCHEMA_FILE, dw_sync.GRANTS_FILE, tally_ods.SCHEMA_FILE, tally_dw.SCHEMA_FILE,
            entities.BILL_MIGRATE, entities.CASE_TRANSACTION_BILL_MIGRATE, entities.OPPORTUNITY_FIELDS_MIGRATE,
            entities.AUDIT_MIGRATE, entities.CAPABILITY_HEAD_MIGRATE, entities.ETL_MIGRATE, entities.BACKUP_MIGRATE,
            entities.LETTERHEAD_MIGRATE, entities.CLIENT_GROUP_MIGRATE,
            entities.EMPLOYEE_DOCUMENTS_MIGRATE, entities.DOCUMENTS_MIGRATE, entities.AI_MIGRATE, entities.CHAT_MIGRATE,
            entities.DATA_RULES_MIGRATE, entities.AUTH_SECURITY_MIGRATE, entities.IDEMPOTENCY_MIGRATE, migrate.TRACKING_FILE,
        ]
        self.assertEqual([str(path) for path in paths if not path.is_file()], [])


class EntityFormsMatchTheSchema(unittest.TestCase):
    """A form field with no column behind it fails on save, not at review."""

    def test_every_form_field_is_a_column(self):
        for name, entity in ENTITIES.items():
            columns = SCHEMA.get(entity["table"])
            self.assertIsNotNone(columns, f"{name}: table {entity['table']} is not created by any SQL file")
            wanted = {entity["primary_key"], *entity["form_fields"], *merge_columns(name, entity)}
            self.assertEqual(sorted(wanted - columns), [], f"{name}: fields with no column in {entity['table']}")

    def test_lookup_fields_point_at_real_tables_and_columns(self):
        for name, entity in ENTITIES.items():
            for key, config in entity["form_fields"].items():
                source = config.get("source_table")
                if not source:
                    continue
                self.assertIn(source, SCHEMA, f"{name}.{key}: {source} is not a table")
                pk = config.get("source_pk_column", "id").split(".")[-1]
                self.assertIn(pk, SCHEMA[source], f"{name}.{key}: {source} has no column {pk}")


class WarehouseLoadsMatchTheSchema(unittest.TestCase):
    """The warehouse load names its columns by hand, on both the ODS and the DW side."""

    def test_columns_read_from_ods_exist(self):
        for name, spec in dw_sync.TABLES.items():
            if "ods" not in spec:
                continue
            missing = sorted(set(spec["ods_cols"]) - SCHEMA[spec["ods"]])
            self.assertEqual(missing, [], f"{name}: {spec['ods']} has no column(s) {missing}")

    def test_columns_written_to_the_warehouse_exist(self):
        for name, spec in dw_sync.TABLES.items():
            if "dw_cols" not in spec:
                continue
            wanted = {spec["sk"], *spec["dw_cols"], *dw_sync._SCD_COLUMNS}
            missing = sorted(wanted - SCHEMA[spec["dw"]])
            self.assertEqual(missing, [], f"{name}: {spec['dw']} has no column(s) {missing}")

    def test_every_entity_table_is_loaded_into_the_warehouse(self):
        loaded = {spec["ods"] for spec in dw_sync.TABLES.values() if "ods" in spec}
        missing = sorted(entity["table"] for entity in ENTITIES.values() if entity["table"] not in loaded)
        self.assertEqual(missing, [], "ODS tables with no warehouse load")


class FrontendMatchesBackend(unittest.TestCase):
    """Names typed on both sides of the API."""

    def test_every_entity_has_a_place_in_the_data_catalog(self):
        text = (FRONTEND / "pages" / "OperationalDataPage.tsx").read_text(encoding="utf-8")
        block = text[text.index("const DATASET_GROUPS") : text.index("function groupDatasets")]
        listed = set()
        for names in re.findall(r"names:\s*\[([^\]]*)\]", block):
            listed.update(re.findall(r"'([^']+)'", names))
        self.assertEqual(listed, set(ENTITIES), "DATASET_GROUPS and ENTITIES list different entities")

    def test_orion_dashboard_tabs_are_backend_views(self):
        text = (FRONTEND / "dashboards" / "registry.ts").read_text(encoding="utf-8")
        block = text[text.index("export const DASHBOARDS") : text.index("export const dashboardByView")]
        # a tab with `standalone: true` has its own page and its own endpoint (the forecast), not a view of the shell
        entries = re.split(r"\n  \{\n", block)[1:]
        tabs = {re.search(r"view:\s*'([a-z_]+)'", e).group(1) for e in entries if "standalone: true" not in e}
        alone = {re.search(r"view:\s*'([a-z_]+)'", e).group(1) for e in entries if "standalone: true" in e}
        self.assertEqual(tabs, set(VIEWS), "dashboard tabs and backend views differ")
        from app.routers import dashboard_router, tally_dashboard_router

        for name in alone:
            self.assertIn(f"/dashboard/{name}", {r.path for r in dashboard_router.router.routes}, f"the {name} tab has no endpoint")
            self.assertIn(f"/tally-dashboard/{name}", {r.path for r in tally_dashboard_router.router.routes}, f"the Tally {name} tab has no endpoint")
        self.assertEqual(alone, {"forecast"})

    def test_every_dashboard_filter_is_known_to_the_frontend(self):
        from app import tally_dashboard
        from app.dashboard.filters import FILTER_KEYS

        text = (FRONTEND / "types.ts").read_text(encoding="utf-8")
        block = text[text.index("export const DASHBOARD_DIMENSION_KEYS") : text.index("export type DashboardFilterKey")]
        known = set(re.findall(r"'([a-z_]+)'", block))
        for name, keys in (("Orion", FILTER_KEYS), ("Tally", tally_dashboard.FILTER_KEYS)):
            self.assertEqual(sorted(set(keys) - known), [], f"{name} dashboard filters missing from types.ts")

    def test_every_access_flag_is_stored_and_typed(self):
        from app.auth import ACCESS_FLAGS

        self.assertEqual(sorted(set(ACCESS_FLAGS) - SCHEMA["orion_ods.app_user"]), [], "flags with no column")
        text = (FRONTEND / "types.ts").read_text(encoding="utf-8")
        user = text[text.index("export interface User {") :]
        user = user[: user.index("}")]
        missing = sorted(flag for flag in ACCESS_FLAGS if f"{flag}:" not in user)
        self.assertEqual(missing, [], "flags missing from the User type")

    def test_revenue_statuses_are_the_same_everywhere(self):
        from app.dashboard.filters import STATUS_ORDER

        for name in ("Transaction", "Expense Transaction"):
            options = ENTITIES[name]["form_fields"]["transaction_status"]["options"]
            self.assertEqual(sorted(options), sorted(STATUS_ORDER), f"{name} status options")
        panel = (FRONTEND / "components" / "billing" / "BillPayments.tsx").read_text(encoding="utf-8")
        for status in STATUS_ORDER:
            self.assertIn(f"{status}:", panel, f"BillPayments.tsx has no label for {status}")

    def test_the_parts_a_bill_can_hide_are_the_same_in_the_editor_and_on_the_server(self):
        text = (FRONTEND / "billing" / "billLayout.ts").read_text(encoding="utf-8")
        browser = re.findall(r"key: '([a-z_]+)'", text)
        server = [key for keys in billing.HIDEABLE.values() for key in keys]
        self.assertEqual(sorted(browser), sorted(server))
        document = (FRONTEND / "components" / "billing" / "BillDocument.tsx").read_text(encoding="utf-8")
        from app import billing_pdf

        pdf = Path(billing_pdf.__file__).read_text(encoding="utf-8")
        for key in server:
            # The lines' columns are chosen by lineColumns (billLayout.ts), which BillDocument.tsx draws from.
            self.assertIn(f"'{key}'", document + text.split("export function lineColumns")[-1], f"BillDocument.tsx never checks {key}")
            self.assertIn(f'"{key}"', pdf, f"billing_pdf.py never checks {key}")

    def test_every_bill_column_the_code_writes_exists(self):
        for column in (*billing.MONEY_COLUMNS, *billing.JSON_COLUMNS):
            self.assertIn(column, SCHEMA["orion_ods.bill"], column)

    def test_bill_preview_uses_the_server_default_rates(self):
        text = (FRONTEND / "billing" / "billCalc.ts").read_text(encoding="utf-8")
        block = text[text.index("export const DEFAULT_RATES") :]
        block = block[: block.index("}")]
        browser = {key: float(value) for key, value in re.findall(r"([a-z_]+):\s*'([0-9.]+)'", block)}
        server = {key: float(value) for key, value in billing.DEFAULT_RATES.items()}
        self.assertEqual(browser, server)


if __name__ == "__main__":
    unittest.main()
