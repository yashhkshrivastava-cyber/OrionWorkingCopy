"""The hover card on a bill number: what it holds, who may ask for it, and that it never invents a figure."""

import sys
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from app import billing  # noqa: E402
from app.dependencies import get_current_user  # noqa: E402
from app.main import app  # noqa: E402


def a_bill(**changes):
    """A bill as get_bill returns it (numbers are floats, dates are text)."""
    bill = {
        "bill_code": "BILL-0012", "bill_number": "2026-27/202", "status": "Issued", "bill_date": "2026-07-31", "service_month": "2026-07-01",
        "ref_no": "WO/12", "ref_date": None, "location": "Bhind", "service_description": "Guards for July",
        "client_code": "CL-1", "client_name": "Civil Surgeon", "legacy_client_ledger": None, "case_code": "CS-1", "case_name": "Bhind hospital",
        "party_name": "Civil Surgeon Bhind", "party_gstin": "23ABCDE1234F1Z5", "party_state": "Madhya Pradesh",
        "lines": [{"particulars": f"Post {n}", "qty": n, "rate": 100.0, "amount": 100.0 * n} for n in range(1, 7)],
        "extra_charges": [{"label": "Uniform", "kind": "amount", "value": 250.0, "amount": 250.0}],
        "lines_total": 2100.0, "epf_amount": 273.0, "esic_amount": 68.25, "service_amount": 210.0, "taxable_total": 2901.25,
        "cgst_amount": 261.11, "sgst_amount": 261.11, "round_off": 0.53, "grand_total": 3424.0, "sub_total": 2441.25,
        "gst_paid": False, "version_no": 2, "version_reason": "Rate corrected", "version_by_name": "Asha", "version_timestamp": "2026-08-02T10:00:00+05:30",
        "created_by": 3, "created_timestamp": "2026-08-01T09:00:00+05:30", "cancelled_reason": None, "cancelled_timestamp": None,
        "revenue": {"received": 0.0, "remaining": 3424.0, "entries": [{"status": "Prospective", "received_date": None, "amount": 3424.0}]},
    }
    bill.update(changes)
    return bill


TODAY = date(2026, 9, 10)


class WhatTheCardHolds(unittest.TestCase):
    def test_it_names_the_bill_the_people_and_the_work(self):
        card = billing.card_from(a_bill(), "Meena", TODAY)
        self.assertEqual((card["id"], card["bill_number"], card["status"]), ("BILL-0012", "2026-27/202", "Issued"))
        self.assertEqual((card["client_name"], card["case_name"], card["party_gstin"], card["location"]), ("Civil Surgeon", "Bhind hospital", "23ABCDE1234F1Z5", "Bhind"))
        self.assertEqual((card["ref_no"], card["service_description"], card["service_month"]), ("WO/12", "Guards for July", "2026-07-01"))

    def test_the_figures_are_the_bills_own_not_recalculated(self):
        card = billing.card_from(a_bill(grand_total=1.0), None, TODAY)
        self.assertEqual(card["figures"]["grand_total"], 1.0)  # a stored figure is shown as stored
        self.assertEqual([c["label"] for c in card["figures"]["extra_charges"]], ["Uniform"])
        for key in ("lines_total", "epf_amount", "esic_amount", "service_amount", "taxable_total", "cgst_amount", "sgst_amount", "round_off"):
            self.assertIn(key, card["figures"])

    def test_a_long_bill_lists_a_few_lines_and_says_how_many_there_are(self):
        card = billing.card_from(a_bill(), None, TODAY)
        self.assertEqual((card["line_count"], len(card["lines"])), (6, billing.CARD_LINES))
        self.assertEqual(card["lines"][0]["particulars"], "Post 1")

    def test_the_gst_position_is_on_the_card_with_what_was_paid_and_when(self):
        gst = {
            "status": "Part paid", "total": {"due": 522.22, "paid": 261.11, "remaining": 261.11},
            "cgst": {"due": 261.11, "paid": 261.11, "remaining": 0.0}, "sgst": {"due": 261.11, "paid": 0.0, "remaining": 261.11},
            "payments": [{"paid_date": "2026-10-05", "reversed": False}, {"paid_date": "2026-09-01", "reversed": False}],
        }
        card = billing.card_from(a_bill(gst=gst), None, TODAY)
        self.assertEqual(card["gst"]["status"], "Part paid")
        self.assertEqual((card["gst"]["cgst"]["remaining"], card["gst"]["sgst"]["remaining"]), (0.0, 261.11))
        self.assertEqual(card["gst"]["last_paid_date"], "2026-10-05")
        self.assertFalse(billing.card_from(a_bill(), None, TODAY)["gst_paid"])

    def test_a_reversed_payment_is_not_the_last_payment(self):
        gst = {"status": "Part paid", "payments": [{"paid_date": "2026-10-05", "reversed": True}, {"paid_date": "2026-09-01", "reversed": False}]}
        self.assertEqual(billing.card_from(a_bill(gst=gst), None, TODAY)["gst"]["last_paid_date"], "2026-09-01")

    def test_who_made_it_and_who_last_changed_it(self):
        card = billing.card_from(a_bill(), "Meena", TODAY)
        self.assertEqual((card["created_by_name"], card["version_by_name"], card["version_no"], card["version_reason"]), ("Meena", "Asha", 2, "Rate corrected"))

    def test_a_bill_raised_before_cases_shows_its_ledger_as_the_client(self):
        card = billing.card_from(a_bill(client_name=None, legacy_client_ledger="Tally ledger X"), None, TODAY)
        self.assertEqual(card["client_name"], "Tally ledger X")

    def test_a_missing_value_is_empty_not_a_crash(self):
        bare = a_bill(lines=None, extra_charges=None, revenue=None, ref_no=None, location=None, service_description=None)
        card = billing.card_from(bare, None, TODAY)
        self.assertEqual((card["line_count"], card["lines"], card["figures"]["extra_charges"]), (0, [], []))
        self.assertEqual(card["payments"], {"received": 0.0, "credited": 0.0, "remaining": 0.0, "count": 0, "recent": []})


