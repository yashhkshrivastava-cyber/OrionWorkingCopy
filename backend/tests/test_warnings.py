"""Two warnings that never block: an expense that looks like one already entered, and a bank balance that is below, or heading below, the minimum a person set.

The rules are checked without a database; with ORION_DB_TESTS=1 the same rules run against the development database inside one transaction that is always rolled
back, so nobody's own records are touched."""

import os
import sys
import unittest
from contextlib import contextmanager
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from app import bank, entities, entity_service  # noqa: E402
from app.ai import insights  # noqa: E402
from app.dependencies import get_current_user  # noqa: E402
from app.main import app  # noqa: E402
from app.routers import entities_router  # noqa: E402

TODAY = date.today()
RUN = os.environ.get("ORION_DB_TESTS") == "1"


class WhatLooksLikeAnotherExpense(unittest.TestCase):
    def test_only_an_expense_is_checked_and_only_with_an_amount_and_a_day(self):
        self.assertEqual(entities.find_possible_duplicates("Client", {"transaction_amount": 5, "transaction_date": TODAY}), [])
        with mock.patch.object(entities, "db_cursor", side_effect=AssertionError("nothing to compare, so the database is not asked")):
            for cleaned in ({}, {"transaction_date": TODAY}, {"transaction_amount": 5}, {"transaction_amount": 0, "transaction_date": TODAY}, {"transaction_amount": "x", "transaction_date": TODAY}):
                with self.subTest(cleaned=cleaned):
                    self.assertEqual(entities.find_possible_duplicates("Expense Transaction", cleaned), [])

    def test_a_match_is_said_in_words(self):
        note = entities.duplicate_note(
            {"expense_code": "EXT-0003", "transaction_date": date(2026, 10, 12), "amount": Decimal("5000"), "paid": True, "expense_type_name": "Fuel", "case_name": "Acme Plant", "transaction_description": "Diesel"}
        )
        self.assertEqual(note, "EXT-0003 on 12 Oct 2026, ₹5,000.00 (paid): Fuel · Acme Plant · Diesel")
        self.assertEqual(entities.duplicate_note({"expense_code": "EXT-1", "transaction_date": date(2026, 1, 2), "amount": Decimal("10")}), "EXT-1 on 02 Jan 2026, ₹10.00")

    def test_the_form_asks_and_a_kind_of_record_that_does_not_check_answers_nothing(self):
        self.assertTrue(entities.ENTITIES["Expense Transaction"].get("duplicate_check"))
        self.assertFalse(entities.ENTITIES["Client"].get("duplicate_check"))
        self.assertEqual(entity_service.possible_duplicates("Client", {"client_name": "x"}), [])

    def test_the_route_needs_permission_to_change_operational_data_and_returns_the_matches(self):
        app.dependency_overrides.clear()
        self.addCleanup(app.dependency_overrides.clear)
        url = "/api/entities/Expense%20Transaction/duplicate-check"
        body = {"data": {"transaction_amount": 5, "transaction_date": TODAY.isoformat()}}
        self.assertIn(TestClient(app).post(url, json=body).status_code, (401, 403))
        app.dependency_overrides[get_current_user] = lambda: {"id": 5, "role": "viewer", "ods_access": True, "ods_write": False}
        self.assertEqual(TestClient(app).post(url, json=body).status_code, 403)
        app.dependency_overrides[get_current_user] = lambda: {"id": 5, "role": "editor", "ods_access": True, "ods_write": True}
        found = [{"expense_code": "EXT-1", "note": "EXT-1 on 01 Oct 2026, ₹5.00"}]
        with mock.patch.object(entity_service, "possible_duplicates", return_value=found):
            answer = TestClient(app).post(url, json=body)
        self.assertEqual(answer.status_code, 200)
        self.assertEqual(answer.json()["matches"][0]["expense_code"], "EXT-1")

    def test_an_upload_names_the_rows_that_look_like_another_and_leaves_the_same_day_to_the_merge(self):
        def row(line, day, amount=100, **more):
            return {"__row": line, "transaction_date": day, "transaction_amount": amount, "expense_type_code": "ET-1", "case_code": "CS-1", **more}

        rows = [row(2, TODAY), row(3, TODAY - timedelta(days=3)), row(4, TODAY - timedelta(days=30)), row(5, TODAY, amount=200), row(6, TODAY, __code="EXT-9")]
        with mock.patch.object(entities_router, "find_possible_duplicates", return_value=[]) as lookup:
            found = entities_router._upload_warnings("Expense Transaction", rows)
        self.assertEqual([f["row"] for f in found], [3])  # row 3 is within a week of row 2; the others are not
        self.assertIn("row 2", found[0]["message"])
        self.assertTrue(all(call.kwargs.get("other_days_only") for call in lookup.call_args_list))  # an expense already recorded on the same day is a merge, not a surprise
        self.assertEqual(lookup.call_count, 4)  # the row that names its record is a change, so it is not checked
        self.assertEqual(entities_router._upload_warnings("Client", rows), [])


