"""The schema is applied once per change, every result is recorded, and a failure stops a deploy.

The first half needs no database. The second half applies a real (and a deliberately broken) migration to the development database
and removes its own `zz_test_*` records; it runs only with ORION_DB_TESTS=1:

    $env:ORION_DB_TESTS = "1"; python -m pytest backend/tests/test_migrate.py
"""

import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app import entities, migrate  # noqa: E402
from app.migrate import MigrationFailed, Result  # noqa: E402

RUN = os.environ.get("ORION_DB_TESTS") == "1"
SQL_DIR = ROOT / ".cursor" / "db"


class TheChecksum(unittest.TestCase):
    def test_line_endings_do_not_change_it(self):
        self.assertEqual(migrate.checksum("a\nb\n"), migrate.checksum("a\r\nb\r\n"))
        self.assertEqual(migrate.checksum("a\nb\n"), migrate.checksum("a\rb\r"))

    def test_any_real_change_does(self):
        self.assertNotEqual(migrate.checksum("ALTER TABLE x ADD COLUMN a INT;"), migrate.checksum("ALTER TABLE x ADD COLUMN b INT;"))
        self.assertNotEqual(migrate.checksum("a"), migrate.checksum("a "))


class TheRegistry(unittest.TestCase):
    def test_every_registered_file_exists_once(self):
        names = [p.name for p in entities.SQL_MIGRATIONS]
        self.assertEqual(len(names), len(set(names)), "a file is listed twice")
        self.assertEqual([p.name for p in entities.SQL_MIGRATIONS if not p.is_file()], [])

    def test_every_sql_file_is_either_registered_or_deliberately_not(self):
        """A new migrate_*.sql that nobody registered would run only from the init scripts and never reach production."""
        registered = {p.name for p in entities.SQL_MIGRATIONS}
        handled_elsewhere = {
            "schema.sql", "grants.sql", "dw_schema.sql", "tally_ods_schema.sql", "tally_dw_schema.sql",  # the base schema, grants, the warehouses
            "migrate_schema_migrations.sql",  # the tracking table: migrate.py runs it first, always
            # legacy: applied by the init scripts, and at startup by their own Python (auth.ensure_user_profile_columns, signup)
            "migrate_app_user_billing_etl_access.sql", "migrate_app_user_contact.sql", "migrate_app_user_dashboard_access.sql",
            "migrate_app_user_password_reset.sql", "migrate_app_user_tally_access.sql", "migrate_app_user_tally_dw_access.sql",
            "migrate_opportunity_tender_and_case.sql", "migrate_signup_request.sql",
        }
        unknown = sorted(p.name for p in SQL_DIR.glob("*.sql") if p.name not in registered | handled_elsewhere)
        self.assertEqual(unknown, [], f"add {unknown} to entities.SQL_MIGRATIONS (and both init scripts)")

    def test_the_tracking_table_is_created_by_a_file_both_init_scripts_run(self):
        for script in ("scripts/init_db_windows.ps1", "scripts/init_db_mac.sh"):
            self.assertIn("migrate_schema_migrations.sql", (ROOT / script).read_text(encoding="utf-8"), script)

    def test_the_tracking_table_records_what_a_deploy_needs(self):
        sql = (SQL_DIR / "migrate_schema_migrations.sql").read_text(encoding="utf-8")
        for column in ("name", "checksum", "status", "applied_timestamp", "duration_ms", "attempts", "error"):
            self.assertRegex(sql, rf"\b{column}\b")
        self.assertIn("CREATE TABLE IF NOT EXISTS", sql)  # it is applied on every start

    def test_startup_goes_through_the_runner_and_nothing_else_applies_these_files(self):
        import inspect

        from app import main

        source = inspect.getsource(main.lifespan)
        self.assertIn("migrate.apply_at_startup(production=is_production())", source)
        for gone in ("ensure_bill_table()", "ensure_dw_schema()", "ensure_tally_ods_schema()", "ensure_tally_dw_schema()"):
            self.assertNotIn(gone, source, f"{gone} would apply a schema step the record does not know about")


