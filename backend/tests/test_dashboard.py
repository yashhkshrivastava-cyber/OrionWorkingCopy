"""Rules behind the Orion dashboards: insights, record sets, and what the dashboard code may read.

No database is needed. The queries themselves are exercised by the dashboard in use; here the rules that are easy to
break without noticing are pinned down.
"""

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.dashboard import insights  # noqa: E402
from app.dashboard.filters import FILTER_KEYS, SCOPES, clause, common  # noqa: E402
from app.dashboard.kpi_help import KPI_HELP  # noqa: E402
from app.dashboard import records  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
DASHBOARD = ROOT / "backend" / "app" / "dashboard"
REGISTRY = ROOT / "frontend" / "src" / "dashboards" / "registry.ts"


def totals(**over):
    base = {
        "bills": 100, "revenue": 1_000_000.0, "billed": 1_180_000.0, "collected": 1_100_000.0, "collection_rate": 93.2,
        "payroll": 700_000.0, "expenses": 100_000.0, "margin": 200_000.0, "margin_pct": 20.0, "payroll_pct": 70.0,
        "expense_pct": 10.0, "salary_pending": 0.0,
    }
    base.update(over)
    return base


class Insights(unittest.TestCase):
    def ids(self, facts):
        return {i["id"] for i in insights.build_insights(facts)}

    def test_nothing_is_said_when_there_are_no_figures(self):
        self.assertEqual(insights.build_insights({}), [])
        self.assertEqual(insights.build_insights({"totals": {"bills": 0, "payroll": 0, "expenses": 0}}), [])

    def test_concentration_is_flagged_only_above_the_watch_level(self):
        low = insights.build_insights({"totals": totals(), "clients": [{"code": "A", "label": "A", "value": 200_000.0}]})
        high = insights.build_insights({"totals": totals(), "clients": [{"code": "A", "label": "A", "value": 400_000.0}]})
        self.assertEqual([i["tone"] for i in low if i["id"] == "concentration"], ["neutral"])
        flagged = [i for i in high if i["id"] == "concentration"][0]
        self.assertEqual(flagged["tone"], "warning")
        self.assertIn(f"{insights.CONCENTRATION_FLAG_PCT:.0f}%", flagged["detail"])
        self.assertEqual(flagged["action"], {"key": "client", "value": "A"})

    def test_overdue_money_points_at_the_oldest_bucket(self):
        found = insights.build_insights({"totals": totals(), "snapshot": {"outstanding": 1_000_000.0, "over90": 400_000.0, "open_bills": 12}})
        item = [i for i in found if i["id"] == "overdue"][0]
        self.assertEqual(item["tone"], "negative")
        self.assertEqual(item["action"], {"key": "bucket", "value": "90+"})

    def test_nothing_overdue_adds_no_action(self):
        found = insights.build_insights({"totals": totals(), "snapshot": {"outstanding": 50_000.0, "over90": 0.0, "open_bills": 2}})
        item = [i for i in found if i["id"] == "overdue"][0]
        self.assertNotIn("action", item)

    def test_a_margin_drop_is_called_out_with_the_points_lost(self):
        previous = totals(margin_pct=26.0)
        found = insights.build_insights({"totals": totals(margin_pct=20.0), "previous": previous, "previous_label": "vs last quarter"})
        item = [i for i in found if i["id"] == "margin_shift"][0]
        self.assertEqual(item["tone"], "negative")
        self.assertIn("6.0 points", item["title"])

    def test_a_small_margin_move_is_not_news(self):
        found = insights.build_insights({"totals": totals(margin_pct=20.0), "previous": totals(margin_pct=19.8), "previous_label": "x"})
        self.assertNotIn("margin_shift", {i["id"] for i in found})

    def test_loss_making_cases_are_totalled_and_the_worst_named(self):
        cases = [{"code": "C1", "label": "Site one", "margin": -50_000.0}, {"code": "C2", "label": "Site two", "margin": -10_000.0}]
        found = insights.build_insights({"totals": totals(), "loss_cases": cases})
        item = [i for i in found if i["id"] == "loss_cases"][0]
        self.assertIn("2 cases", item["title"])
        self.assertEqual(item["action"]["value"], "C1")

    def test_a_missing_input_skips_the_insight_rather_than_guessing(self):
        found = self.ids({"totals": totals()})
        self.assertFalse(found & {"overdue", "dso", "attrition", "win_rate", "km_allowance", "concentration"})

    def test_attrition_is_flagged_above_the_watch_level(self):
        low = insights.build_insights({"totals": totals(), "people": {"attrition": 10.0, "leavers": 5, "joiners": 6, "headcount": 100}})
        high = insights.build_insights({"totals": totals(), "people": {"attrition": 40.0, "leavers": 20, "joiners": 6, "headcount": 100}})
        self.assertEqual([i["tone"] for i in low if i["id"] == "attrition"], ["neutral"])
        self.assertEqual([i["tone"] for i in high if i["id"] == "attrition"], ["warning"])

    def test_no_more_than_the_cap_and_no_repeats(self):
        found = insights.build_insights({"totals": totals(), "monthly": []})
        self.assertLessEqual(len(found), insights.MAX_INSIGHTS)
        ids = [i["id"] for i in found]
        self.assertEqual(len(ids), len(set(ids)))

    def test_a_month_far_from_the_rest_is_a_swing(self):
        monthly = [{"code": f"2026-{m:02d}", "label": f"M{m}", "revenue": 100.0} for m in range(1, 8)]
        monthly.append({"code": "2026-08", "label": "Aug", "revenue": 400.0})
        item = insights._swing(monthly)
        self.assertEqual(item["action"], {"key": "month", "value": "2026-08"})
        self.assertIsNone(insights._swing(monthly[:3]))


