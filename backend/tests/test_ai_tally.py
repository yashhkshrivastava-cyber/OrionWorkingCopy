"""The Copilot's Tally tools, checked without a database or a model.

The Tally dashboard's own functions are replaced with fixed figures, so these tests pin down what the tools do with them:
who may use them, how a client named in words is matched to the books, how a change against the earlier period is worked
out, what the rules recognise as a Tally question, and that the application's own answers say which books they came from.
"""

import sys
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app import auth  # noqa: E402
from app.ai import insights, periods, prompt, safety  # noqa: E402
from app.ai.routing import compose, intents  # noqa: E402
from app.ai.tools import core, tally  # noqa: E402

TODAY = date(2026, 10, 10)


def user(role="viewer", **flags):
    base = {flag: False for flag in auth.ACCESS_FLAGS}
    base.update({"id": 7, "username": "t", "display_name": "Tester", "role": role, "ai_access": True})
    base.update(flags)
    return base


ADMIN = user("admin", **{flag: True for flag in auth.ACCESS_FLAGS})
NOBODY = user("viewer")
ORION_ONLY = user("viewer", orion_dashboard_access=True)
TALLY_ONLY = user("viewer", tally_dashboard_access=True)

TALLY_TOOLS = {
    "get_tally_summary", "get_tally_metric", "compare_tally_periods", "get_tally_top_clients",
    "get_tally_income_mix", "get_tally_debtors", "get_tally_credit_notes", "get_tally_books_position",
}


def totals(**over):
    base = {
        "billed": 1_180_000.0, "revenue": 1_000_000.0, "gst": 180_000.0, "invoices": 20.0, "clients": 4.0,
        "sales_billed": 1_240_000.0, "sales_count": 18.0, "cn_billed": -60_000.0, "cn_count": 2.0, "dn_billed": 0.0, "dn_count": 0.0,
        "manpower": 700_000.0, "vehicle": 200_000.0, "service": 100_000.0, "epf": 0.0, "esic": 0.0, "other_income": 0.0,
    }
    base.update(over)
    return base


class FakeCursor:
    """Answers the name look-ups the tools make; the figures come from the patched dashboard functions."""

    def __init__(self, names=None):
        self.names = names or {}
        self.sql = ""

    def execute(self, sql, params=None):
        self.sql = sql

    def fetchall(self):
        for needle, rows in self.names.items():
            if needle in self.sql:
                return [(r,) for r in rows]
        return []


