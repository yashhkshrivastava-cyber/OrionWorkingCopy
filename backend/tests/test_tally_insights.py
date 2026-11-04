"""Rules behind the Tally dashboard's comparisons and insights.

Run from the backend folder:  python -m unittest discover -s tests -v
"""

import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.tally_insights import (  # noqa: E402
    CONCENTRATION_FLAG_PCT,
    MAX_INSIGHTS,
    build_insights,
    comparison_windows,
    selected_window,
    top_movers,
    validate_filters,
)

LO, HI = date(2025, 4, 1), date(2026, 9, 23)  # first billed day, last billed day


class ValidateFilters(unittest.TestCase):
    def test_valid_filters_pass_through(self):
        clean, problems = validate_filters({"month": "2026-07", "fy": "2025", "client": "X"})
        self.assertEqual(clean, {"month": "2026-07", "fy": "2025", "client": "X"})
        self.assertEqual(problems, [])

    def test_unusable_values_are_dropped_and_reported(self):
        clean, problems = validate_filters({"month": "2026-13", "from": "garbage", "fy": "abcd"})
        self.assertEqual(clean, {})
        self.assertEqual({p["key"] for p in problems}, {"month", "from", "fy"})

    def test_reversed_dates_are_swapped_not_dropped(self):
        clean, problems = validate_filters({"from": "2026-08-31", "to": "2026-06-01"})
        self.assertEqual((clean["from"], clean["to"]), ("2026-06-01", "2026-08-31"))
        self.assertEqual(len(problems), 1)


class Windows(unittest.TestCase):
    def test_no_filters_means_no_window_and_no_comparison(self):
        self.assertIsNone(selected_window({}, LO, HI))
        self.assertEqual(comparison_windows({}, LO, HI), {"previous": None, "yoy": None, "full": None})

    def test_month_compares_with_previous_month_and_same_month_last_year(self):
        result = comparison_windows({"month": "2026-07"}, LO, HI)
        self.assertEqual(result["previous"]["filters"]["from"], "2026-06-01")
        self.assertEqual(result["previous"]["filters"]["to"], "2026-06-30")
        self.assertEqual(result["yoy"]["filters"]["from"], "2025-07-01")
        self.assertEqual(result["yoy"]["filters"]["to"], "2025-07-31")

    def test_part_billed_month_compares_like_for_like(self):
        result = comparison_windows({"month": "2026-09"}, LO, HI)  # billed to 23 Sep only
        self.assertEqual(result["previous"]["filters"]["to"], "2026-08-23")
        self.assertEqual(result["yoy"]["filters"]["to"], "2025-09-23")
        self.assertTrue(result["previous"]["like_for_like"])
        self.assertIn("1–23", result["previous"]["label"])

    def test_no_comparison_where_the_data_does_not_reach_back(self):
        result = comparison_windows({"month": "2025-04"}, LO, HI)
        self.assertEqual(result, {"previous": None, "yoy": None, "full": None})
        result = comparison_windows({"from": "2025-04-01", "to": "2025-06-30"}, LO, HI)
        self.assertEqual(result, {"previous": None, "yoy": None, "full": None})

    def test_financial_year_compares_the_same_months_of_the_year_before(self):
        result = comparison_windows({"fy": "2026"}, LO, HI)  # FY 2026-27, in progress
        previous = result["previous"]
        self.assertEqual(previous["filters"]["from"], "2025-04-01")
        self.assertEqual(previous["filters"]["to"], "2025-09-23")
        self.assertIn("FY 2025-26", previous["label"])
        self.assertIsNone(result["yoy"])  # same comparison, shown once

    def test_range_compares_with_equal_length_period_before(self):
        result = comparison_windows({"from": "2026-06-01", "to": "2026-08-31"}, LO, HI)
        self.assertEqual(result["previous"]["filters"]["to"], "2026-05-31")
        self.assertEqual(result["previous"]["filters"]["from"], "2026-03-01")
        self.assertIsNotNone(result["yoy"])

    def test_comparison_keeps_the_other_filters(self):
        result = comparison_windows({"month": "2026-07", "client": "ACME"}, LO, HI)
        self.assertEqual(result["previous"]["filters"]["client"], "ACME")
        self.assertNotIn("month", result["previous"]["filters"])


class Movers(unittest.TestCase):
    def test_largest_gain_and_fall(self):
        gainers, losers = top_movers({"A": 100, "B": 50, "C": 0}, {"A": 40, "B": 90, "D": 30})
        self.assertEqual(gainers[0], ("A", 60))
        self.assertEqual(losers[0], ("B", -40))
        self.assertIn(("D", -30), losers)


def _months(values):
    return [
        {"code": f"2026-{i + 1:02d}", "label": f"M{i + 1}", "billed": v, "revenue": v}
        for i, v in enumerate(values)
    ]


def _insights(**over):
    base = dict(
        totals={"billed": 100.0, "revenue": 90.0, "invoices": 10, "cn_count": 0, "cn_billed": 0.0, "sales_billed": 100.0},
        previous=None,
        previous_label="",
        yoy=None,
        monthly=_months([10, 10, 10, 10, 10, 10]),
        clients=[],
        gainers=[],
        losers=[],
        mover_basis="",
        mover_months=None,
        notes=[],
        income_groups=[],
        data_end=date(2026, 6, 30),
    )
    base.update(over)
    return build_insights(**base)


