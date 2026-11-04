"""ETL runs: what is counted, which steps a run has, and that the history table matches the code.

None of this needs a database or Tally. Run from the repo root:  python -m pytest backend/tests
"""

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app import dw_sync, etl, tally_dw, tally_ods  # noqa: E402

from test_contracts import SCHEMA  # noqa: E402


class Counting(unittest.TestCase):
    def test_a_table_copy_reports_four_counts(self):
        counts = etl.normalise({"inserted": 3, "updated": 2, "deleted": 1, "unchanged": 10})
        self.assertEqual(
            counts,
            {"rows_read": 15, "rows_inserted": 3, "rows_updated": 2, "rows_deleted": 1, "rows_unchanged": 10},
        )

    def test_a_warehouse_new_version_is_an_update_and_an_expiry_a_delete(self):
        counts = etl.normalise({"inserted": 1, "versioned": 4, "expired": 2, "unchanged": 5})
        self.assertEqual((counts["rows_updated"], counts["rows_deleted"], counts["rows_read"]), (4, 2, 10))

    def test_missing_counts_are_zero(self):
        self.assertEqual(sum(etl.normalise(None).values()), 0)
        self.assertEqual(etl.normalise({"inserted": 2, "unchanged": 0})["rows_read"], 2)

    def test_a_permission_error_says_what_to_do(self):
        text = etl._message(RuntimeError("permission denied for table dim_case"))
        self.assertIn("RuntimeError: permission denied", text)
        self.assertIn("grants.sql", text)

    def test_a_tally_error_is_shown_as_it_is(self):
        class TallyError(RuntimeError):
            pass

        self.assertEqual(etl._message(TallyError("Cannot reach Tally Prime")), "Cannot reach Tally Prime")

    def test_a_very_long_error_is_cut(self):
        self.assertEqual(len(etl._message(RuntimeError("x" * 5000))), etl.ERROR_LIMIT)


class Pipelines(unittest.TestCase):
    def setUp(self):
        self.all = etl.pipelines()

    def test_the_three_pipelines_in_page_order(self):
        self.assertEqual(list(self.all), ["orion_dw", "tally_ods", "tally_dw"])

    def test_each_runs_every_table_of_its_loader_in_load_order(self):
        self.assertEqual([n for n, _ in self.all["orion_dw"].steps()], dw_sync.REFRESH_ORDER)
        self.assertEqual([n for n, _ in self.all["tally_ods"].steps()], tally_ods.REFRESH_ORDER)
        self.assertEqual([n for n, _ in self.all["tally_dw"].steps()], tally_dw.REFRESH_ORDER)

    def test_the_calendar_is_generated_and_not_counted_as_rows_read(self):
        for key in ("orion_dw", "tally_dw"):
            kinds = dict(self.all[key].steps())
            self.assertEqual(kinds["Date"], etl.GENERATED)
            self.assertNotIn(etl.GENERATED, [k for n, k in self.all[key].steps() if n != "Date"])

    def test_one_tally_table_brings_what_it_needs_first(self):
        names = [n for n, _ in self.all["tally_ods"].resolve("Voucher Bill Allocation")]
        self.assertEqual(names, ["Company", "Voucher", "Voucher Ledger Entry", "Voucher Bill Allocation"])
        self.assertEqual([n for n, _ in self.all["tally_ods"].resolve("Company")], ["Company"])

    def test_one_warehouse_table_is_just_itself(self):
        self.assertEqual([n for n, _ in self.all["orion_dw"].resolve("Client")], [("Client")])

    def test_every_step_has_a_target_table_that_the_schema_defines(self):
        for key, pipeline in self.all.items():
            for name, _kind in pipeline.steps():
                table = pipeline.target_table(name)
                self.assertTrue(table, f"{key}: {name} has no target table")
                if table in SCHEMA:  # the Tally schemas are in other SQL files, parsed the same way
                    continue
                self.assertTrue(table.split(".")[0] in ("orion_dw", "tally_ods", "tally_dw"), table)

    def test_the_tally_warehouse_waits_for_the_working_copy(self):
        self.assertEqual(self.all["tally_dw"].blocked_by, ("tally_ods",))
        self.assertEqual(self.all["orion_dw"].blocked_by, ())

    def test_pipelines_follow_the_etl_flags(self):
        viewer = {"role": "viewer", "etl_access": True, "etl_write": False}
        runner = {"role": "viewer", "etl_access": True, "etl_write": True}
        nobody = {"role": "admin", "etl_access": False, "etl_write": False, "dw_access": True, "dw_write": True}
        for pipeline in self.all.values():
            self.assertTrue(pipeline.can_view(viewer))
            self.assertFalse(pipeline.can_run(viewer))
            self.assertTrue(pipeline.can_run(runner))
            self.assertFalse(pipeline.can_view(nobody), "the warehouse flags no longer open the ETL page")

    def test_a_bad_request_is_refused_before_anything_starts(self):
        for args in (("nope",), ("orion_dw", "Not A Table"), ("orion_dw", "all", "someday")):
            with self.assertRaises(etl.EtlError):
                etl.start_run(*args)