class ApplyingOneFile(unittest.TestCase):
    refused = RuntimeError('permission denied for table x')

    def test_the_applications_role_is_tried_first(self):
        with mock.patch.object(migrate, "db_cursor") as cursor, mock.patch("app.dw_sync._run_sql") as owner:
            migrate.apply_sql("SELECT 1")
        cursor.assert_called_once()
        owner.assert_not_called()

    def test_an_ownership_refusal_is_retried_as_the_database_owner(self):
        with mock.patch.object(migrate, "db_cursor", side_effect=self.refused), \
             mock.patch("app.dw_sync._superuser_settings", return_value={"user": "postgres"}), mock.patch("app.dw_sync._run_sql") as owner:
            migrate.apply_sql("ALTER TABLE x ADD COLUMN y INT")
        owner.assert_called_once_with("ALTER TABLE x ADD COLUMN y INT", {"user": "postgres"})

    def test_with_no_owner_available_it_fails_and_says_what_to_set(self):
        with mock.patch.object(migrate, "db_cursor", side_effect=RuntimeError("must be owner of table signup_request")), \
             mock.patch("app.dw_sync._superuser_settings", return_value=None):
            with self.assertRaises(RuntimeError) as caught:
                migrate.apply_sql("x")
        self.assertIn("ORION_POSTGRES_SUPER_PASSWORD", str(caught.exception))

    def test_any_other_error_is_raised_as_it_is(self):
        with mock.patch.object(migrate, "db_cursor", side_effect=ValueError("syntax error at or near FOO")), mock.patch("app.dw_sync._run_sql") as owner:
            with self.assertRaises(ValueError):
                migrate.apply_sql("FOO")
        owner.assert_not_called()  # a typo is not an ownership problem: the owner must not be asked to run it


class FakeRun:
    """migrate.run with the database taken away: what is recorded, what runs, what it is asked to record."""

    def __init__(self, files, recorded=None, fail=(), warehouse=()):
        self.files, self.recorded, self.fail = files, dict(recorded or {}), set(fail)
        self.applied, self.records = [], []
        self.warehouse = warehouse

    def __enter__(self):
        def apply_sql(sql):
            if sql in self.fail:
                raise RuntimeError(f"syntax error in {sql}")
            self.applied.append(sql)

        def record(name, digest, ok, started, error):
            self.records.append((name, digest, ok, error))

        paths = []
        self.dir = tempfile.TemporaryDirectory()
        for name, text in self.files.items():
            path = Path(self.dir.name) / name
            path.write_bytes(text.encode("utf-8"))  # the exact bytes: write_text would rewrite line endings itself on Windows
            paths.append(path)
        self.patches = [
            mock.patch.object(migrate, "apply_sql", apply_sql),
            mock.patch.object(migrate, "_recorded", lambda: self.recorded),
            mock.patch.object(migrate, "_record", record),
            mock.patch.object(migrate, "sql_steps", lambda: paths),
            mock.patch.object(migrate, "warehouse_steps", lambda: list(self.warehouse)),
            mock.patch.object(migrate, "TRACKING_FILE", Path(self.dir.name) / "tracking.sql"),
        ]
        (Path(self.dir.name) / "tracking.sql").write_text("CREATE TABLE tracking", encoding="utf-8")
        for patch in self.patches:
            patch.start()
        return self

    def __exit__(self, *exc):
        for patch in self.patches:
            patch.stop()
        self.dir.cleanup()


