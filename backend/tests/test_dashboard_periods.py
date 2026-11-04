"""The financial year as the dashboards' default, and a year in progress set against the year before in two ways.

The windows are pure, so most of this needs no database. The last class runs the two dashboards against the development
database when ORION_DASHBOARD_DB_TESTS=1.
"""

import os
import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.dashboard.engine import full_change  # noqa: E402
from app.dashboard.windows import (  # noqa: E402
    ALL_YEARS,
    THIS_FY,
    comparison_windows,
    fy_start_year,
    resolve_fy,
    validate_filters,
)

LO, HI = date(2023, 1, 1), date(2026, 9, 30)


class TheFinancialYearWeAreIn(unittest.TestCase):
    def test_a_financial_year_runs_april_to_march(self):
        self.assertEqual(fy_start_year(date(2026, 4, 1)), 2026)
        self.assertEqual(fy_start_year(date(2027, 3, 31)), 2026)
        self.assertEqual(fy_start_year(date(2026, 3, 31)), 2025)

    def test_current_becomes_the_year_today_is_in(self):
        self.assertEqual(resolve_fy({"fy": THIS_FY}, HI, today=date(2026, 10, 18))["fy"], "2026")
        self.assertEqual(resolve_fy({"fy": THIS_FY}, HI, today=date(2027, 2, 1))["fy"], "2026")

    def test_a_new_year_with_no_data_yet_still_opens_on_the_year_that_has_some(self):
        # Opened on 5 April with bills only to 31 March: the new year is empty, so the one just ended is shown.
        self.assertEqual(resolve_fy({"fy": THIS_FY}, date(2027, 3, 31), today=date(2027, 4, 5))["fy"], "2026")

    def test_data_dated_ahead_of_today_does_not_move_the_year(self):
        self.assertEqual(resolve_fy({"fy": THIS_FY}, date(2027, 6, 30), today=date(2026, 10, 18))["fy"], "2026")

    def test_all_means_no_financial_year_filter(self):
        self.assertEqual(resolve_fy({"fy": ALL_YEARS, "client": "CL-1"}, HI), {"client": "CL-1"})

    def test_everything_else_is_left_alone(self):
        raw = {"fy": "2025", "client": "CL-1", "month": "2025-07"}
        self.assertEqual(resolve_fy(raw, HI), raw)
        self.assertEqual(resolve_fy({}, HI), {})

    def test_the_names_are_not_years_until_they_are_resolved(self):
        clean, problems = validate_filters({"fy": THIS_FY})
        self.assertEqual(clean, {})
        self.assertEqual(problems[0]["key"], "fy")
        clean, problems = validate_filters(resolve_fy({"fy": THIS_FY}, HI, today=date(2026, 10, 18)))
        self.assertEqual((clean, problems), ({"fy": "2026"}, []))


class AYearInProgressAgainstTheYearBefore(unittest.TestCase):
    def test_it_is_set_against_the_same_stretch_and_against_the_whole_year(self):
        result = comparison_windows({"fy": "2026"}, LO, HI)  # FY 2026-27, data to 30 Sep
        same, whole = result["previous"], result["full"]
        self.assertEqual((same["filters"]["from"], same["filters"]["to"]), ("2025-04-01", "2025-09-30"))
        self.assertEqual((whole["filters"]["from"], whole["filters"]["to"]), ("2025-04-01", "2026-03-31"))
        self.assertEqual(same["label"], "vs FY 2025-26, same period")
        self.assertEqual(whole["label"], "vs full FY 2025-26")
        self.assertIsNone(result["yoy"])

    def test_a_finished_year_has_one_comparison_because_the_two_are_the_same(self):
        result = comparison_windows({"fy": "2025"}, LO, HI)
        self.assertIsNotNone(result["previous"])
        self.assertIsNone(result["full"])
        self.assertEqual(result["previous"]["filters"]["to"], "2025-03-31")

    def test_neither_comparison_is_offered_where_the_data_does_not_reach_back(self):
        result = comparison_windows({"fy": "2023"}, date(2023, 6, 1), HI)
        self.assertEqual(result, {"previous": None, "yoy": None, "full": None})

    def test_months_and_ranges_keep_their_own_comparisons_and_have_no_full_year(self):
        self.assertIsNone(comparison_windows({"month": "2026-07"}, LO, HI)["full"])
        self.assertIsNone(comparison_windows({"from": "2026-05-01", "to": "2026-08-31"}, LO, HI)["full"])
        self.assertIsNotNone(comparison_windows({"month": "2026-07"}, LO, HI)["yoy"])

    def test_all_time_has_nothing_to_compare_with(self):
        self.assertEqual(comparison_windows({}, LO, HI), {"previous": None, "yoy": None, "full": None})


