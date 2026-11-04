"""The forecasting engine: that it recovers what is in a series, that its ranges are honest, and that it says so when the history is too short.
No database."""

import math
import os
import random
import sys
import time
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402
from unittest import mock  # noqa: E402

from app import forecast as fc  # noqa: E402
from app.dependencies import get_current_user  # noqa: E402
from app.main import app  # noqa: E402

TODAY = date(2026, 10, 20)


def months(count, start="2023-01"):
    return [fc.month_add(start, i) for i in range(count)]


def series(values, start="2023-01"):
    return list(zip(months(len(values), start), values))


def run(values, start="2023-01", **kw):
    kw.setdefault("as_of", None)
    return fc.forecast_series(series(values, start), **kw)


def noisy(count, base, slope=0.0, noise=0.0, seed=1, season=None):
    rng = random.Random(seed)
    out = []
    for t in range(count):
        v = base + slope * t + rng.gauss(0, noise)
        if season:
            v += season[t % 12]
        out.append(v)
    return out


class Helpers(unittest.TestCase):
    def test_months_and_financial_years(self):
        self.assertEqual(fc.month_add("2026-11", 3), "2027-02")
        self.assertEqual(fc.month_add("2026-01", -1), "2025-12")
        self.assertEqual(fc.months_between("2025-10", "2026-02"), 4)
        self.assertEqual(fc.fiscal_year("2026-03"), "2025-26")
        self.assertEqual(fc.fiscal_year("2026-04"), "2026-27")
        self.assertEqual(fc.fiscal_year("2027-01"), "2026-27")


class WhatIsInTheHistory(unittest.TestCase):
    def test_nothing_to_forecast(self):
        for empty in ([], [("2026-01", 0.0), ("2026-02", 0.0)], [("2026-01", float("nan"))]):
            out = fc.forecast_series(empty)
            self.assertFalse(out["available"])
            self.assertTrue(out["notes"])

    def test_a_straight_trend_is_followed(self):
        out = run([100 + 5 * t for t in range(36)])
        self.assertTrue(out["available"])
        truth = [100 + 5 * (36 + h) for h in range(12)]
        got = [r["expected"] for r in out["forecast"][:12]]
        for g, t in zip(got, truth):
            self.assertAlmostEqual(g / t, 1.0, delta=0.06)

    def test_a_flat_series_stays_flat_with_a_narrow_range(self):
        out = run([1000.0] * 30)
        for row in out["forecast"][:12]:
            self.assertAlmostEqual(row["expected"], 1000.0, delta=15)
        first = out["forecast"][0]
        self.assertLess((first["p90"] - first["p10"]) / first["expected"], 0.2)

    def test_the_seasonal_pattern_is_learned(self):
        pattern = [-300, -200, 0, 100, 300, 500, 400, 200, 0, -100, -300, -500]
        values = noisy(48, 5000, slope=10, noise=40, season=pattern)
        out = run(values, start="2022-01")
        self.assertTrue(out["model"]["seasonal"])
        self.assertGreater(out["seasonality"]["strength"], 0.6)
        effects = [row["effect_pct"] for row in out["seasonality"]["index"]]
        self.assertAlmostEqual(sum(effects), 0.0, delta=1.0)
        # the best month is June in the data (index 5), the worst December (11)
        self.assertEqual(effects.index(max(effects)), 5)
        self.assertEqual(effects.index(min(effects)), 11)
        # next year follows the pattern: June above the year's average, December below
        year = out["forecast"][:12]
        june = next(r for r in year if r["month"].endswith("-06"))["expected"]
        december = next(r for r in year if r["month"].endswith("-12"))["expected"]
        self.assertGreater(june - december, 600)

    def test_a_level_shift_is_learned_from_the_new_level(self):
        values = noisy(24, 100, noise=2, seed=3) + noisy(24, 200, noise=3, seed=4)
        out = run(values)
        self.assertEqual(out["model"]["from"], fc.month_add("2023-01", 24))
        self.assertTrue(any("level changed" in n for n in out["notes"]))
        self.assertAlmostEqual(out["forecast"][0]["expected"], 200, delta=12)

    def test_a_shift_too_recent_to_learn_from_widens_the_range(self):
        values = noisy(20, 100, noise=2, seed=5) + noisy(4, 200, noise=2, seed=6)
        out = run(values)
        self.assertTrue(any("too recently" in n for n in out["notes"]))
        self.assertIn(out["confidence"]["level"], ("low", "very_low"))

    def test_a_one_off_spike_does_not_move_the_forecast(self):
        base = noisy(30, 1000, noise=10, seed=7)
        spiked = list(base)
        spiked[20] = 9000
        clean_out, spiked_out = run(base), run(spiked)
        self.assertIn("smoothed", " ".join(spiked_out["notes"]))
        self.assertAlmostEqual(spiked_out["forecast"][0]["expected"], clean_out["forecast"][0]["expected"], delta=40)

    def test_a_month_with_no_data_inside_the_history_is_treated_as_a_gap(self):
        values = noisy(30, 1000, noise=10, seed=8)
        values[15] = 0.0
        out = run(values)
        self.assertIn("smoothed", " ".join(out["notes"]))
        self.assertAlmostEqual(out["forecast"][0]["expected"], 1000, delta=60)

    def test_the_month_in_progress_is_left_out(self):
        data = series([100.0 + t for t in range(10)], start="2026-01")  # 2026-01 .. 2026-10
        out = fc.forecast_series(data, as_of=TODAY)
        self.assertEqual(out["data_through"], "2026-09")
        self.assertTrue(any("in progress" in n for n in out["notes"]))
        self.assertEqual(out["first_forecast"], "2026-10")

    def test_leading_empty_months_are_dropped(self):
        out = run([0, 0, 0, 0] + [100.0 + t for t in range(20)])
        self.assertEqual(out["history"][0]["month"], "2023-05")

    def test_duplicates_are_added_and_unsorted_input_is_ordered(self):
        data = [("2026-03", 10.0), ("2026-01", 10.0), ("2026-02", 10.0), ("2026-02", 5.0), ("2026-04", None), ("2026-05", True)]
        out = fc.forecast_series(data)
        by = {h["month"]: h["value"] for h in out["history"]}
        self.assertEqual(by["2026-02"], 15.0)
        self.assertEqual(list(by), ["2026-01", "2026-02", "2026-03"])