class TheRun(unittest.TestCase):
    def test_a_new_file_is_applied_and_recorded(self):
        with FakeRun({"a.sql": "SELECT 1"}) as fake:
            results = migrate.run()
        self.assertEqual([(r.name, r.status) for r in results], [("a.sql", "applied")])
        self.assertEqual(fake.records, [("a.sql", migrate.checksum("SELECT 1"), True, None)])

    def test_an_unchanged_file_is_not_run_again(self):
        digest = migrate.checksum("SELECT 1")
        with FakeRun({"a.sql": "SELECT 1"}, recorded={"a.sql": (digest, "applied")}) as fake:
            results = migrate.run()
        self.assertEqual(results[0].status, "unchanged")
        self.assertEqual(fake.applied, ["CREATE TABLE tracking"])  # only the tracking file, which always runs
        self.assertEqual(fake.records, [])

    def test_an_edited_file_is_applied_again(self):
        with FakeRun({"a.sql": "SELECT 2"}, recorded={"a.sql": (migrate.checksum("SELECT 1"), "applied")}) as fake:
            results = migrate.run()
        self.assertEqual(results[0].status, "applied")
        self.assertIn("SELECT 2", fake.applied)

    def test_a_file_that_failed_last_time_is_tried_again_even_if_unchanged(self):
        digest = migrate.checksum("SELECT 1")
        with FakeRun({"a.sql": "SELECT 1"}, recorded={"a.sql": (digest, "failed")}):
            results = migrate.run()
        self.assertEqual(results[0].status, "applied")

    def test_a_line_ending_change_alone_does_not_reapply(self):
        digest = migrate.checksum("SELECT 1\nSELECT 2\n")
        with FakeRun({"a.sql": "SELECT 1\r\nSELECT 2\r\n"}, recorded={"a.sql": (digest, "applied")}):
            self.assertEqual(migrate.run()[0].status, "unchanged")

    def test_force_applies_everything(self):
        digest = migrate.checksum("SELECT 1")
        with FakeRun({"a.sql": "SELECT 1"}, recorded={"a.sql": (digest, "applied")}):
            self.assertEqual(migrate.run(force=True)[0].status, "applied")

    def test_a_failure_is_recorded_with_its_error_and_the_rest_still_run(self):
        with FakeRun({"a.sql": "SELECT 1", "b.sql": "BROKEN", "c.sql": "SELECT 3"}, fail={"BROKEN"}) as fake:
            results = migrate.run()
        self.assertEqual([r.status for r in results], ["applied", "failed", "applied"])
        self.assertIn("syntax error in BROKEN", results[1].error)
        failed = [r for r in fake.records if r[0] == "b.sql"]
        self.assertEqual((failed[0][2], "syntax error" in failed[0][3]), (False, True))
        self.assertIn("SELECT 3", fake.applied, "one bad file must not hide whether the others work")

    def test_the_warehouse_schemas_run_every_time_and_a_failure_in_one_is_recorded(self):
        calls = []
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        schema = Path(tmp.name) / "w.sql"
        schema.write_text("SELECT 1", encoding="utf-8")

        def good():
            calls.append("good")

        def bad():
            raise RuntimeError("warehouse broke")

        with FakeRun({}, warehouse=[("w1.sql", schema, good), ("w2.sql", schema, bad), ("w3.sql", schema, good)]):
            results = migrate.run()
        self.assertEqual([r.status for r in results], ["applied", "failed", "applied"])
        self.assertEqual(calls, ["good", "good"])

    def test_if_the_record_cannot_be_made_nothing_else_is_attempted(self):
        with FakeRun({"a.sql": "SELECT 1"}, fail={"CREATE TABLE tracking"}) as fake:
            results = migrate.run()
        self.assertEqual([r.status for r in results], ["failed"])
        self.assertNotIn("SELECT 1", fake.applied)

    def test_the_sql_only_run_leaves_the_warehouses_alone(self):
        def never():
            raise AssertionError("the warehouse step must not run")

        with FakeRun({"a.sql": "SELECT 1"}, warehouse=[("w.sql", Path("x"), never)]):
            self.assertEqual([r.name for r in migrate.run(warehouse=False)], ["a.sql"])