class Scopes(unittest.TestCase):
    def test_every_scope_keeps_only_live_warehouse_rows(self):
        for name, scope in SCOPES.items():
            self.assertTrue(
                any("is_current" in part and "is_expired" in part for part in scope["base"]),
                f"{name} does not restrict itself to live warehouse rows",
            )

    def test_every_scope_filter_is_a_known_filter_key(self):
        known = set(FILTER_KEYS)
        for name, scope in SCOPES.items():
            self.assertEqual(sorted(set(scope["fields"]) - known), [], f"{name} has a filter the engine does not know")

    def test_a_click_on_a_dimension_is_reversible(self):
        where, params = clause("bill", {"client": "CL-1", "month": "2026-01"}, exclude=("client",))
        self.assertNotIn("client_code", where)
        self.assertEqual(params, ["2026-01"])

    def test_combined_measures_use_only_the_dimensions_every_fact_has(self):
        shared = common({"client": "CL-1", "designation": "Guard", "expense_type": "EXP-1", "month": "2026-01"}, "bill", "expense", "payroll")
        self.assertEqual(shared, {"client": "CL-1", "month": "2026-01"})

    def test_cancelled_bills_are_left_out_unless_asked_for(self):
        self.assertIn("<> 'Cancelled'", clause("bill", {})[0])
        self.assertNotIn("<> 'Cancelled'", clause("bill", {}, include_cancelled=True)[0])


class RecordSets(unittest.TestCase):
    def test_every_set_names_a_real_default_sort_and_unique_columns(self):
        for name, spec in records.DATASETS.items():
            keys = [c["key"] for c in spec["columns"]]
            self.assertEqual(len(keys), len(set(keys)), f"{name} repeats a column")
            self.assertIn(spec["sort"][0], keys, f"{name} sorts by a column it does not have")
            self.assertIn(spec["scope"], SCOPES)

    def test_sets_that_show_pay_say_who_may_open_them(self):
        self.assertEqual(records.DATASETS["payroll"]["needs"], "ods")
        self.assertEqual(records.DATASETS["employees"]["needs"], "ods")
        self.assertEqual(records.DATASETS["bills"]["needs"], "billing")

    def test_a_sort_column_that_is_not_in_the_set_is_never_put_in_the_query(self):
        class Cursor:
            def __init__(self):
                self.sql = []

            def execute(self, sql, params=None):
                self.sql.append(sql)

            def fetchall(self):
                return [(0,)]

        cur = Cursor()
        try:
            records.fetch(cur, "bills", {}, sort="1; DROP TABLE x --", direction="asc")
        except Exception:  # noqa: S110 - only what was sent to the database matters here, not whether the call refused
            pass
        self.assertFalse(any("DROP TABLE" in sql for sql in cur.sql))


class Contracts(unittest.TestCase):
    def test_the_dashboards_read_the_warehouse_not_the_operational_store(self):
        for path in DASHBOARD.glob("*.py"):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("orion_ods", text, f"{path.name} reads orion_ods; the Orion dashboards read orion_dw")

    def test_every_figure_a_tab_shows_has_plain_language_help(self):
        text = REGISTRY.read_text(encoding="utf-8")
        block = text[text.index("export const DASHBOARDS") : text.index("export const dashboardByView")]
        keys = set(re.findall(r"'([a-z_0-9]+)'", " ".join(re.findall(r"kpiKeys: \[([^\]]*)\]", block))))
        self.assertTrue(keys)
        self.assertEqual(sorted(k for k in keys if k not in KPI_HELP), [], "figures without help in kpi_help.py")

    def test_every_help_entry_explains_what_and_how(self):
        for key, entry in KPI_HELP.items():
            self.assertTrue(entry.get("means") and entry.get("calc"), f"{key} needs both a meaning and a calculation")


if __name__ == "__main__":
    unittest.main()