class WhenItShouldNotBeSure(unittest.TestCase):
    def test_a_short_history_says_so_and_has_a_wide_range(self):
        out = run([100.0, 110.0, 105.0, 120.0])
        self.assertEqual(out["confidence"]["level"], "very_low")
        row = out["forecast"][11]
        self.assertGreater((row["p90"] - row["p10"]) / row["expected"], 0.4)
        self.assertTrue(any("Too few months" in n for n in out["notes"]))

    def test_nine_months_cannot_be_confident_and_the_far_end_is_flagged(self):
        out = run(noisy(9, 1000, slope=20, noise=15, seed=9))
        self.assertIn(out["confidence"]["level"], ("low", "very_low"))
        self.assertTrue(any("indicative" in n for n in out["notes"]))

    def test_more_history_is_never_less_confident(self):
        order = ["very_low", "low", "medium", "high"]
        short = run(noisy(12, 1000, slope=5, noise=10, seed=10))["confidence"]["level"]
        long_ = run(noisy(60, 1000, slope=5, noise=10, seed=10))["confidence"]["level"]
        self.assertGreaterEqual(order.index(long_), order.index(short))

    def test_a_noisy_series_gets_a_wider_range_than_a_steady_one(self):
        steady = run(noisy(36, 1000, noise=5, seed=11))
        wild = run(noisy(36, 1000, noise=150, seed=11))
        s, w = steady["forecast"][5], wild["forecast"][5]
        self.assertGreater(w["p90"] - w["p10"], 3 * (s["p90"] - s["p10"]))

    def test_the_range_widens_with_distance(self):
        out = run(noisy(40, 1000, slope=4, noise=30, seed=12))
        widths = [r["p90"] - r["p10"] for r in out["forecast"]]
        self.assertTrue(all(b >= a - 1e-6 for a, b in zip(widths, widths[1:])))
        self.assertGreater(widths[35], 1.5 * widths[0])

    def test_95_wraps_80_which_wraps_the_forecast(self):
        for row in run(noisy(36, 1000, slope=3, noise=40, seed=13))["forecast"]:
            self.assertLessEqual(row["p025"], row["p10"] + 1e-9)
            self.assertLessEqual(row["p10"], row["expected"] + 1e-9)
            self.assertLessEqual(row["expected"], row["p90"] + 1e-9)
            self.assertLessEqual(row["p90"], row["p975"] + 1e-9)

    def test_the_80_per_cent_range_holds_about_80_per_cent_of_what_happens(self):
        hits = total = 0
        for seed in range(40):
            rng = random.Random(1000 + seed)
            level, values = 1000.0, []
            for _t in range(54):
                level += rng.gauss(4, 6)
                values.append(level + rng.gauss(0, 35))
            train, future = values[:48], values[48:]
            out = run(train)
            for row, actual in zip(out["forecast"][:6], future):
                total += 1
                hits += row["p10"] <= actual <= row["p90"]
        coverage = hits / total
        self.assertGreater(coverage, 0.62, coverage)
        self.assertLess(coverage, 0.96, coverage)

    def test_a_forecast_that_beats_the_guess_has_positive_skill_and_one_that_cannot_does_not(self):
        trending = run(noisy(48, 500, slope=12, noise=10, seed=14))
        self.assertGreater(trending["accuracy"]["skill"], 0.1)
        pure_noise = run(noisy(48, 1000, noise=120, seed=15))
        self.assertLess(pure_noise["accuracy"]["skill"], 0.2)