class TheChangeAgainstTheWholeYear(unittest.TestCase):
    def test_a_rise_and_a_fall(self):
        up = full_change(150, 100, label="vs full FY 2025-26", value="₹100", range_text="1 Apr – 31 Mar")
        self.assertEqual((up["delta"], up["delta_type"], up["delta_pct"]), ("+50.0%", "positive", 50.0))
        self.assertEqual((up["compare"], up["value"], up["range"]), ("vs full FY 2025-26", "₹100", "1 Apr – 31 Mar"))
        down = full_change(60, 100, label="x", value="100")
        self.assertEqual((down["delta"], down["delta_type"]), ("-40.0%", "negative"))

    def test_where_a_rise_is_bad_news_the_colour_follows_the_meaning(self):
        cost = full_change(120, 100, label="x", value="100", higher_is_better=False)
        self.assertEqual((cost["delta"], cost["delta_type"]), ("+20.0%", "negative"))

    def test_a_percentage_is_compared_in_points(self):
        margin = full_change(26.7, -253.9, label="x", value="-253.9%", points=True)
        self.assertEqual((margin["delta"], margin["delta_type"], margin["delta_pct"]), ("+280.6 pts", "positive", None))
        self.assertEqual(full_change(10.0, 10.02, label="x", value="v", points=True)["delta"], "flat")

    def test_nothing_is_claimed_where_there_is_nothing_to_set_it_against(self):
        self.assertIsNone(full_change(5, None, label="x", value=""))
        self.assertIsNone(full_change(None, 5, label="x", value="5"))
        self.assertIsNone(full_change(5, 0, label="x", value="0"))  # a change from nothing is not a percentage

    def test_switching_the_comparison_does_not_move_the_page(self):
        # The tab strip used to scroll the whole page back to itself from a ref, on every render of the dashboard, so
        # anything that re-rendered it (this switch included) threw the reader back to the top.
        tabs = (ROOT / "frontend" / "src" / "components" / "dashboard" / "ViewTabs.tsx").read_text(encoding="utf-8")
        self.assertNotIn("scrollIntoView(", tabs.replace("scrollIntoView` from a ref", ""))
        board = (ROOT / "frontend" / "src" / "components" / "dashboard" / "MetricCard.tsx").read_text(encoding="utf-8")
        # a card keeps the room for its second comparison, so it is the same height in either mode
        self.assertIn('aria-hidden="true" />}', board)

    def test_the_period_follows_through_to_the_screen(self):
        # The screens send "current" when no period is chosen, and "all" for every year; the server answers with the year.
        page = (ROOT / "frontend" / "src" / "dashboards" / "useDashboard.ts").read_text(encoding="utf-8")
        self.assertIn("{ ...filters, fy: 'current' }", page)
        compare = (ROOT / "frontend" / "src" / "dashboards" / "compare.ts").read_text(encoding="utf-8")
        self.assertIn("kpi.full", compare)


@unittest.skipUnless(os.environ.get("ORION_DASHBOARD_DB_TESTS") == "1", "needs the development database")
class TheDashboardsAgainstTheDatabase(unittest.TestCase):
    def test_orion_answers_the_current_year_with_both_comparisons_on_every_period_figure(self):
        from app import dashboard

        payload = dashboard.build_view("overview", {"fy": THIS_FY})
        self.assertRegex(payload["filters"]["fy"], r"^\d{4}$")
        self.assertEqual(payload["meta"]["comparison"]["kind"], "fy")
        for item in payload["kpis"]:
            self.assertIn("full", item, item["key"])
            if item["scope"] == "snapshot":
                self.assertIsNone(item["full"], item["key"])
        # No period figure on any tab is left out of the comparison (attrition, days to decide, cars and km per day were).
        for view in ("people", "pipeline", "fleet", "collections", "profitability", "controls"):
            for item in dashboard.build_view(view, {"fy": THIS_FY})["kpis"]:
                if item["scope"] == "period":
                    note = (item.get("detail") or {}).get("note", "")
                    self.assertNotIn("not compared with an earlier period", note.lower(), f"{view}: {item['key']}")
        every = dashboard.build_view("overview", {"fy": ALL_YEARS})
        self.assertEqual(every["filters"], {})
        self.assertEqual(every["meta"]["comparison"]["kind"], "all")

    def test_tally_answers_the_same_way(self):
        from app import tally_dashboard

        payload = tally_dashboard.build_tally_dashboard({"fy": THIS_FY})
        self.assertRegex(payload["filters"]["fy"], r"^\d{4}$")
        self.assertEqual(payload["meta"]["comparison"]["kind"], "fy")
        self.assertTrue(any(item.get("full") for item in payload["kpis"]))
        # The income lines and the percentages are compared too, not only the money totals.
        by_key = {item["key"]: item for item in payload["kpis"]}
        for key in ("manpower", "gst_pct", "cn_rate", "top_share", "avg_revenue"):
            self.assertTrue(by_key[key]["delta"] or by_key[key].get("full"), key)
        self.assertEqual(tally_dashboard.build_tally_dashboard({"fy": ALL_YEARS})["filters"], {})


if __name__ == "__main__":
    unittest.main()