class TheMoney(unittest.TestCase):
    def test_unpaid(self):
        card = billing.card_from(a_bill(), None, TODAY)
        self.assertEqual((card["payment_status"], card["age_days"], card["payments"]["remaining"]), ("Unpaid", 41, 3424.0))

    def test_part_paid_lists_what_came_in_newest_first(self):
        revenue = {
            "received": 1500.0,
            "remaining": 1924.0,
            "entries": [
                {"status": "Committed", "received_date": "2026-08-05", "amount": 500.0},
                {"status": "Committed", "received_date": "2026-09-01", "amount": 1000.0},
                {"status": "Prospective", "received_date": None, "amount": 1924.0},
            ],
        }
        card = billing.card_from(a_bill(revenue=revenue), None, TODAY)
        self.assertEqual(card["payment_status"], "Part paid")
        self.assertEqual(card["payments"]["count"], 2)
        self.assertEqual([p["received_date"] for p in card["payments"]["recent"]], ["2026-09-01", "2026-08-05"])

    def test_paid_has_no_age(self):
        revenue = {"received": 3424.0, "remaining": 0.0, "entries": [{"status": "Committed", "received_date": "2026-08-20", "amount": 3424.0}]}
        card = billing.card_from(a_bill(revenue=revenue), None, TODAY)
        self.assertEqual((card["payment_status"], card["age_days"]), ("Paid", None))

    def test_a_cancelled_bill_is_owed_nothing(self):
        card = billing.card_from(a_bill(status="Cancelled", cancelled_reason="Raised twice", revenue={"received": 0.0, "remaining": 0.0, "entries": []}), None, TODAY)
        self.assertEqual((card["payment_status"], card["age_days"], card["cancelled_reason"]), ("Cancelled", None, "Raised twice"))

    def test_a_bill_dated_in_the_future_is_not_negative_days_old(self):
        card = billing.card_from(a_bill(bill_date="2026-12-31"), None, TODAY)
        self.assertEqual(card["age_days"], 0)


class FindingTheBill(unittest.TestCase):
    def test_by_code_it_asks_for_that_bill(self):
        with mock.patch.object(billing, "get_bill", return_value=None) as get:
            self.assertIsNone(billing.bill_card(code="BILL-9"))
        get.assert_called_once_with("BILL-9")

    def test_nothing_given_finds_nothing_and_asks_nothing(self):
        with mock.patch.object(billing, "get_bill") as get, mock.patch.object(billing, "db_cursor") as cursor:
            self.assertIsNone(billing.bill_card())
            self.assertIsNone(billing.bill_card(code="  ", number=" "))
        get.assert_not_called()
        cursor.assert_not_called()

    def test_by_number_it_looks_the_code_up_first(self):
        cursor = mock.MagicMock()
        cursor.__enter__.return_value.fetchone.return_value = ("BILL-0012",)
        with mock.patch.object(billing, "db_cursor", return_value=cursor), mock.patch.object(billing, "get_bill", return_value=a_bill(created_by=None)) as get:
            card = billing.bill_card(number="2026-27/202")
        get.assert_called_once_with("BILL-0012")
        self.assertEqual(card["bill_number"], "2026-27/202")

    def test_an_unknown_number_is_none(self):
        cursor = mock.MagicMock()
        cursor.__enter__.return_value.fetchone.return_value = None
        with mock.patch.object(billing, "db_cursor", return_value=cursor), mock.patch.object(billing, "get_bill") as get:
            self.assertIsNone(billing.bill_card(number="1999-00/1"))
        get.assert_not_called()


class TheRoute(unittest.TestCase):
    def tearDown(self):
        app.dependency_overrides.clear()

    def signed_in(self, **flags):
        app.dependency_overrides[get_current_user] = lambda: {"id": 1, "role": "viewer", "billing_access": False, **flags}

    def test_it_needs_a_sign_in(self):
        self.assertEqual(TestClient(app).get("/api/billing/card?number=2026-27/202").status_code, 401)

    def test_it_needs_billing_access(self):
        self.signed_in()
        with mock.patch.object(billing, "bill_card") as card:
            response = TestClient(app).get("/api/billing/card?number=2026-27/202")
        self.assertEqual(response.status_code, 403)
        card.assert_not_called()

    def test_with_access_it_answers_for_a_number_or_a_code(self):
        self.signed_in(billing_access=True)
        with mock.patch.object(billing, "bill_card", return_value={"id": "BILL-1", "bill_number": "2026-27/1"}) as card:
            client = TestClient(app)
            by_number = client.get("/api/billing/card", params={"number": "2026-27/1"})
            by_code = client.get("/api/billing/card", params={"code": "BILL-1"})
        self.assertEqual((by_number.status_code, by_code.status_code), (200, 200))
        self.assertEqual(card.call_args_list, [mock.call(code=None, number="2026-27/1"), mock.call(code="BILL-1", number=None)])

    def test_no_such_bill_is_a_404_and_no_question_is_a_400(self):
        self.signed_in(billing_access=True)
        with mock.patch.object(billing, "bill_card", return_value=None):
            client = TestClient(app)
            self.assertEqual(client.get("/api/billing/card", params={"number": "x"}).status_code, 404)
            self.assertEqual(client.get("/api/billing/card").status_code, 400)


if __name__ == "__main__":
    unittest.main()