ACCOUNT_A = {"account_id": 1, "account_name": "Current account", "low_balance_floor": Decimal("50000")}
ACCOUNT_B = {"account_id": 2, "account_name": "Cash", "low_balance_floor": None}


class WhenTheBalanceIsLow(unittest.TestCase):
    def alerts(self, accounts, balances, lowest=None, forecast_balance=None):
        @contextmanager
        def cursor(commit=False):
            yield mock.Mock()

        ahead = {"configured": True, "balance": forecast_balance, "lowest": {"balance": lowest, "week_start": TODAY + timedelta(days=7)}} if lowest is not None else {"configured": False}
        with mock.patch.object(bank, "db_cursor", cursor), mock.patch.object(bank, "_accounts", return_value=accounts), mock.patch.object(
            bank, "_balance", side_effect=lambda cur, a: balances[a["account_id"]]
        ), mock.patch.object(bank, "forecast", return_value=ahead) as forecast:
            found = bank.alerts()
        return found, forecast

    def test_with_no_minimum_there_is_nothing_to_say(self):
        found, forecast = self.alerts([{**ACCOUNT_A, "low_balance_floor": None}, ACCOUNT_B], {1: Decimal(10), 2: Decimal(10)}, lowest=Decimal(-5))
        self.assertEqual(found, [])
        forecast.assert_not_called()

    def test_an_account_below_its_minimum_is_critical_and_says_how_much(self):
        found, _ = self.alerts([ACCOUNT_A, ACCOUNT_B], {1: Decimal("49999.99"), 2: Decimal("1000")})
        self.assertEqual([(f["key"], f["level"]) for f in found], [("below:1", "critical")])
        self.assertIn("₹49,999.99", found[0]["detail"])
        self.assertIn("₹50,000.00", found[0]["detail"])

    def test_an_account_at_its_minimum_is_not_below_it(self):
        found, _ = self.alerts([ACCOUNT_A], {1: Decimal("50000")}, lowest=Decimal("50000"), forecast_balance=Decimal("50000"))
        self.assertEqual(found, [])

    def test_a_balance_expected_to_fall_below_within_two_weeks_is_a_warning(self):
        found, forecast = self.alerts([ACCOUNT_A, ACCOUNT_B], {1: Decimal("90000"), 2: Decimal("1000")}, lowest=Decimal("20000"), forecast_balance=Decimal("91000"))
        self.assertEqual([(f["key"], f["level"]) for f in found], [("projected", "warning")])
        self.assertEqual(found[0]["floor"], Decimal("50000"))
        self.assertIn("only what Orion already knows", found[0]["detail"])
        forecast.assert_called_once_with(include_overdue=False, weeks=2)  # two weeks, and overdue money is left out

    def test_a_balance_that_stays_above_says_nothing(self):
        found, _ = self.alerts([ACCOUNT_A], {1: Decimal("90000")}, lowest=Decimal("60000"), forecast_balance=Decimal("90000"))
        self.assertEqual(found, [])

    def test_an_account_already_below_is_not_also_reported_as_expected_to_fall(self):
        found, _ = self.alerts([ACCOUNT_A], {1: Decimal("1000")}, lowest=Decimal("-500"), forecast_balance=Decimal("1000"))
        self.assertEqual([f["key"] for f in found], ["below:1"])

    def test_the_minimum_is_checked_when_saving_an_account(self):
        with mock.patch.object(bank, "db_cursor", side_effect=AssertionError("refused before the database was touched")):
            for floor in ("abc", "1e400", "NaN"):
                with self.subTest(floor=floor), self.assertRaises(bank.BankError):
                    bank.save_account({"account_name": "A", "opening_balance": "0", "opening_date": TODAY.isoformat(), "low_balance_floor": floor}, 1)

    def test_the_copilot_is_told_and_the_route_is_for_people_with_bank_access(self):
        alert = {"key": "below:1", "level": "critical", "title": "Current account is below its minimum balance", "detail": "It holds ₹1.00 now; the minimum is ₹2.00."}
        with mock.patch.object(bank, "alerts", return_value=[alert]):
            items = insights._bank({"id": 1})
        self.assertEqual([(i["id"], i["severity"], i["area"], i["link"]) for i in items], [("bank:below:1", "critical", "Bank", "/bank")])
        app.dependency_overrides.clear()
        self.addCleanup(app.dependency_overrides.clear)
        self.assertIn(TestClient(app).get("/api/bank/alerts").status_code, (401, 403))
        app.dependency_overrides[get_current_user] = lambda: {"id": 5, "role": "admin", "bank_access": False, "bank_write": False}
        self.assertEqual(TestClient(app).get("/api/bank/alerts").status_code, 403)
        app.dependency_overrides[get_current_user] = lambda: {"id": 5, "role": "viewer", "bank_access": True, "bank_write": False}
        with mock.patch.object(bank, "alerts", return_value=[]):
            self.assertEqual(TestClient(app).get("/api/bank/alerts").json(), {"alerts": []})