class WhatComesOut(unittest.TestCase):
    def setUp(self):
        self.out = run(noisy(40, 1000, slope=6, noise=20, seed=16))

    def test_thirty_six_months_ahead_in_order(self):
        rows = self.out["forecast"]
        self.assertEqual(len(rows), 36)
        self.assertEqual(rows[0]["month"], fc.month_add(self.out["data_through"], 1))
        self.assertEqual([r["month"] for r in rows], [fc.month_add(self.out["data_through"], h) for h in range(1, 37)])

    def test_the_horizons_are_sums_of_the_months_and_widen(self):
        by = {h["months"]: h for h in self.out["horizons"]}
        self.assertEqual(sorted(by), [1, 3, 6, 12, 36])
        self.assertAlmostEqual(by[3]["expected"], sum(r["expected"] for r in self.out["forecast"][:3]), places=6)
        self.assertAlmostEqual(by[36]["expected"], sum(r["expected"] for r in self.out["forecast"]), places=6)
        for h in by.values():
            self.assertLess(h["p10"], h["expected"])
            self.assertGreater(h["p90"], h["expected"])
        relative = [(h["p90"] - h["p10"]) / h["expected"] for h in (by[1], by[12], by[36])]
        self.assertLess(relative[0], relative[2])
        # a quarter of months is not as uncertain as the sum of three months' worth of worst cases
        quarter_sum_of_bounds = sum(r["p90"] - r["p10"] for r in self.out["forecast"][:3])
        self.assertLess(by[3]["p90"] - by[3]["p10"], quarter_sum_of_bounds + 1e-6)

    def test_each_horizon_is_compared_with_the_same_length_just_gone(self):
        by = {h["months"]: h for h in self.out["horizons"]}
        raw = [h["value"] for h in self.out["history"]]
        self.assertAlmostEqual(by[6]["previous"], sum(raw[-6:]), delta=0.2)
        self.assertAlmostEqual(by[6]["change_pct"], (by[6]["expected"] / sum(raw[-6:]) - 1) * 100, places=2)

    def test_financial_years_add_what_has_happened_to_what_is_expected(self):
        out = run([100.0 + t for t in range(20)], start="2025-04", as_of=date(2026, 12, 15))  # data to 2026-11
        years = {y["fy"]: y for y in out["years"]}
        self.assertIn("2026-27", years)
        y = years["2026-27"]
        self.assertTrue(y["complete"])
        self.assertEqual(y["actual_months"] + y["forecast_months"], 12)
        self.assertGreater(y["expected"], y["actual"])
        self.assertLess(y["p10"], y["expected"])

    def test_the_drivers(self):
        d = self.out["drivers"]
        self.assertAlmostEqual(d["run_rate_per_year"], d["run_rate_per_month"] * 12, places=6)
        self.assertGreater(d["growth_yoy_pct"], 0)
        self.assertIsNotNone(d["pace_pct_per_year"])

    def test_the_models_that_were_used_and_their_weights(self):
        weights = [c["weight"] for c in self.out["model"]["components"]]
        self.assertAlmostEqual(sum(weights), 1.0, places=2)
        self.assertTrue(all(w > 0 for w in weights))

    def test_a_series_that_cannot_be_negative_is_never_forecast_below_zero(self):
        out = run([max(0.0, 500 - 25 * t) + 1 for t in range(24)])
        for row in out["forecast"]:
            self.assertGreaterEqual(row["p025"], 0.0)
            self.assertGreaterEqual(row["expected"], 0.0)

    def test_a_signed_series_may_go_below_zero(self):
        out = run([100 - 12 * t + (3 if t % 2 else -3) for t in range(24)], non_negative=False)
        self.assertLess(out["forecast"][-1]["expected"], 0)

    def test_what_goes_to_the_screen_has_no_working_fields_and_no_nan(self):
        shown = fc.public(self.out)
        self.assertNotIn("sigma", str(shown))
        self.assertEqual(fc.public({"x": float("nan"), "y": 1.23456})["y"], 1.23)
        self.assertIsNone(fc.public({"x": float("inf")})["x"])

    def test_it_is_deterministic_and_fast(self):
        values = noisy(120, 5000, slope=10, noise=100, seed=17, season=[0, 50, 100, 150, 100, 50, 0, -50, -100, -150, -100, -50])
        started = time.monotonic()
        a = run(values)
        elapsed = time.monotonic() - started
        b = run(values)
        self.assertEqual(a["forecast"], b["forecast"])
        self.assertLess(elapsed, 5.0)