class FrontendMatches(unittest.TestCase):
    types = (ROOT / "frontend" / "src" / "types.ts").read_text(encoding="utf-8")

    def test_the_pipeline_keys_are_the_ones_the_page_types(self):
        declared = re.search(r"EtlPipelineKey = ([^\n]+)", self.types).group(1)
        self.assertEqual(set(re.findall(r"'([a-z_]+)'", declared)), set(etl.pipelines()))

    def test_the_run_triggers_are_the_ones_the_page_types(self):
        run = re.search(r"export interface EtlRun \{.*?\n\}", self.types, re.S).group(0)
        declared = re.search(r"trigger: ([^\n]+)", run).group(1)
        self.assertEqual(set(re.findall(r"'([a-z]+)'", declared)), set(etl.TRIGGERS))

    def test_the_ui_does_not_call_the_removed_load_routes(self):
        client = (ROOT / "frontend" / "src" / "api" / "client.ts").read_text(encoding="utf-8")
        for gone in ("/refresh'", "/load`", "dwLoad", "tallyLoad", "tallyDwLoad"):
            self.assertNotIn(gone, client)

    def test_the_rail_and_the_route_both_know_the_page(self):
        routes = (ROOT / "frontend" / "src" / "workspaceRoutes.tsx").read_text(encoding="utf-8")
        memory = (ROOT / "frontend" / "src" / "context" / "TabMemoryContext.tsx").read_text(encoding="utf-8")
        layout = (ROOT / "frontend" / "src" / "components" / "nav" / "navigation.ts").read_text(encoding="utf-8")
        self.assertIn('path="/etl"', routes)
        self.assertIn("etl: '/etl'", memory)
        self.assertIn("area: 'etl'", layout)


class HistoryTable(unittest.TestCase):
    def test_the_pipeline_keys_are_the_ones_the_table_allows(self):
        sql = (ROOT / ".cursor" / "db" / "migrate_etl.sql").read_text(encoding="utf-8")
        allowed = set(re.findall(r"'([a-z_]+)'", re.search(r"pipeline\s+TEXT NOT NULL CHECK \(pipeline IN \((.*?)\)\)", sql, re.S).group(1)))
        self.assertEqual(allowed, set(etl.pipelines()))

    def test_the_triggers_are_the_ones_the_table_allows(self):
        sql = (ROOT / ".cursor" / "db" / "migrate_etl.sql").read_text(encoding="utf-8")
        allowed = set(re.findall(r"'([a-z]+)'", re.search(r"trigger\s+TEXT NOT NULL CHECK \(trigger IN \((.*?)\)\)", sql, re.S).group(1)))
        self.assertEqual(allowed, set(etl.TRIGGERS))

    def test_every_column_the_code_writes_exists(self):
        columns = SCHEMA["orion_ods.etl_run"]
        for name in ("pipeline", "scope", "trigger", "started_by", "steps_total", "target", "runner_host", "app_env",
                     "source", "source_fingerprint", "status", "duration_ms", "error", "rows_read", "rows_inserted",
                     "rows_updated", "rows_deleted", "rows_unchanged", "steps_succeeded", "steps_failed", "steps_skipped"):
            self.assertIn(name, columns)
        step = SCHEMA["orion_ods.etl_run_step"]
        for name in ("run_id", "seq", "name", "kind", "target_table", "status", "duration_ms", "target_rows_before",
                     "target_rows_after", "stats", "error", "rows_read"):
            self.assertIn(name, step)


if __name__ == "__main__":
    unittest.main()