class TheStartupAndTheDeploy(unittest.TestCase):
    bad = [Result("a.sql", "applied"), Result("b.sql", "failed", error="column x does not exist")]

    def test_production_refuses_to_start_on_a_failed_step_and_says_which(self):
        with mock.patch.object(migrate, "run", return_value=self.bad):
            with self.assertRaises(MigrationFailed) as caught:
                migrate.apply_at_startup(production=True)
        self.assertIn("b.sql", str(caught.exception))
        self.assertIn("column x does not exist", str(caught.exception))

    def test_a_development_machine_logs_it_and_carries_on(self):
        with mock.patch.object(migrate, "run", return_value=self.bad):
            self.assertEqual(migrate.apply_at_startup(production=False), self.bad)

    def test_all_well_starts_in_production(self):
        ok = [Result("a.sql", "applied"), Result("b.sql", "unchanged")]
        with mock.patch.object(migrate, "run", return_value=ok):
            self.assertEqual(migrate.apply_at_startup(production=True), ok)

    def test_the_command_exits_1_on_a_failure_and_0_when_all_is_well(self):
        import io
        from contextlib import redirect_stdout

        with mock.patch.object(migrate, "run", return_value=self.bad), redirect_stdout(io.StringIO()) as out:
            self.assertEqual(migrate.main([]), 1)
        self.assertIn("FAILED", out.getvalue())
        self.assertIn("b.sql", out.getvalue())
        with mock.patch.object(migrate, "run", return_value=[Result("a.sql", "applied"), Result("b.sql", "unchanged")]), redirect_stdout(io.StringIO()) as out:
            self.assertEqual(migrate.main([]), 0)
        self.assertIn("up to date", out.getvalue())

    def test_force_is_passed_through(self):
        import io
        from contextlib import redirect_stdout

        with mock.patch.object(migrate, "run", return_value=[]) as run, redirect_stdout(io.StringIO()):
            migrate.main(["--force"])
        run.assert_called_once_with(force=True)

    def test_the_deploy_runs_it_before_anything_is_stopped(self):
        script = (ROOT / "scripts" / "deploy.ps1").read_text(encoding="utf-8")
        self.assertIn('@("app.migrate")', script)
        self.assertLess(script.index('@("app.migrate")'), script.index("$switchedServer = $true"))


class WhatIsWrongRightNow(unittest.TestCase):
    now = datetime(2026, 10, 19, tzinfo=timezone.utc)

    def rows(self, **overrides):
        def row(name, status="applied", text="SELECT 1", error=None):
            return {"name": name, "status": status, "checksum": migrate.checksum(text), "applied_timestamp": self.now, "error": error}

        return [row(p.name, text=p.read_text(encoding="utf-8")) for p in entities.SQL_MIGRATIONS] if not overrides else overrides["rows"]

    def test_a_clean_record_has_no_problems(self):
        with mock.patch.object(migrate, "status_rows", return_value=self.rows()):
            self.assertEqual(migrate.problems(), [])

    def test_a_failed_step_is_a_problem_with_its_error(self):
        rows = self.rows()
        rows[3] = {**rows[3], "status": "failed", "error": "relation x does not exist\nLINE 1"}
        with mock.patch.object(migrate, "status_rows", return_value=rows):
            found = migrate.problems()
        self.assertEqual(len(found), 1)
        self.assertIn("failed: relation x does not exist", found[0])

    def test_a_failed_step_for_a_file_this_code_does_not_know_is_not_a_problem(self):
        """What a rolled-back release leaves behind: its new migration failed, and the old code has never heard of the file."""
        rows = self.rows() + [{"name": "migrate_from_a_newer_release.sql", "status": "failed", "checksum": "x", "applied_timestamp": self.now, "error": "boom"}]
        with mock.patch.object(migrate, "status_rows", return_value=rows):
            self.assertEqual(migrate.problems(), [])

    def test_a_file_never_applied_or_edited_since_is_a_problem(self):
        rows = self.rows()
        missing, edited = rows.pop(0), rows[0]
        rows[0] = {**edited, "checksum": migrate.checksum("an older version")}
        with mock.patch.object(migrate, "status_rows", return_value=rows):
            found = migrate.problems()
        self.assertTrue(any("has not been applied" in item and missing["name"] in item for item in found))
        self.assertTrue(any("has changed since it was applied" in item and edited["name"] in item for item in found))