class Differences(unittest.TestCase):
    def test_margin_is_revenue_less_cost_and_its_spread_follows_from_both(self):
        revenue = run(noisy(40, 1000, slope=6, noise=20, seed=21), label="Revenue")
        cost = run(noisy(40, 700, slope=3, noise=15, seed=22), label="Cost")
        margin = fc.difference(revenue, cost, label="Margin")
        self.assertTrue(margin["available"])
        for m, r, c in zip(margin["forecast"], revenue["forecast"], cost["forecast"]):
            self.assertAlmostEqual(m["expected"], r["expected"] - c["expected"], places=6)
        first = margin["forecast"][0]
        independent = math.sqrt(revenue["forecast"][0]["sigma"] ** 2 + cost["forecast"][0]["sigma"] ** 2)
        self.assertLess(first["sigma"], independent)  # costs move with revenue: steadier than if they were independent
        self.assertAlmostEqual(margin["history"][-1]["value"], revenue["history"][-1]["value"] - cost["history"][-1]["value"], places=1)

    def test_it_needs_both_parts(self):
        revenue = run([100.0 + t for t in range(20)])
        nothing = fc.forecast_series([])
        self.assertFalse(fc.difference(revenue, nothing, label="Margin")["available"])

    def test_it_takes_the_lower_confidence(self):
        long_ = run(noisy(60, 1000, slope=5, noise=10, seed=23))
        short = run([100.0, 105.0, 110.0, 108.0], start=fc.month_add("2023-01", 56))  # ends in the same month as the long one
        self.assertEqual(fc.difference(long_, short, label="Margin")["confidence"]["level"], "very_low")


class TheEndpoints(unittest.TestCase):
    def setUp(self):
        app.dependency_overrides.clear()
        self.addCleanup(app.dependency_overrides.clear)

    def test_nobody_signed_out_gets_a_forecast(self):
        for path in ("/api/dashboard/forecast", "/api/tally-dashboard/forecast"):
            self.assertIn(TestClient(app).get(path).status_code, (401, 403), path)

    def test_each_forecast_follows_its_own_dashboard_permission(self):
        app.dependency_overrides[get_current_user] = lambda: {"id": 5, "role": "viewer", "orion_dashboard_access": True, "tally_dashboard_access": False}
        with mock.patch("app.routers.dashboard_router.build_forecast", return_value={"ready": True}) as orion, mock.patch("app.routers.tally_dashboard_router.build_tally_forecast", return_value={"ready": True}) as tally:
            client = TestClient(app)
            self.assertEqual(client.get("/api/dashboard/forecast?client=CL-0001").status_code, 200)
            self.assertEqual(orion.call_args.args[0], {"client": "CL-0001"})  # the filters reach the builder, and the route is not the {view} one
            self.assertEqual(client.get("/api/tally-dashboard/forecast").status_code, 403)
            tally.assert_not_called()
        app.dependency_overrides[get_current_user] = lambda: {"id": 5, "role": "viewer", "orion_dashboard_access": False, "tally_dashboard_access": True}
        with mock.patch("app.routers.dashboard_router.build_forecast") as orion, mock.patch("app.routers.tally_dashboard_router.build_tally_forecast", return_value={"ready": True}):
            self.assertEqual(TestClient(app).get("/api/dashboard/forecast").status_code, 403)
            orion.assert_not_called()
            self.assertEqual(TestClient(app).get("/api/tally-dashboard/forecast").status_code, 200)