def run(name, args, cursor=None, who=ADMIN, previous=None, **patches):
    """Runs one tool with the dashboard's functions replaced. ``previous`` is what the earlier period billed."""
    ctx = core.ToolContext(user=who, today=TODAY)
    ctx._cursor = cursor or FakeCursor()
    current = patches.pop("totals", totals())

    calls = []

    def aggregates(_cur, filters):
        # The tools ask for the selection first and the earlier period second.
        calls.append(filters)
        return dict(previous if (previous is not None and len(calls) > 1) else current)

    income = {"totals": {"manpower": 700_000.0, "vehicle": 200_000.0, "service": 100_000.0, "epf": 0.0, "esic": 0.0, "other_income": 0.0},
              "groups": [{"code": "manpower", "label": "Manpower", "value": 700_000.0}, {"code": "vehicle", "label": "Vehicle rent", "value": 200_000.0},
                         {"code": "service", "label": "SG service", "value": 100_000.0}],
              "rows": [{"code": "Manpower Supply", "group": "Manpower", "revenue": 700_000.0, "share": 70.0}]}
    base = {
        "_warehouse_ready": lambda cur: True,
        "_aggregates": aggregates,
        "_income_from_lines": lambda cur, f: income,
        "_data_span": lambda cur: {"min": "2023-04-01", "max": "2026-09-30"},
        "_monthly": lambda cur, f: [{"code": "2026-08", "label": "Aug 26", "billed": 400_000.0, "revenue": 340_000.0, "gst": 60_000.0, "invoices": 7.0},
                                    {"code": "2026-09", "label": "Sep 26", "billed": 780_000.0, "revenue": 660_000.0, "gst": 120_000.0, "invoices": 13.0}],
        "_top_clients": lambda cur, f, limit=12: [
            {"code": "Narmada Cement Works", "label": "Narmada Cement", "revenue": 500_000.0, "billed": 590_000.0},
            {"code": "Malwa Cooperative Bank", "label": "Malwa Bank", "revenue": 300_000.0, "billed": 354_000.0},
            {"code": "City Centre Mall", "label": "City Centre", "revenue": 200_000.0, "billed": 236_000.0}][:limit],
        "_debtor_snapshot": lambda cur, f: {"balance": -250_000.0, "count": 9.0},
        "_debtor_rows": lambda cur, f, limit=200: [{"code": "Civil Hospital", "label": "Civil Hospital", "client": "Civil Hospital", "closing": -150_000.0, "revenue": 90_000.0, "invoices": 3.0}],
        "_notes_by_client": lambda cur, f, limit=12: [{"code": "Malwa Cooperative Bank", "label": "Malwa Bank", "value": 40_000.0}],
        "_note_documents": lambda cur, f, limit=200: [{"code": "Malwa Cooperative Bank", "date": "2026-09-12", "voucher": "CN-4", "type": "Credit note", "client": "Malwa Bank",
                                                      "company": "PS", "billed": -40_000.0, "revenue": -34_000.0, "gst": -6_000.0, "reference": "", "narration": "rate difference"}],
        "_books_position": lambda cur, f: {"gst_payable": -80_000.0, "loans": -500_000.0, "creditors": -120_000.0, "statutory": -30_000.0, "cash": 210_000.0,
                                           "profit_loss": 1_000_000.0, "loan_ledgers": 2, "creditor_ledgers": 5, "balances": [], "rows": []},
        "build_tally_dashboard": lambda f: {"insights": [{"tone": "warning", "title": "Sep 26 is only partly billed", "detail": "Some documents may follow."}]},
    }
    base.update(patches)
    stack = [mock.patch.object(tally.td, key, value) for key, value in base.items()]
    stack.append(mock.patch("app.ai.tools.core.store.audit"))
    for item in stack:
        item.start()
    try:
        return core.execute(ctx, name, args)
    finally:
        for item in stack:
            item.stop()



class Access(unittest.TestCase):
    def offered(self, who):
        return {s["name"] for s in core.specs_for(who)}

    def test_every_tally_tool_is_registered_and_only_reads(self):
        self.assertTrue(TALLY_TOOLS <= set(core.REGISTRY))
        for name in TALLY_TOOLS:
            with self.subTest(tool=name):
                self.assertEqual(core.REGISTRY[name].kind, "read")
                self.assertFalse(core.REGISTRY[name].confirm)

    def test_only_a_person_with_the_tally_dashboard_is_offered_them(self):
        self.assertFalse(TALLY_TOOLS & self.offered(NOBODY))
        self.assertFalse(TALLY_TOOLS & self.offered(ORION_ONLY))
        self.assertTrue(TALLY_TOOLS <= self.offered(TALLY_ONLY))
        self.assertTrue(TALLY_TOOLS <= self.offered(ADMIN))

    def test_the_orion_dashboard_alone_does_not_open_the_orion_tools_to_a_tally_only_person(self):
        self.assertNotIn("get_business_summary", self.offered(TALLY_ONLY))

    def test_a_tally_tool_is_refused_for_someone_without_access_even_if_asked_for(self):
        outcome = run("get_tally_summary", {}, who=ORION_ONLY)
        self.assertTrue(outcome.refused)
        self.assertFalse(outcome.ok)