class TheSchemaIsVisible(unittest.TestCase):
    """A schema that is not right must show up where somebody looks, not only in a log file."""

    def setUp(self):
        from app import health

        self.health = health
        self.addCleanup(lambda: health._ready_cache.update(at=0.0, ok=True, ms=None, schema=None))

    def ready(self, database_ok=True, problems=None):
        self.health._ready_cache["at"] = 0.0
        database = {"ok": database_ok, "ms": 1, "error": None}
        with mock.patch.object(self.health, "check_database", return_value=database):
            with mock.patch.object(self.health, "schema_problems", return_value=problems):
                return self.health.ready()

    def test_a_healthy_answer_is_exactly_what_it_always_was(self):
        self.assertEqual(self.ready(problems=[]), (True, {"status": "ok", "database": "ok"}))

    def test_a_schema_problem_makes_it_not_ready_and_says_why(self):
        found = self.ready(problems=["migrate_x.sql failed: boom"])
        self.assertEqual(found, (False, {"status": "degraded", "database": "ok", "schema": "problem"}))

    def test_not_being_able_to_look_is_not_a_problem(self):
        self.assertTrue(self.ready(problems=None)[0])  # CI has no database: the record cannot be read, and that is not a failure

    def test_a_dead_database_is_still_reported_as_that(self):
        self.assertEqual(self.ready(database_ok=False), (False, {"status": "degraded", "database": "down"}))

    def test_the_system_page_lists_each_schema_problem_with_what_to_do(self):
        calm = {"ok": True, "ms": 1, "error": None}
        note = self.health.attention(calm, None, [], [], datetime(2026, 10, 19, tzinfo=timezone.utc), ["migrate_x.sql failed: boom"])
        self.assertEqual(len(note), 1)
        self.assertIn("migrate_x.sql failed: boom", note[0])
        self.assertIn("python -m app.migrate", note[0])

    def test_the_details_carry_the_schema_record(self):
        rows = [
            {"status": "applied", "applied_timestamp": datetime(2026, 10, 19, 9, tzinfo=timezone.utc)},
            {"status": "failed", "applied_timestamp": None},
        ]
        database = {"ok": True, "ms": 1, "error": None}
        with mock.patch.object(self.health, "check_database", return_value=database):
            with mock.patch.object(self.health, "pipelines", return_value=[]):
                with mock.patch.object(self.health.backup, "status", return_value={"state": "off"}):
                    with mock.patch.object(self.health.migrate, "status_rows", return_value=rows):
                        with mock.patch.object(self.health.migrate, "problems", return_value=["x failed: y"]):
                            found = self.health.details()
        self.assertEqual((found["schema"]["steps"], found["schema"]["applied"], found["schema"]["problems"]), (2, 1, ["x failed: y"]))
        self.assertEqual(found["status"], "attention")