class Explore(unittest.TestCase):
    def test_every_drill_down_reads_only_dimensions_its_facts_carry(self):
        from app.dashboard import explore

        for key, measure in explore.MEASURES.items():
            for part in measure.parts.values():
                fields = SCOPES[part.scope]["fields"]
                for dim in measure.dims:
                    self.assertIn(dim, fields, f"{key} offers {dim}, which the {part.scope} fact does not carry")

    def test_every_drill_down_opens_a_record_set_that_exists(self):
        from app.dashboard import explore

        for key, measure in explore.MEASURES.items():
            for dataset, _label in measure.records:
                self.assertIn(dataset, records.DATASETS, f"{key} opens {dataset}, which is not a record set")

    def test_a_drill_down_that_is_a_ratio_works_out_each_bar_from_its_own_parts(self):
        from app.dashboard import explore

        measure = explore.MEASURES["margin_pct"]
        self.assertAlmostEqual(measure.combine({"r": 200.0, "p": 120.0, "e": 40.0}), 20.0)
        self.assertEqual(measure.combine({"r": 0.0, "p": 5.0, "e": 5.0}), 0.0)
        self.assertEqual(explore.MEASURES["collection_rate"].combine({"c": 90.0, "b": 100.0}), 90.0)

    def test_figures_that_add_up_say_so_and_ratios_do_not(self):
        from app.dashboard import explore

        self.assertTrue(explore.MEASURES["revenue"].additive)
        for key in ("margin_pct", "collection_rate", "avg_bill", "win_rate", "clients"):
            self.assertFalse(explore.MEASURES[key].additive, key)

    def test_every_tile_with_a_drill_down_has_help(self):
        from app.dashboard import explore

        self.assertEqual(sorted(k for k in explore.MEASURES if k not in KPI_HELP), [])

    def test_tally_drill_downs_name_real_record_sets_and_dimensions(self):
        from app import tally_explore

        for key, measure in tally_explore.MEASURES.items():
            for dataset, _label in measure.records:
                self.assertTrue(dataset == "vouchers" or dataset in tally_explore.SNAPSHOT_DATASET, f"{key} opens {dataset}")
            for dim in measure.dims:
                self.assertIn(dim, tally_explore.DIM_SQL, f"{key} offers {dim}")
            self.assertTrue(measure.expr or measure.snapshot, f"{key} has no expression")

    def test_tally_books_drill_downs_cover_every_balance_tile(self):
        from app import tally_explore

        for key in ("debtors", "gst_payable", "loans", "creditors", "statutory", "cash", "profit_loss"):
            self.assertTrue(tally_explore.MEASURES[key].snapshot, key)


class DrillDownContext(unittest.TestCase):
    """The rows opened from a figure are the rows that count towards it, not the whole table."""

    def test_a_narrowed_figure_narrows_the_rows_it_opens(self):
        from app.dashboard import explore

        extra, cancelled = explore.record_context("won", "opportunities")
        self.assertTrue(any("Closed Won" in part for part in extra))
        self.assertFalse(cancelled)
        self.assertTrue(any("Active" in part for part in explore.record_context("headcount", "employees")[0]))
        self.assertTrue(any("Active" in part for part in explore.record_context("active_cases", "cases")[0]))
        self.assertTrue(any("'No'" in part for part in explore.record_context("salary_pending", "payroll")[0]))

    def test_cancelled_rows_only_count_for_the_figure_about_them(self):
        from app.dashboard import explore

        self.assertEqual(explore.record_context("revenue", "bills"), ((), False))
        self.assertEqual(explore.record_context("expenses", "expenses"), ((), False))
        self.assertTrue(explore.record_context("cancelled_bills", "bills")[1])

    def test_every_narrowed_figure_says_what_is_listed(self):
        from app.dashboard import explore

        for key, measure in explore.MEASURES.items():
            if measure.population and any(measure.population[d][0] for d in measure.population):
                self.assertTrue(measure.population_note, f"{key} narrows its rows but does not say how")
                for dataset in measure.population:
                    self.assertIn(dataset, [d for d, _l in measure.records], f"{key} narrows {dataset}, which it does not open")

    def test_the_default_lists_leave_out_cancelled_bills_and_expenses(self):
        self.assertFalse(records.DATASETS["bills"].get("include_cancelled"))
        self.assertFalse(records.DATASETS["expenses"].get("include_cancelled"))
        self.assertTrue(records.DATASETS["cancelled"]["include_cancelled"])

    def test_narrowed_sets_are_openable_by_a_chart_but_not_offered_in_the_menu(self):
        user = {"role": "admin"}
        everything = {s["id"]: s for s in records.datasets_for(user)}
        for narrowed in ("cancelled", "edited", "gst_pending", "payroll_pending", "open_opps", "active_employees"):
            self.assertTrue(everything[narrowed]["hidden"], narrowed)
        self.assertFalse(everything["bills"]["hidden"])

    def test_tally_documents_are_narrowed_to_the_figure(self):
        from app import tally_explore

        self.assertIn("Credit note", tally_explore.record_context("credit_notes")[0])
        self.assertIn("Sales", tally_explore.record_context("sales")[0])
        self.assertIn("epf_billed", tally_explore.record_context("epf")[0])
        self.assertEqual(tally_explore.record_context("billed"), ())