class Figures(unittest.TestCase):
    def test_the_summary_compares_with_the_period_before_and_says_which_books_it_read(self):
        outcome = run("get_tally_summary", {"period": "last_month"}, previous=totals(billed=1_000_000.0, revenue=900_000.0))
        self.assertTrue(outcome.ok, outcome.summary)
        data = outcome.data
        self.assertEqual(data["source"], "Tally books")
        billed = next(h for h in data["headline"] if h["metric"] == "billed")
        self.assertEqual(billed["value"], 1_180_000.0)
        self.assertEqual(billed["previous_value"], 1_000_000.0)
        self.assertEqual(billed["change_pct"], 18.0)
        self.assertEqual(billed["direction"], "up")
        self.assertTrue(billed["good"])
        self.assertEqual(data["top_clients"][0]["client"], "Narmada Cement Works")
        self.assertEqual(data["top_clients"][0]["share_pct"], 50.0)
        self.assertEqual(data["sundry_debtors_now"]["closing_balance"], -250_000.0)
        self.assertEqual(data["dashboard_findings"][0]["title"], "Sep 26 is only partly billed")
        self.assertTrue(data["blocks"])

    def test_a_rise_in_credit_notes_is_bad_news(self):
        outcome = run("get_tally_metric", {"metric": "credit_notes", "period": "last_month"}, previous=totals(cn_billed=-20_000.0))
        self.assertEqual(outcome.data["value"], 60_000.0)  # credit notes are reported as a size, not a negative
        self.assertEqual(outcome.data["direction"], "up")
        self.assertFalse(outcome.data["good"])

    def test_credit_notes_as_a_share_of_sales_is_worked_out_from_the_totals(self):
        outcome = run("get_tally_metric", {"metric": "credit_note_rate", "period": "last_month"})
        self.assertAlmostEqual(outcome.data["value"], 4.84, places=2)
        self.assertEqual(outcome.data["unit"], "pct")

    def test_a_figure_with_a_monthly_chart_returns_the_months(self):
        outcome = run("get_tally_metric", {"metric": "billed", "period": "last_12_months"})
        self.assertEqual([m["month"] for m in outcome.data["monthly"]], ["2026-08", "2026-09"])

    def test_nothing_billed_is_said_rather_than_a_zero_being_passed_off_as_a_finding(self):
        outcome = run("get_tally_metric", {"metric": "billed", "period": "last_month"}, totals=totals(invoices=0.0, billed=0.0))
        self.assertTrue(any("Nothing was billed" in note for note in outcome.data["notes"]))

    def test_no_comparison_is_made_for_all_time(self):
        outcome = run("get_tally_metric", {"metric": "billed", "period": "all_time"})
        self.assertNotIn("previous_value", outcome.data)

    def test_the_warehouse_not_being_loaded_is_a_plain_message(self):
        outcome = run("get_tally_summary", {}, _warehouse_ready=lambda cur: False)
        self.assertFalse(outcome.ok)
        self.assertIn("has not been loaded", outcome.summary)

    def test_two_periods_side_by_side(self):
        outcome = run("compare_tally_periods", {"period_a": {"period": "last_quarter"}, "metrics": ["billed", "invoices"]}, previous=totals(billed=1_000_000.0, invoices=25.0))
        rows = {r["metric"]: r for r in outcome.data["comparison"]}
        self.assertEqual(rows["billed"]["a_display"], "₹11.8 L")
        self.assertEqual(rows["invoices"]["direction"], "down")
        self.assertEqual(outcome.data["period_b"]["label"], periods.previous(periods.resolve("last_quarter", None, None, TODAY)).label)

    def test_clients_are_ranked_with_their_share_and_the_top_three(self):
        outcome = run("get_tally_top_clients", {"period": "last_12_months", "limit": 3})
        ranked = outcome.data["clients"]
        self.assertEqual([c["client"] for c in ranked], ["Narmada Cement Works", "Malwa Cooperative Bank", "City Centre Mall"])
        self.assertEqual(ranked[0]["share_pct"], round(500_000.0 / 1_000_000.0 * 100, 2))
        self.assertEqual(outcome.data["top_three_share_pct"], round(sum(c["share_pct"] for c in ranked), 2))

    def test_the_income_mix_has_shares(self):
        outcome = run("get_tally_income_mix", {"period": "last_12_months"})
        self.assertEqual(outcome.data["by_line"][0], {"line": "Manpower", "amount": 700000.0, "display": "₹7.0 L", "share_pct": 70.0})

    def test_debtors_are_a_book_balance_and_say_so(self):
        outcome = run("get_tally_debtors", {})
        self.assertEqual(outcome.data["total_closing_balance"], -250_000.0)
        self.assertIn("not aged receivables", outcome.data["note"])
        self.assertIn("get_receivables", core.REGISTRY["get_tally_debtors"].description)

    def test_books_balances_are_listed_not_added_together(self):
        outcome = run("get_tally_books_position", {})
        names = [b["balance"] for b in outcome.data["balances"]]
        self.assertIn("GST payable", names)
        self.assertNotIn("Total", names)
        self.assertIn("not added together", outcome.data["note"])

    def test_credit_notes_report(self):
        outcome = run("get_tally_credit_notes", {"period": "last_12_months"})
        self.assertEqual(outcome.data["credit_note_count"], 2)
        self.assertEqual(outcome.data["most_credited_clients"][0]["client"], "Malwa Cooperative Bank")