@unittest.skipUnless(RUN, "set ORION_DB_TESTS=1 to run these against the development database")
class AgainstTheRealDatabase(unittest.TestCase):
    NAME = "zz_test_migration.sql"

    def setUp(self):
        from app.database import db_cursor

        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.path = Path(self.dir.name) / self.NAME
        self.addCleanup(self.cleanup)
        with db_cursor(commit=True) as cur:
            cur.execute("DROP TABLE IF EXISTS orion_ods.zz_migration_probe")

    def cleanup(self):
        from app.database import db_cursor

        with db_cursor(commit=True) as cur:
            cur.execute("DROP TABLE IF EXISTS orion_ods.zz_migration_probe")
            cur.execute(f"DELETE FROM {migrate.TABLE} WHERE name LIKE 'zz_test_%'")

    def run_it(self, text, **kw):
        self.path.write_text(text, encoding="utf-8")
        with mock.patch.object(migrate, "sql_steps", lambda: [self.path]):
            return migrate.run(warehouse=False, **kw)

    def row(self):
        return next((r for r in migrate.status_rows() if r["name"] == self.NAME), None)

    def test_a_real_migration_is_applied_recorded_and_then_skipped(self):
        sql = "CREATE TABLE IF NOT EXISTS orion_ods.zz_migration_probe (id INT);"
        first = self.run_it(sql)
        self.assertEqual(first[0].status, "applied")
        row = self.row()
        self.assertEqual((row["status"], row["checksum"], row["attempts"]), ("applied", migrate.checksum(sql), 1))
        self.assertIsNotNone(row["applied_timestamp"])
        self.assertGreaterEqual(row["duration_ms"], 0)
        self.assertEqual(self.run_it(sql)[0].status, "unchanged")

    def test_a_broken_migration_is_recorded_as_failed_and_changes_nothing(self):
        results = self.run_it("CREATE TABLE orion_ods.zz_migration_probe (id INT); SELECT * FROM table_that_is_not_there;")
        self.assertEqual(results[0].status, "failed")
        row = self.row()
        self.assertEqual(row["status"], "failed")
        self.assertIn("table_that_is_not_there", row["error"])
        from app.database import db_cursor

        with db_cursor() as cur:
            cur.execute("SELECT to_regclass('orion_ods.zz_migration_probe')")
            self.assertIsNone(cur.fetchone()[0], "a file is applied whole or not at all: half of it must not be left behind")

    def test_a_failed_migration_that_is_fixed_is_applied_and_the_failure_cleared(self):
        self.run_it("SELECT * FROM table_that_is_not_there;")
        self.assertEqual(self.run_it("SELECT * FROM table_that_is_not_there;")[0].status, "failed")
        self.assertEqual(self.row()["attempts"], 2)  # the same broken file tried again
        fixed = self.run_it("CREATE TABLE IF NOT EXISTS orion_ods.zz_migration_probe (id INT);")
        self.assertEqual(fixed[0].status, "applied")
        row = self.row()
        self.assertEqual((row["status"], row["error"], row["attempts"]), ("applied", None, 1))

    def test_an_edited_migration_is_applied_again(self):
        self.run_it("CREATE TABLE IF NOT EXISTS orion_ods.zz_migration_probe (id INT);")
        edited = self.run_it("CREATE TABLE IF NOT EXISTS orion_ods.zz_migration_probe (id INT); ALTER TABLE orion_ods.zz_migration_probe ADD COLUMN IF NOT EXISTS name TEXT;")
        self.assertEqual(edited[0].status, "applied")
        from app.database import db_cursor

        with db_cursor() as cur:
            cur.execute("SELECT column_name FROM information_schema.columns WHERE table_schema='orion_ods' AND table_name='zz_migration_probe'")
            self.assertEqual({r[0] for r in cur.fetchall()}, {"id", "name"})

    def test_the_problems_list_names_a_failed_step_and_clears_when_it_is_fixed(self):
        def found():
            with mock.patch.object(migrate, "sql_steps", lambda: [self.path]):  # the file is one this code knows
                return migrate.problems()

        self.run_it("SELECT * FROM table_that_is_not_there;")
        self.assertTrue(any(self.NAME in item and "failed" in item for item in found()))
        self.assertFalse(any(self.NAME in item for item in migrate.problems()), "a file the code does not know is not its problem")
        self.run_it("SELECT 1;")
        self.assertFalse(any(self.NAME in item for item in found()))

    def test_the_command_exits_1_for_a_broken_file_and_0_for_a_good_one(self):
        import io
        from contextlib import redirect_stdout

        self.path.write_text("SELECT * FROM table_that_is_not_there;", encoding="utf-8")
        with mock.patch.object(migrate, "sql_steps", lambda: [self.path]), mock.patch.object(migrate, "warehouse_steps", lambda: []), redirect_stdout(io.StringIO()):
            self.assertEqual(migrate.main([]), 1)
        self.path.write_text("SELECT 1;", encoding="utf-8")
        with mock.patch.object(migrate, "sql_steps", lambda: [self.path]), mock.patch.object(migrate, "warehouse_steps", lambda: []), redirect_stdout(io.StringIO()):
            self.assertEqual(migrate.main([]), 0)

    def test_the_real_registry_applies_cleanly_and_a_second_run_changes_nothing(self):
        first = migrate.run()
        self.assertEqual([r.name for r in migrate.failures(first)], [])
        second = migrate.run()
        sql_second = [r for r in second if r.name in {p.name for p in entities.SQL_MIGRATIONS}]
        self.assertTrue(all(r.status == "unchanged" for r in sql_second), "nothing changed, so nothing should run again")
        self.assertEqual(migrate.problems(), [])


if __name__ == "__main__":
    unittest.main()