class TheCopilotTool(unittest.TestCase):
    ORION = {"id": 1, "role": "viewer", "orion_dashboard_access": True, "tally_dashboard_access": False}
    TALLY = {"id": 2, "role": "viewer", "orion_dashboard_access": False, "tally_dashboard_access": True}
    NOBODY = {"id": 3, "role": "viewer", "orion_dashboard_access": False, "tally_dashboard_access": False}

    def payload(self, source="orion"):
        metric = fc.public(fc.forecast_series(series(noisy(40, 1000, slope=6, noise=20, seed=31)), label="Revenue"))
        metric.update({"key": "revenue", "label": "Revenue", "means": "Earned."})
        return {"source": source, "ready": True, "metrics": [metric], "default_metric": "revenue"}

    def run_tool(self, user, args, builder="app.dashboard.forecasting.build_forecast"):
        from app.ai.tools import core, forecast as tool

        self.assertIn("get_forecast", core.REGISTRY)
        with mock.patch(builder, return_value=self.payload()):
            return tool.get_forecast(core.ToolContext(user=user), args)

    def test_it_is_offered_only_to_people_who_may_see_a_dashboard_and_only_reads(self):
        from app.ai.tools import core

        offered = lambda who: {s["name"] for s in core.specs_for(who)}  # noqa: E731
        self.assertIn("get_forecast", offered(self.ORION))
        self.assertIn("get_forecast", offered(self.TALLY))
        self.assertNotIn("get_forecast", offered(self.NOBODY))
        self.assertEqual(core.REGISTRY["get_forecast"].kind, "read")
        self.assertFalse(core.REGISTRY["get_forecast"].confirm)

    def test_the_answer_carries_the_range_and_the_confidence(self):
        out = self.run_tool(self.ORION, {})
        self.assertEqual(out.data["figure"], "Revenue")
        self.assertEqual([h["period"] for h in out.data["horizons"]], ["Next month", "Next 3 months", "Next 6 months", "Next 12 months", "Next 3 years"])
        for h in out.data["horizons"]:
            self.assertLess(h["likely_low"], h["expected"])
            self.assertGreater(h["likely_high"], h["expected"])
        self.assertIn(out.data["confidence"], ("high", "medium", "low", "very_low"))
        self.assertTrue(out.data["why"])

    def test_each_source_checks_its_own_permission(self):
        from app.ai.tools.core import ToolError

        with self.assertRaises(ToolError):
            self.run_tool(self.ORION, {"source": "tally"}, builder="app.tally_forecast.build_tally_forecast")
        with self.assertRaises(ToolError):
            self.run_tool(self.TALLY, {"source": "orion"})
        self.assertTrue(self.run_tool(self.TALLY, {}, builder="app.tally_forecast.build_tally_forecast").data)

    def test_an_unknown_figure_is_refused_with_the_choices(self):
        from app.ai.tools.core import ToolError

        with self.assertRaisesRegex(ToolError, "revenue"):
            self.run_tool(self.ORION, {"metric": "profit"})


@unittest.skipUnless(os.environ.get("ORION_DASHBOARD_DB_TESTS") == "1", "set ORION_DASHBOARD_DB_TESTS=1 to run these against the development database")
class AgainstTheWarehouses(unittest.TestCase):
    """Both forecasts, built from the real warehouses: every figure present, the filters honoured, and the whole thing small and quick."""

    def check(self, payload, expect):
        self.assertTrue(payload["ready"])
        self.assertEqual([m["key"] for m in payload["metrics"]], expect)
        for metric in payload["metrics"]:
            self.assertTrue(metric["available"], metric["key"])
            self.assertEqual(len(metric["forecast"]), 36)
            self.assertEqual([h["months"] for h in metric["horizons"]], [1, 3, 6, 12, 36])
            self.assertNotIn("sigma", str(metric))

    def test_orion(self):
        from app.dashboard.forecasting import build_forecast

        started = time.monotonic()
        payload = build_forecast({})
        self.assertLess(time.monotonic() - started, 5)
        self.check(payload, ["revenue", "billed", "collected", "cost", "margin"])
        one = payload["options"]["clients"][0]["id"]
        narrowed = build_forecast({"client": one, "fy": "2025", "from": "2025-04-01"})  # a period is ignored: a forecast learns from everything
        self.assertEqual(narrowed["filters"], {"client": one})
        revenue = next(m for m in payload["metrics"] if m["key"] == "revenue")
        revenue_one = next(m for m in narrowed["metrics"] if m["key"] == "revenue")
        self.assertLessEqual(revenue_one["horizons"][3]["expected"], revenue["horizons"][3]["expected"] + 1)

    def test_tally(self):
        from app.tally_forecast import build_tally_forecast

        payload = build_tally_forecast({})
        if not payload["ready"]:
            self.skipTest("the Tally warehouse is not loaded")
        self.check(payload, ["billed", "revenue", "gst", "invoices", "credit_notes"])
        self.assertEqual(build_tally_forecast({"fy": "2025", "month": "2025-06"})["filters"], {})


if __name__ == "__main__":
    unittest.main()
