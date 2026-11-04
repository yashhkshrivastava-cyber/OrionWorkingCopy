"""Finding a bill by its case, its client or the month it is for: what a typed month means, what is asked of the database, and who may ask. No database is needed."""

import inspect
import sys
import unittest
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from fastapi.routing import APIRoute  # noqa: E402

from app import billing  # noqa: E402
from app.routers import billing_router  # noqa: E402


class TypedMonths(unittest.TestCase):
    def test_a_month_in_words_or_numbers_is_understood(self):
        cases = {
            "sep": (9, None), "Sept": (9, None), "september": (9, None), "September 2026": (9, 2026), "sep 26": (9, 2026), "SEP, 2026": (9, 2026),
            "2026-09": (9, 2026), "2026/9": (9, 2026), "09/2026": (9, 2026), "9-2026": (9, 2026), "may": (5, None), "march 2025": (3, 2025), "jan": (1, None),
        }
        for text, expected in cases.items():
            with self.subTest(text):
                self.assertEqual(billing.month_hint(text), expected)

    def test_other_words_are_not_months(self):
        for text in ("", "ma", "mark", "city centre", "2026", "13/2026", "2026-13", "bill 31", "septic", "mallpay", "SEP2026X"):
            with self.subTest(text):
                self.assertIsNone(billing.month_hint(text))


class Cursor:
    def __init__(self):
        self.sql = ""
        self.params = []
        self.description = []

    def execute(self, sql, params=None):
        self.sql = " ".join(sql.split())
        self.params = list(params or [])

    def fetchall(self):
        return []


def run(**kwargs):
    cursor = Cursor()

    @contextmanager
    def opened(commit=False):
        yield cursor

    with mock.patch.object(billing, "db_cursor", opened):
        billing.list_bills(**kwargs)
    return cursor


class WhatIsAsked(unittest.TestCase):
    def test_a_client_a_case_and_a_month_are_exact_conditions_never_text(self):
        cursor = run(client_code="CL-0001", case_code="CS-0002", month="2026-09")
        self.assertIn("b.client_code = %s", cursor.sql)
        self.assertIn("b.case_code = %s", cursor.sql)
        self.assertIn("b.service_month = %s", cursor.sql)
        self.assertEqual(cursor.params[:3], ["CL-0001", "CS-0002", date(2026, 9, 1)])
        self.assertNotIn("CL-0001", cursor.sql)  # a value is a parameter, never put into the SQL text

    def test_with_no_filter_every_year_is_searched(self):
        cursor = run()
        self.assertNotIn("b.fy_start_year = %s", cursor.sql)
        self.assertNotIn("service_month = %s", cursor.sql)

    def test_a_typed_month_also_looks_at_the_month_a_bill_is_for(self):
        cursor = run(search="september 2026")
        self.assertIn("EXTRACT(MONTH FROM b.service_month)", cursor.sql)
        self.assertEqual(cursor.params[6:9], [9, 2026, 2026])
        self.assertEqual(cursor.params[:6], ["%september 2026%"] * 6)  # and the words are still searched in the usual places

    def test_ordinary_words_do_not_bring_in_a_month(self):
        self.assertNotIn("EXTRACT(MONTH", run(search="city centre").sql)

    def test_a_search_covers_the_site_too(self):
        self.assertIn("b.location ILIKE %s", run(search="mall").sql)

    def test_a_month_that_is_not_one_is_refused(self):
        with self.assertRaises(billing.BillError):
            run(month="September")


class TheRoute(unittest.TestCase):
    def test_the_register_takes_the_filters_and_needs_billing_access(self):
        found = {route.path: route for route in billing_router.router.routes if isinstance(route, APIRoute) and "GET" in route.methods}
        route = found["/billing/bills"]
        self.assertTrue(route.dependant.dependencies)
        names = {param.name for param in route.dependant.query_params}
        self.assertTrue({"fy", "q", "client_code", "case_code", "month"} <= names)
        self.assertIn("require_billing", inspect.getsource(billing_router.bills))


if __name__ == "__main__":
    unittest.main()
