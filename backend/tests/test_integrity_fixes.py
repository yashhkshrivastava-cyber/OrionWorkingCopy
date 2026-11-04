"""Six data-integrity fixes, each pinned where a regression would be silent:

  1. a second save of a record cannot silently undo the first (optimistic version check);
  2. the warehouse pages list every column, surrogate keys and version dates included;
  3. a revenue entry follows the current version of its bill;
  4. the calendar reaches every date a fact carries;
  5. kilometres and readings are never negative, and manager and group chains never loop;
  6. the privilege script is not run, and so locks nothing, when there is nothing to grant.

None of these need a database: the database side of 5 is checked by reading the migration, and by the
development-database run described in the pull request.
"""

import re
import sys
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app import db_grants, db_utils, dw_sync, entities, entity_service, tally_dw  # noqa: E402
from app.payload import PayloadError  # noqa: E402

SQL_DIR = ROOT / ".cursor" / "db"


def at(day: int, hour: int = 10) -> datetime:
    return datetime(2026, 10, day, hour, 0, 0, 123456, tzinfo=timezone.utc)


# ------------------------------------------------------------------------------------------------------------ 1. versions


class SavingTheSameRecordTwice(unittest.TestCase):
    """Two people open one record; the second save must not undo the first, and must say so."""

    def setUp(self):
        self.stored = {"employee_code": "EMP-1", "employee_name": "Asha", "last_updated_timestamp": at(10), "last_updated_by": 4, "created_by": 1}
        self.writes = []
        patches = [
            mock.patch.object(entity_service, "fetch_by_id", side_effect=lambda *a, **k: dict(self.stored)),
            mock.patch.object(entity_service, "invalid_reason", return_value=None),
            mock.patch.object(entity_service, "_who_changed", return_value="Ravi"),
            mock.patch.object(entity_service, "update", side_effect=self.fake_update),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def fake_update(self, table, columns, values, record_id, pk, user_id=None, expected_updated=db_utils._UNSET):
        self.writes.append({"columns": columns, "values": values, "expected": expected_updated})
        return True

    def test_a_save_made_from_an_out_of_date_copy_is_refused_and_nothing_is_written(self):
        stale = at(9).isoformat()
        with self.assertRaises(entity_service.EntityError) as caught:
            entity_service.change("Employee", "EMP-1", {"employee_name": "Asha K"}, 7, stale)
        self.assertEqual(caught.exception.status, 409)
        self.assertIn("Ravi", caught.exception.message)
        self.assertEqual(self.writes, [])

    def test_a_save_made_from_the_current_copy_goes_through_with_that_version(self):
        entity_service.change("Employee", "EMP-1", {"employee_name": "Asha K"}, 7, at(10).isoformat())
        self.assertEqual(len(self.writes), 1)
        self.assertEqual(self.writes[0]["expected"], at(10))

    def test_the_same_moment_written_with_another_offset_still_matches(self):
        other_zone = at(10).astimezone(timezone(timedelta(hours=5, minutes=30))).isoformat()
        entity_service.change("Employee", "EMP-1", {"employee_name": "Asha K"}, 7, other_zone)
        self.assertEqual(len(self.writes), 1)

    def test_a_caller_with_no_version_is_held_to_the_one_it_just_read(self):
        entity_service.change("Employee", "EMP-1", {"employee_name": "Asha K"}, 7)
        self.assertEqual(self.writes[0]["expected"], at(10))

    def test_a_write_that_loses_the_race_is_a_conflict_not_a_silent_overwrite(self):
        with mock.patch.object(entity_service, "update", return_value=False):
            with self.assertRaises(entity_service.EntityError) as caught:
                entity_service.change("Employee", "EMP-1", {"employee_name": "Asha K"}, 7, at(10).isoformat())
        self.assertEqual(caught.exception.status, 409)

    def test_a_record_deleted_in_the_meantime_is_not_found(self):
        gone = [dict(self.stored), None]
        with mock.patch.object(entity_service, "fetch_by_id", side_effect=gone), mock.patch.object(entity_service, "update", return_value=False):
            with self.assertRaises(entity_service.EntityError) as caught:
                entity_service.change("Employee", "EMP-1", {"employee_name": "Asha K"}, 7, at(10).isoformat())
        self.assertEqual(caught.exception.status, 404)

    def test_the_update_statement_carries_the_version_in_its_where_clause(self):
        statements = []

        class Cursor:
            rowcount = 0

            def execute(self, sql, params):
                statements.append((sql, params))

        class Context:
            def __enter__(self):
                return Cursor()

            def __exit__(self, *exc):
                return False

        with mock.patch.object(db_utils, "db_cursor", return_value=Context()):
            changed = db_utils.update("orion_ods.employee", ["employee_name"], ["Asha"], "EMP-1", "employee_code", user_id=7, expected_updated="2026-10-10T10:00:00+00:00")
        self.assertFalse(changed)
        sql, params = statements[0]
        self.assertIn("last_updated_timestamp IS NOT DISTINCT FROM", sql)
        self.assertEqual(params[-1], "2026-10-10T10:00:00+00:00")

    def test_the_record_form_sends_only_what_was_changed_and_the_version_it_opened(self):
        page = (ROOT / "frontend" / "src" / "pages" / "OperationalDataPage.tsx").read_text(encoding="utf-8")
        self.assertIn("last_updated_timestamp", page)
        self.assertIn("changed.has(key)", page)
        router = (ROOT / "backend" / "app" / "routers" / "entities_router.py").read_text(encoding="utf-8")
        self.assertIn("body.expected_updated", router)


# ------------------------------------------------------------------------------------------------------------- 2. columns


class WarehousePagesListEveryColumn(unittest.TestCase):
    def test_every_orion_table_lists_all_its_columns_surrogate_keys_included(self):
        for name, meta in dw_sync.TABLES.items():
            if name == "Date":
                continue
            sql = dw_sync.dw_preview(meta, True)
            wanted = [meta["sk"], *meta["dw_cols"], *dw_sync._VERSION_COLUMNS]
            for column in wanted:
                with self.subTest(table=name, column=column):
                    self.assertRegex(sql, rf"\b[df]\.{column}\b")

    def test_every_fact_shows_the_keys_that_link_it_to_the_dimension_versions(self):
        for name, meta in dw_sync.FACTS.items():
            keys = [col for col in meta["dw_cols"] if col.endswith("_sk")]
            self.assertTrue(keys, name)
            sql = dw_sync.dw_preview(meta, False)
            for key in keys:
                with self.subTest(table=name, key=key):
                    self.assertIn(f"f.{key}", sql)

    def test_all_versions_are_listed_not_only_the_current_one(self):
        for name, meta in dw_sync.TABLES.items():
            with self.subTest(table=name):
                # (a join that looks a name up on the current version of another record is not a filter on the listing)
                self.assertNotRegex(dw_sync.dw_preview(meta, True), r"WHERE\s+\w+\.is_current")

    def test_the_salary_is_still_left_out_for_a_reader_who_may_not_see_it(self):
        meta = dw_sync.TABLES["Employee"]
        self.assertIn("monthly_salary", dw_sync.dw_preview(meta, True))
        self.assertNotIn("monthly_salary", dw_sync.dw_preview(meta, False))
        # ... and everything else of the employee is still there for them
        for column in ("employee_type", "client_facing", "emp_start_date", "manager_code"):
            self.assertIn(column, dw_sync.dw_preview(meta, False))

    def test_the_date_dimension_lists_all_of_its_columns(self):
        sql = dw_sync.TABLES["Date"]["preview"]
        for column in ("month_number", "week_of_year", "day_of_month", "day_of_week"):
            self.assertIn(column, sql)

    def test_the_columns_listed_are_columns_of_the_schema(self):
        schema = (SQL_DIR / "dw_schema.sql").read_text(encoding="utf-8")
        for name, meta in dw_sync.FACTS.items():
            for column in [meta["sk"], *meta["dw_cols"]]:
                with self.subTest(table=name, column=column):
                    self.assertRegex(schema, rf"\b{column}\b")

    def test_the_tally_listing_keeps_the_curated_columns_and_adds_the_rest(self):
        meta = tally_dw.TABLES["Voucher"]
        shown = ["voucher_dw_sk", "voucher_date"]
        columns = ["voucher_dw_sk", "voucher_date", "date_sk", "company_sk", "effective_from", "effective_to"]

        class Cursor:
            def __init__(self):
                self.description = [(c,) for c in shown]

            def execute(self, sql, params=()):
                self.last = sql

            def fetchall(self):
                return [(c,) for c in columns]

        class Context:
            def __enter__(self):
                return Cursor()

            def __exit__(self, *exc):
                return False

        with mock.patch("app.database.db_cursor", return_value=Context()):
            sql = tally_dw.dw_preview({**meta, "preview": "SELECT voucher_dw_sk, voucher_date FROM tally_dw.fact_voucher f WHERE f.is_current = TRUE ORDER BY f.voucher_date DESC"})
        self.assertIn('t."date_sk"', sql)
        self.assertIn('t."company_sk"', sql)
        self.assertNotIn("is_current", sql)
        # the order is applied outside the curated query, so it cannot name that query's table alias
        self.assertTrue(sql.rstrip().endswith("ORDER BY voucher_date DESC, effective_from DESC"), sql)

    def test_the_pages_show_every_column_the_server_sends(self):
        for page in ("WarehousePage.tsx", "TallyDwPage.tsx"):
            text = (ROOT / "frontend" / "src" / "pages" / page).read_text(encoding="utf-8")
            self.assertIn("allColumns", text, page)


# ------------------------------------------------------------------------------------------------------------ 3. bill link


class RevenueEntryFollowsItsBill(unittest.TestCase):
    def index(self):
        rows = [
            {"bill_code": "B-1", "bill_sk": 10, "effective_from": datetime(2026, 8, 1, tzinfo=timezone.utc), "effective_to": datetime(2026, 9, 15, tzinfo=timezone.utc), "is_current": False},
            {"bill_code": "B-1", "bill_sk": 11, "effective_from": datetime(2026, 9, 15, tzinfo=timezone.utc), "effective_to": None, "is_current": True},
        ]
        return dw_sync._DimIndex(rows, "bill_code", "bill_sk")

    def test_the_latest_version_is_the_current_one(self):
        self.assertEqual(self.index().latest("B-1")["bill_sk"], 11)
        self.assertIsNone(self.index().latest("nope"))
        self.assertIsNone(self.index().latest(None))

    def test_a_deleted_bill_resolves_to_its_last_version(self):
        index = self.index()
        for row in index.by_nk["B-1"]:
            row["is_current"] = False
        self.assertEqual(index.latest("B-1")["bill_sk"], 11)

    def test_an_entry_dated_before_the_edit_points_at_the_edited_bill(self):
        pit = mock.Mock()
        pit.bill = self.index()
        pit.case_keys.return_value = {"case_sk": 1, "client_sk": 2, "capability_sk": 3, "business_domain_sk": 4}
        ods = {"case_code": "C-1", "bill_code": "B-1", "transaction_date": date(2026, 8, 31)}
        keys = dw_sync._pit_case_txn(pit, ods, datetime(2026, 10, 10, tzinfo=timezone.utc))
        self.assertEqual(keys["bill_sk"], 11)
        # (as the bill stood on the entry's date it would have been version 10, which is the bug)
        self.assertEqual(pit.bill.at("B-1", datetime(2026, 8, 31, 23, 59, tzinfo=timezone.utc))["bill_sk"], 10)

    def test_the_bill_is_loaded_before_the_entries_that_point_at_it(self):
        order = dw_sync.REFRESH_ORDER
        self.assertLess(order.index("Bill"), order.index("Case Transaction"))


# ----------------------------------------------------------------------------------------------------------- 4. calendar


class CalendarReachesEveryFactDate(unittest.TestCase):
    FIRST, LAST = date(2015, 1, 1), date(2029, 12, 31)

    def test_it_is_at_least_the_usual_range(self):
        self.assertEqual(dw_sync.calendar_bounds(self.FIRST, self.LAST, []), (self.FIRST, self.LAST))
        self.assertEqual(dw_sync.calendar_bounds(self.FIRST, self.LAST, [(None, None)]), (self.FIRST, self.LAST))

    def test_a_fact_dated_before_or_after_the_usual_range_gets_calendar_rows(self):
        found = [(date(2012, 6, 3), date(2031, 1, 1))]
        self.assertEqual(dw_sync.calendar_bounds(self.FIRST, self.LAST, found), (date(2012, 6, 3), date(2031, 1, 1)))

    def test_a_mistyped_year_cannot_add_a_century_of_rows(self):
        found = [(date(1850, 1, 1), date(9999, 12, 31))]
        start, end = dw_sync.calendar_bounds(self.FIRST, self.LAST, found)
        self.assertEqual((start, end), dw_sync.CALENDAR_LIMITS)

    def test_the_tally_calendar_starts_on_the_first_of_the_month_because_monthly_facts_are_dated_so(self):
        start, end = tally_dw.calendar_bounds(self.FIRST, self.LAST, [(date(2013, 5, 15), date(2016, 1, 1))])
        self.assertEqual(start, date(2013, 5, 1))
        self.assertEqual(end, self.LAST)

    def test_every_fact_date_column_the_warehouse_links_by_is_in_the_calendar_query(self):
        linked = {column for _table, column in dw_sync._FACT_DATES}
        self.assertEqual(linked, {"transaction_date", "driving_date", "bill_date", "deposit_date"})
        text = (ROOT / "backend" / "app" / "dw_sync.py").read_text(encoding="utf-8")
        for column in re.findall(r'keys\["date_sk"\] = _date_sk\(ods.get\("(\w+)"\)\)', text):
            self.assertIn(column, linked)


# --------------------------------------------------------------------------------------------------------- 5. data rules


class DataRules(unittest.TestCase):
    def test_kilometres_and_readings_cannot_be_negative(self):
        for entity, field in (("Case", "monthly_allowed_km"), ("Car", "per_km_price"), ("Car Transaction", "initial_reading"), ("Car Transaction", "final_reading")):
            rule = entities.ENTITIES[entity]["field_rules"][field]
            with self.subTest(entity=entity, field=field):
                self.assertEqual(rule(0), 0)
                self.assertEqual(rule(12.5), 12.5)
                with self.assertRaises(PayloadError):
                    rule(-1)

    def test_a_final_reading_below_the_initial_one_is_refused_whichever_field_was_sent(self):
        self.assertIsNotNone(entities.invalid_reason("Car Transaction", None, {"initial_reading": 500, "final_reading": 400}))
        # an edit that sends only the final reading is checked against the stored initial one
        self.assertIsNotNone(entities.invalid_reason("Car Transaction", "CT-1", {"final_reading": 400}, {"initial_reading": 500, "final_reading": 600}))
        self.assertIsNone(entities.invalid_reason("Car Transaction", "CT-1", {"final_reading": 700}, {"initial_reading": 500, "final_reading": 600}))
        self.assertIsNone(entities.invalid_reason("Car Transaction", None, {"initial_reading": None, "final_reading": 400}))

    def test_received_money_with_no_bill_is_refused_from_the_form_the_upload_and_the_copilot(self):
        new_receipt = {"case_code": "CS-1", "transaction_status": "Committed", "transaction_amount": 500}
        self.assertIn("recorded on its bill", entities.invalid_reason("Transaction", None, new_receipt))
        # a Prospective or Cancelled entry is a forecast or nothing, not money in the bank
        for status in ("Prospective", "Cancelled"):
            self.assertIsNone(entities.invalid_reason("Transaction", None, {**new_receipt, "transaction_status": status}))
        # an entry that belongs to a bill is the bill's: billing writes it
        self.assertIsNone(entities.invalid_reason("Transaction", None, {**new_receipt, "bill_code": "BILL-1"}))
        # making a Prospective entry Committed is the same as entering a receipt
        self.assertIn(
            "recorded on its bill",
            entities.invalid_reason("Transaction", "TR-1", {"transaction_status": "Committed"}, {"transaction_status": "Prospective", "bill_code": None}),
        )
        # one stored as received before the rule can still be corrected where it stands, so no balance moves
        self.assertIsNone(
            entities.invalid_reason("Transaction", "TR-1", {"transaction_amount": 600}, {"transaction_status": "Committed", "bill_code": None}),
        )
        self.assertIn("Bank", entity_service.CONSTRAINT_MESSAGES["case_transaction_committed_needs_bill"])

    def test_an_employee_cannot_be_their_own_manager(self):
        reason = entities.invalid_reason("Employee", "EMP-1", {"manager_code": "EMP-1"})
        self.assertIn("own manager", reason)
        self.assertIsNone(entities.invalid_reason("Employee", "EMP-1", {"manager_code": None}))

    def test_a_manager_who_already_reports_to_the_employee_is_a_loop(self):
        with mock.patch.object(entities, "_chain_reaches", return_value=True) as reaches:
            reason = entities.invalid_reason("Employee", "EMP-1", {"manager_code": "EMP-3"})
        self.assertIn("circle", reason)
        reaches.assert_called_once_with("orion_ods.employee", "manager_code", "employee_code", "EMP-3", "EMP-1")
        with mock.patch.object(entities, "_chain_reaches", return_value=False):
            self.assertIsNone(entities.invalid_reason("Employee", "EMP-1", {"manager_code": "EMP-3"}))

    def test_a_group_that_already_belongs_to_the_client_is_a_loop(self):
        with mock.patch.object(entities, "_chain_reaches", return_value=True):
            self.assertIn("circle", entities.invalid_reason("Client", "CL-1", {"client_group_code": "CL-2"}))
        self.assertIn("own group", entities.invalid_reason("Client", "CL-1", {"client_group_code": "CL-1"}))

    def test_a_new_record_is_checked_too(self):
        with mock.patch.object(entity_service, "validate", return_value={"initial_reading": 9, "final_reading": 3, "car_code": "C"}), mock.patch.object(
            entity_service, "insert"
        ) as insert:
            with self.assertRaises(entity_service.EntityError) as caught:
                entity_service.create("Car Transaction", {"initial_reading": 9, "final_reading": 3, "car_code": "C"}, 1)
        self.assertEqual(caught.exception.status, 400)
        insert.assert_not_called()

    def test_the_database_holds_the_same_rules_so_an_upload_meets_them_too(self):
        sql = (SQL_DIR / "migrate_data_rules.sql").read_text(encoding="utf-8")
        own_file = {"expense_": "migrate_expense_payments.sql", "salary_": "migrate_payroll.sql", "emd_": "migrate_contacts_emd.sql", "contact_": "migrate_contacts_emd.sql"}  # rules that belong to a feature's own schema file
        for name in entity_service.CONSTRAINT_MESSAGES:
            if name == "client_group_not_self":
                continue  # migrate_client_group.sql
            where = next((f for prefix, f in own_file.items() if name.startswith(prefix)), None)
            with self.subTest(constraint=name):
                self.assertIn(name, (SQL_DIR / where).read_text(encoding="utf-8") if where else sql)
        self.assertEqual(sql.count("NOT VALID;"), 5)  # five constraints, none of which may stop on rows already stored
        # a receipt with no bill is refused when it is new, and a legacy one can still be corrected where it stands
        self.assertIn("TG_OP = 'INSERT' OR OLD.transaction_status IS DISTINCT FROM 'Committed' OR OLD.bill_code IS NOT NULL", sql)
        self.assertIn("DROP TRIGGER IF EXISTS case_transaction_committed_needs_bill", sql)
        # a loop already stored must not stop an unrelated edit of one of its rows
        self.assertIn("UPDATE OF manager_code", sql)
        self.assertIn("UPDATE OF client_group_code", sql)
        # re-running it is safe
        self.assertIn("CREATE OR REPLACE FUNCTION", sql)
        self.assertEqual(sql.count("IF NOT EXISTS (SELECT 1 FROM pg_trigger"), 2)

    def test_the_new_sql_file_reaches_every_database(self):
        for script in ("scripts/init_db_windows.ps1", "scripts/init_db_mac.sh"):
            self.assertIn("migrate_data_rules.sql", (ROOT / script).read_text(encoding="utf-8"), script)
        self.assertTrue(entities.DATA_RULES_MIGRATE.is_file())
        self.assertIn(entities.DATA_RULES_MIGRATE, entities.SQL_MIGRATIONS)  # applied (and recorded) at every start by app.migrate

    def test_a_refusal_from_the_database_is_a_sentence_not_a_constraint_name(self):
        from psycopg2 import errors as pg_errors

        class Diag:
            constraint_name = "employee_manager_no_loop"

        error = pg_errors.CheckViolation("x")
        with mock.patch.object(pg_errors.CheckViolation, "diag", Diag(), create=True):
            refusal = entity_service.database_refusal(error)
        self.assertIn("circle", refusal.message)
        self.assertEqual(refusal.status, 400)


# -------------------------------------------------------------------------------------------------------- 6. grants


class PrivilegeScript(unittest.TestCase):
    def test_nothing_is_run_when_the_application_role_already_has_everything(self):
        calls = []
        with mock.patch.object(db_grants, "needed", return_value=False), mock.patch.object(dw_sync, "_run_sql", side_effect=lambda *a, **k: calls.append(a)):
            dw_sync.ensure_dw_privileges()
        self.assertEqual(calls, [])

    def test_the_script_is_run_when_something_is_missing(self):
        calls = []
        with mock.patch.object(db_grants, "needed", return_value=True), mock.patch.object(
            dw_sync, "_superuser_settings", return_value={"user": "postgres"}
        ), mock.patch.object(dw_sync, "_run_sql", side_effect=lambda *a, **k: calls.append(a)):
            dw_sync.ensure_dw_privileges()
        self.assertEqual(len(calls), 1)

    def test_a_check_that_cannot_be_made_runs_the_script_as_before(self):
        with mock.patch.object(db_grants, "db_cursor", side_effect=RuntimeError("no database")):
            self.assertTrue(db_grants.needed())

    def test_the_script_changes_only_objects_that_are_not_already_owned_and_does_not_wait_long(self):
        sql = (SQL_DIR / "grants.sql").read_text(encoding="utf-8")
        self.assertIn("SET lock_timeout", sql)
        # each ownership change is guarded by "owned by someone else", so an already-owned table is never locked
        self.assertEqual(sql.count("ALTER TABLE") + sql.count("ALTER VIEW"), 6)
        self.assertEqual(sql.count("pg_get_userbyid(c.relowner) <> 'orion_user'"), 3)
        self.assertEqual(sql.count("pg_get_userbyid(nspowner) <> 'orion_user'"), 3)

    def test_the_tally_warehouses_use_the_same_check(self):
        from app import tally_ods

        for module, function in ((tally_ods, "ensure_tally_ods_privileges"), (tally_dw, "ensure_tally_dw_privileges")):
            calls = []
            with mock.patch.object(db_grants, "needed", return_value=False), mock.patch.object(module, "_run_sql", side_effect=lambda *a, _calls=calls, **k: _calls.append(a)):
                getattr(module, function)()
            self.assertEqual(calls, [], function)


if __name__ == "__main__":
    unittest.main()