class Names(unittest.TestCase):
    def test_a_part_of_a_client_name_finds_the_client(self):
        cursor = FakeCursor({"party_ledger_name": ["Narmada Cement Works"]})
        outcome = run("get_tally_metric", {"metric": "billed", "period": "last_month", "filters": {"client": "narmada"}}, cursor=cursor)
        self.assertTrue(outcome.ok, outcome.summary)
        self.assertEqual(outcome.data["filters_applied"], {"client": "Narmada Cement Works"})
        self.assertTrue(any("Narmada Cement Works" in n for n in outcome.data["filter_notes"]))

    def test_a_name_that_matches_several_clients_is_asked_about(self):
        cursor = FakeCursor({"party_ledger_name": ["Narmada Cement Works", "Narmada Textiles"]})
        outcome = run("get_tally_metric", {"metric": "billed", "filters": {"client": "narmada"}}, cursor=cursor)
        self.assertFalse(outcome.ok)
        self.assertIn("several", outcome.summary)

    def test_a_name_that_matches_nothing_is_said_not_ignored(self):
        outcome = run("get_tally_metric", {"metric": "billed", "filters": {"client": "Nobody Ltd"}}, cursor=FakeCursor())
        self.assertFalse(outcome.ok)
        self.assertIn("no client called", outcome.summary)

    def test_an_income_line_is_known_by_its_name(self):
        outcome = run("get_tally_metric", {"metric": "billed", "filters": {"income_line": "vehicle rent"}})
        self.assertEqual(outcome.data["filters_applied"], {"income_line": "vehicle"})

    def test_a_filter_the_tool_does_not_have_is_refused(self):
        outcome = run("get_tally_metric", {"metric": "billed", "filters": {"state": "Gujarat"}})
        self.assertFalse(outcome.ok)