class Insights(unittest.TestCase):
    def ids(self, items):
        return [item["id"] for item in items]

    def test_nothing_is_said_when_nothing_matches(self):
        self.assertEqual(_insights(totals={"invoices": 0, "billed": 0}), [])

    def test_steady_months_produce_no_swing(self):
        self.assertNotIn("swing", self.ids(_insights()))

    def test_a_month_far_from_the_rest_is_called_out_with_its_numbers(self):
        items = _insights(monthly=_months([10, 10, 10, 10, 10, 50]))
        swing = next(item for item in items if item["id"] == "swing")
        self.assertIn("5.0×", swing["title"])
        self.assertEqual(swing["action"], {"key": "month", "value": "2026-06"})

    def test_swing_needs_enough_months(self):
        self.assertNotIn("swing", self.ids(_insights(monthly=_months([10, 10, 50]))))

    def test_swing_is_skipped_when_a_month_is_selected(self):
        items = _insights(monthly=_months([10, 10, 10, 10, 10, 50]), month_selected=True)
        self.assertNotIn("swing", self.ids(items))

    def test_concentration_flags_only_above_the_watch_level(self):
        low = [{"code": "A", "revenue": 20.0}, {"code": "B", "revenue": 10.0}]
        high = [{"code": "A", "revenue": 40.0}, {"code": "B", "revenue": 10.0}]
        def tone(clients):
            return next(i for i in _insights(clients=clients) if i["id"] == "concentration")["tone"]

        self.assertEqual(tone(low), "neutral")
        self.assertEqual(tone(high), "warning")
        self.assertEqual(CONCENTRATION_FLAG_PCT, 30.0)

    def test_period_change_follows_the_sign_of_the_change(self):
        prev = {"billed": 80.0, "invoices": 5}
        up = next(i for i in _insights(previous=prev, previous_label="vs X") if i["id"] == "period_change")
        self.assertEqual(up["tone"], "positive")
        self.assertIn("up 25.0%", up["title"])
        down = next(
            i
            for i in _insights(previous={"billed": 200.0, "invoices": 5}, previous_label="vs X")
            if i["id"] == "period_change"
        )
        self.assertEqual(down["tone"], "negative")

    def test_credit_notes_are_reported_with_their_rate(self):
        totals = {"billed": 90.0, "revenue": 80.0, "invoices": 11, "cn_count": 1, "cn_billed": -10.0, "sales_billed": 100.0}
        notes = [{"type": "Credit note", "billed": -10.0, "client": "ACME", "date": "2026-03-01"}]
        item = next(i for i in _insights(totals=totals, notes=notes) if i["id"] == "credit_notes")
        self.assertIn("1 credit note worth", item["title"])
        self.assertIn("10.0% of sales", item["detail"])
        self.assertEqual(item["tab"], "credit-notes")

    def test_partial_month_warning_only_when_that_month_is_in_view(self):
        monthly = _months([10, 10, 10, 10, 10, 10])
        def partial(**kw):
            return "partial_month" in self.ids(_insights(monthly=monthly, data_end=date(2026, 6, 20), **kw))

        self.assertTrue(partial())
        self.assertTrue(partial(window=(date(2026, 6, 1), date(2026, 6, 30))))
        self.assertFalse(partial(window=(date(2026, 3, 1), date(2026, 3, 31))))

    def test_zero_value_documents_are_reported_with_the_fair_average(self):
        totals = {"billed": 900.0, "revenue": 800.0, "invoices": 10, "zero_docs": 1, "cn_count": 0, "cn_billed": 0.0, "sales_billed": 900.0}
        item = next(i for i in _insights(totals=totals) if i["id"] == "zero_value")
        self.assertEqual(item["title"], "1 of 10 documents (10%) have no value")
        self.assertIn("₹100", item["detail"])  # 900 / 9 documents with a value
        self.assertNotIn("zero_value", self.ids(_insights()))

    def test_never_more_than_the_cap(self):
        items = _insights(
            previous={"billed": 50.0, "invoices": 5},
            yoy={"billed": 60.0, "invoices": 5},
            monthly=_months([10, 10, 10, 10, 10, 50]),
            clients=[{"code": "A", "revenue": 60.0}],
            totals={"billed": 100.0, "revenue": 90.0, "invoices": 10, "cn_count": 1, "cn_billed": -5.0, "sales_billed": 100.0},
            income_groups=[{"code": "a", "label": "A", "value": 60}, {"code": "b", "label": "B", "value": 30}],
            data_end=date(2026, 6, 10),
        )
        self.assertLessEqual(len(items), MAX_INSIGHTS)


if __name__ == "__main__":
    unittest.main()


class DataThrough(unittest.TestCase):
    """The "Latest billed document" date must be a document's date, never today's."""

    def test_no_documents_means_no_date(self):
        from app.tally_dashboard import _data_through

        # what _data_span returns on an empty warehouse: no first day, today as the upper bound
        self.assertEqual(_data_through({"min": "", "max": date.today().isoformat()}), "")

    def test_with_documents_it_is_the_latest_one(self):
        from app.tally_dashboard import _data_through

        self.assertEqual(_data_through({"min": "2025-04-01", "max": "2026-09-23"}), "2026-09-23")