@unittest.skipUnless(RUN, "set ORION_DB_TESTS=1 to run these against the development database")
class AgainstTheRealDatabase(unittest.TestCase):
    """Run in one transaction that is rolled back: nothing stays, whatever the database holds."""

    def setUp(self):
        from app.database import get_connection

        self.conn = get_connection()
        self.cur = self.conn.cursor()
        cur = self.cur

        @contextmanager
        def one_transaction(commit=False):
            yield cur

        for module in (entities, bank):
            patcher = mock.patch.object(module, "db_cursor", one_transaction)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(self.close)

    def close(self):
        self.conn.rollback()
        self.conn.close()

    def expense(self, code, day, amount, status="Committed", type_code=None, case_code=None):
        self.cur.execute(
            "INSERT INTO orion_ods.expense_transaction (expense_code, transaction_date, transaction_amount, tax, gst, amount_after_tax_gst, transaction_status, expense_type_code, case_code) "
            "VALUES (%s, %s, %s, 0, 0, %s, %s, %s, %s)",
            (code, day, amount, amount, status, type_code, case_code),
        )

    def test_same_type_case_and_amount_within_a_week_is_found(self):
        self.expense("ZZ-DUP-1", TODAY, "777.77")
        self.expense("ZZ-DUP-2", TODAY - timedelta(days=3), "777.77")
        self.expense("ZZ-DUP-3", TODAY - timedelta(days=30), "777.77")  # a month apart: a regular expense, not a duplicate
        self.expense("ZZ-DUP-4", TODAY, "777.78")  # another amount
        self.expense("ZZ-DUP-5", TODAY, "777.77", status="Cancelled")  # withdrawn: nothing to duplicate
        probe = {"transaction_amount": 777.77, "transaction_date": TODAY - timedelta(days=1)}
        self.assertEqual([m["expense_code"] for m in entities.find_possible_duplicates("Expense Transaction", probe)], ["ZZ-DUP-1", "ZZ-DUP-2"])
        self.assertEqual(entities.find_possible_duplicates("Expense Transaction", {**probe, "transaction_date": TODAY + timedelta(days=20)}), [])
        self.assertEqual(entities.find_possible_duplicates("Expense Transaction", {**probe, "transaction_amount": 5}), [])
        same_day = {**probe, "transaction_date": TODAY}
        self.assertEqual([m["expense_code"] for m in entities.find_possible_duplicates("Expense Transaction", same_day, other_days_only=True)], ["ZZ-DUP-2"])
        # the amount is the one with tax and GST, to the paisa
        self.assertEqual(len(entities.find_possible_duplicates("Expense Transaction", {"amount_after_tax_gst": "777.77", "transaction_amount": 1, "transaction_date": TODAY})), 2)

    def test_the_answer_comes_with_a_sentence_and_saving_is_not_refused(self):
        self.expense("ZZ-DUP-9", TODAY, "888.88")
        found = entity_service.possible_duplicates("Expense Transaction", {"transaction_amount": 888.88, "tax": 0, "gst": 0, "transaction_date": TODAY.isoformat()})
        self.assertEqual([m["expense_code"] for m in found], ["ZZ-DUP-9"])
        self.assertIn("ZZ-DUP-9", found[0]["note"])

    def test_a_minimum_set_above_the_balance_raises_the_alert(self):
        self.cur.execute("INSERT INTO orion_ods.bank_account (account_name, opening_balance, opening_date) VALUES ('ZZ warning check', 5000, %s) RETURNING account_id", (TODAY - timedelta(days=10),))
        mine = self.cur.fetchone()[0]
        self.cur.execute("UPDATE orion_ods.bank_account SET low_balance_floor = NULL WHERE account_id <> %s", (mine,))  # only this account has a minimum
        self.cur.execute("UPDATE orion_ods.bank_account SET low_balance_floor = 6000 WHERE account_id = %s", (mine,))
        self.assertIn(f"below:{mine}", [a["key"] for a in bank.alerts()])
        self.cur.execute("UPDATE orion_ods.bank_account SET low_balance_floor = 4000 WHERE account_id = %s", (mine,))
        self.assertNotIn(f"below:{mine}", [a["key"] for a in bank.alerts()])
        self.cur.execute("UPDATE orion_ods.bank_account SET low_balance_floor = NULL")
        self.assertEqual(bank.alerts(), [])
        # saving an account keeps a minimum that was not sent, changes one that was, and clears one sent empty
        base = {"account_name": "ZZ warning check", "opening_balance": "5000", "opening_date": (TODAY - timedelta(days=10)).isoformat()}
        self.assertEqual(Decimal(str(bank.save_account({**base, "low_balance_floor": "2500"}, 1, account_id=mine)["low_balance_floor"])), Decimal("2500"))
        self.assertEqual(Decimal(str(bank.save_account(base, 1, account_id=mine)["low_balance_floor"])), Decimal("2500"))
        self.assertIsNone(bank.save_account({**base, "low_balance_floor": ""}, 1, account_id=mine)["low_balance_floor"])


if __name__ == "__main__":
    unittest.main()