class Rules(unittest.TestCase):
    def plan(self, text, page=None):
        return intents.plan(text, page or {}, TODAY)

    def tool_of(self, text, page=None):
        found = self.plan(text, page)
        return found.calls[0][0] if found and found.calls else None

    def test_common_tally_questions_are_answered_by_the_tally_tools(self):
        cases = {
            "How is billing in Tally?": "get_tally_summary",
            "Who are our top 5 clients in Tally?": "get_tally_top_clients",
            "how many credit notes this year": "get_tally_credit_notes",
            "what do the sundry debtors show": "get_tally_debtors",
            "what is our gst payable": "get_tally_books_position",
            "manpower versus vehicle rent in tally": "get_tally_income_mix",
            "How much manpower income last quarter in tally": "get_tally_metric",
            "compare tally billing this quarter with last quarter": "compare_tally_periods",
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(self.tool_of(text), expected)

    def test_a_named_client_and_period_are_passed_on(self):
        found = self.plan("how much did we bill Narmada Cement Works last year in tally")
        self.assertEqual(found.calls[0][1], {"metric": "billed", "period": "last_year", "filters": {"client": "Narmada Cement Works"}})

    def test_a_question_about_the_books_is_never_answered_from_orions_records(self):
        self.assertIsNone(self.plan("why did tally billing fall"))
        self.assertIsNone(self.plan("export tally invoices"))
        self.assertNotEqual(self.tool_of("remind me to check tally tomorrow"), "get_tally_summary")

    def test_orion_questions_still_go_to_orion(self):
        self.assertEqual(self.tool_of("How are we doing this month?"), "get_business_summary")
        self.assertEqual(self.tool_of("What is revenue last month?"), "get_metric")
        self.assertEqual(self.tool_of("who owes us the most?"), "get_top_items")

    def test_on_a_tally_page_a_plain_question_is_about_tally_and_uses_the_filters_on_screen(self):
        page = {"area": "dashboard_tally", "view": "overview", "filters": {"fy": "2026", "client": "Acme"}}
        found = self.plan("Summarize what I'm looking at", page)
        self.assertEqual(found.calls[0][0], "get_tally_summary")
        self.assertEqual(found.calls[0][1], {"from": "2026-04-01", "to": "2027-03-31", "filters": {"client": "Acme"}})
        self.assertEqual(self.tool_of("top clients", page), "get_tally_top_clients")

    def test_on_a_tally_page_a_question_only_orion_can_answer_still_goes_to_orion(self):
        page = {"area": "dashboard_tally", "view": "overview"}
        self.assertEqual(self.tool_of("who owes us the most?", page), "get_top_items")
        self.assertEqual(self.tool_of("what is our payroll last month?", page), "get_metric")


class Answers(unittest.TestCase):
    def answer(self, name, args):
        outcome = run(name, args, previous=totals(billed=1_000_000.0))
        self.assertTrue(outcome.ok, outcome.summary)
        return compose.answer([outcome])

    def test_every_tally_tool_has_a_written_answer_that_names_the_books(self):
        cases = [
            ("get_tally_summary", {"period": "last_month"}), ("get_tally_metric", {"metric": "billed", "period": "last_month"}),
            ("compare_tally_periods", {"period_a": {"period": "last_quarter"}}), ("get_tally_top_clients", {"period": "last_12_months"}),
            ("get_tally_income_mix", {"period": "last_12_months"}), ("get_tally_debtors", {}), ("get_tally_credit_notes", {"period": "last_12_months"}),
            ("get_tally_books_position", {}),
        ]
        for name, args in cases:
            with self.subTest(tool=name):
                text = self.answer(name, args)
                self.assertIn("Tally", text)
                self.assertNotIn("Done.", text)

    def test_the_summary_quotes_the_tools_figures_and_the_change(self):
        text = self.answer("get_tally_summary", {"period": "last_month"})
        self.assertIn("₹11.8 L", text)
        self.assertIn("+18.0%", text)
        self.assertIn("Narmada Cement Works", text)

    def test_debtors_are_not_passed_off_as_receivables(self):
        self.assertIn("not aged receivables", self.answer("get_tally_debtors", {}))


class Context(unittest.TestCase):
    def test_the_tally_pages_own_filters_are_kept_and_checked(self):
        cleaned = safety.sanitize_context({"path": "/dashboard/tally/billing", "area": "dashboard_tally", "view": "billing",
                                           "filters": {"client": "Acme", "voucher_type": "Sales", "fy": "2026", "state": "Gujarat", "from": "not a date"}})
        self.assertEqual(cleaned["filters"], {"client": "Acme", "voucher_type": "Sales", "fy": "2026"})

    def test_orion_filters_are_still_checked_the_orion_way(self):
        cleaned = safety.sanitize_context({"area": "dashboard", "filters": {"state": "Gujarat", "voucher_type": "Sales"}})
        self.assertEqual(cleaned["filters"], {"state": "Gujarat"})

    def test_the_prompt_tells_the_model_about_both_sources(self):
        text = prompt.system_prompt(TALLY_ONLY, "x", "", TODAY)
        self.assertIn("Tally dashboards: yes", text)
        self.assertIn("Orion dashboards: no", text)
        self.assertIn("two sources of figures", text)

    def test_starter_questions_on_a_tally_page_are_about_tally(self):
        starters = insights.suggestions(TALLY_ONLY, {"area": "dashboard_tally", "view": "clients"})
        self.assertTrue(any("Sundry Debtors" in s for s in starters))
        self.assertFalse([s for s in insights.suggestions(NOBODY, {"area": "dashboard_tally"}) if "Tally" in s])


if __name__ == "__main__":
    unittest.main()
