"""Payables: an expense is owed until it is paid, in instalments, from an account. What may be recorded, who may do it, how an expense ages, and (against
the development database, with ORION_DB_TESTS=1, inside one transaction that is always rolled back, so nobody's own records are touched) the whole life of
an expense: owed, part paid, paid, reversed, and what the bank book and the forecast make of each step."""

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

from app import bank, db_utils, entities, entity_service, excel_import, payables  # noqa: E402
from app.dependencies import get_current_user  # noqa: E402
from app.main import app  # noqa: E402
from app.routers import payables_router  # noqa: E402

TODAY = date.today()
RUN = os.environ.get("ORION_DB_TESTS") == "1"
ROOT = Path(__file__).resolve().parents[2]


def pay(**changes):
    data = {"confirm": True, "seen_paid": "0", "amount": "100", "paid_date": TODAY, "reference": "UTR1"}
    data.update(changes)
    return data


class WhatMayBeRecorded(unittest.TestCase):
    def refused(self, **changes):
        with mock.patch.object(payables, "db_cursor", side_effect=AssertionError("refused before the database was touched")):
            with self.assertRaises(payables.PayableError) as caught:
                payables.record_payment("EXT-0001", 1, **pay(**changes))
        return str(caught.exception)

    def test_it_needs_the_confirmation_and_what_the_person_saw(self):
        self.assertIn("Confirm", self.refused(confirm=False))
        self.assertIn("Reload", self.refused(seen_paid=None))

    def test_the_amount_is_positive_a_number_and_not_absurd(self):
        for amount in ("0", "-5", "abc", "", None, "1e400", "NaN", "99999999999999"):
            with self.subTest(amount=amount):
                self.refused(amount=amount)

    def test_the_day_cannot_be_in_the_future_or_missing(self):
        self.assertIn("future", self.refused(paid_date=TODAY + timedelta(days=1)))
        self.refused(paid_date="not a date")

    def test_a_reversal_needs_the_confirmation_and_a_reason(self):
        with mock.patch.object(payables, "db_cursor", side_effect=AssertionError("refused before the database was touched")):
            for kwargs in ({"confirm": False, "reason": "wrong amount"}, {"confirm": True, "reason": ""}, {"confirm": True, "reason": "no"}):
                with self.subTest(**kwargs), self.assertRaises(payables.PayableError):
                    payables.reverse_payment(1, 1, **kwargs)


class HowAnExpenseAges(unittest.TestCase):
    def test_paid_part_paid_unpaid(self):
        total = Decimal("1000.00")
        self.assertEqual(payables.payment_status(total, Decimal("0")), "Unpaid")
        self.assertEqual(payables.payment_status(total, Decimal("400")), "Part paid")
        self.assertEqual(payables.payment_status(total, Decimal("1000")), "Paid")

    def test_the_ageing_counts_days_past_the_day_it_was_to_be_paid(self):
        for late, bucket in ((-1, "not_due"), (0, "0-30"), (30, "0-30"), (31, "31-60"), (60, "31-60"), (61, "61-90"), (90, "61-90"), (91, "90+"), (900, "90+")):
            with self.subTest(late=late):
                self.assertEqual(payables.bucket_of(late), bucket)
        self.assertEqual(set(payables.BUCKET_LABELS), set(payables.BUCKETS))

    def test_the_total_is_with_tax_and_gst_to_the_paisa(self):
        self.assertEqual(payables._total({"amount_after_tax_gst": Decimal("1180.005"), "transaction_amount": 1000}), Decimal("1180.01"))
        self.assertEqual(payables._total({"amount_after_tax_gst": None, "transaction_amount": 1000}), Decimal("1000.00"))

    def test_the_filters_are_checked(self):
        with mock.patch.object(payables, "db_cursor", side_effect=AssertionError("refused before the database was touched")):
            for kwargs in ({"status": "sideways"}, {"bucket": "tomorrow"}, {"page": "x"}):
                with self.subTest(**kwargs), self.assertRaises(payables.PayableError):
                    payables.list_payables(**kwargs)


class WhatTheFormsMayDo(unittest.TestCase):
    def test_an_expense_with_payments_stays_committed_and_is_never_less_than_was_paid(self):
        with mock.patch.object(entities, "_paid_on_expense", return_value=Decimal("400")):
            self.assertIn("stays Committed", entities.invalid_reason("Expense Transaction", "EXT-1", {"transaction_status": "Cancelled"}, {"transaction_status": "Committed"}))
            self.assertIn("cannot be less", entities.invalid_reason("Expense Transaction", "EXT-1", {"amount_after_tax_gst": 399.99}, {"transaction_status": "Committed"}))
            self.assertIsNone(entities.invalid_reason("Expense Transaction", "EXT-1", {"amount_after_tax_gst": 400}, {"transaction_status": "Committed"}))
            self.assertIsNone(entities.invalid_reason("Expense Transaction", "EXT-1", {"transaction_description": "renamed"}, {"transaction_status": "Committed", "amount_after_tax_gst": 900}))
        with mock.patch.object(entities, "_paid_on_expense", return_value=Decimal("0")):
            self.assertIsNone(entities.invalid_reason("Expense Transaction", "EXT-1", {"transaction_status": "Cancelled"}, {"transaction_status": "Committed"}))
        self.assertIsNone(entities.invalid_reason("Expense Transaction", None, {"transaction_status": "Committed", "amount_after_tax_gst": 5}))  # a new one has no payments

    def test_the_pay_by_day_is_a_field_of_the_expense_form_and_of_the_warehouse(self):
        self.assertIn("due_date", entities.ENTITIES["Expense Transaction"]["form_fields"])
        self.assertTrue(entities.ENTITIES["Expense Transaction"]["form_fields"]["due_date"].get("optional"))
        self.assertIn("due_date", (ROOT / ".cursor" / "db" / "dw_schema.sql").read_text(encoding="utf-8"))


class PaidWhenItIsEntered(unittest.TestCase):
    """An expense that has already been paid says so when it is added, and is paid in the same save."""

    def test_the_status_has_plainer_words_that_are_stored_as_before(self):
        entity = entities.ENTITIES["Expense Transaction"]
        config = entity["form_fields"]["transaction_status"]
        self.assertEqual(config["options"], ["Committed", "Prospective", "Cancelled"])
        self.assertEqual(config["option_labels"]["Committed"], "Incurred (a real cost)")
        self.assertEqual(entity_service.validate(entity, {"transaction_status": "Incurred"})["transaction_status"], "Committed")
        self.assertEqual(entity_service.validate(entity, {"transaction_status": "planned"})["transaction_status"], "Prospective")
        self.assertEqual(excel_import._resolve_value("transaction_status", config, "Incurred", {}), "Committed")
        self.assertEqual(excel_import._resolve_value("transaction_status", config, "Planned", {}), "Prospective")

    def test_the_questions_are_asked_only_when_adding_and_are_not_columns_of_the_expense(self):
        entity = entities.ENTITIES["Expense Transaction"]
        extra = entities.create_fields(entity)
        self.assertEqual(set(extra), {"paid_on", "paid_from", "payment_reference"})
        self.assertFalse(set(extra) & set(entity["form_fields"]))
        self.assertEqual(entities.create_fields(entities.ENTITIES["Client"]), {})
        self.assertTrue(set(extra) <= set(entities.with_create_fields(entity)["form_fields"]))
        cleaned = entity_service.validate(entities.with_create_fields(entity), {"transaction_amount": 5, "paid_on": TODAY.isoformat(), "payment_reference": "R1"})
        paid = entity_service.split_payment(entity, cleaned)
        self.assertEqual(set(paid), {"paid_on", "payment_reference"})
        self.assertNotIn("paid_on", cleaned)  # only the record's own columns are written

    def test_a_payment_that_cannot_be_made_is_refused_in_plain_words(self):
        refuse = entity_service.check_payment_on_entry
        self.assertFalse(refuse({"transaction_status": "Prospective"}, {}))
        self.assertFalse(refuse({"transaction_status": "Prospective"}, {"paid_on": None, "paid_from": ""}))  # nothing was said about paying
        with self.assertRaises(entity_service.EntityError) as day:
            refuse({"transaction_status": "Committed", "transaction_amount": 5}, {"paid_from": "17"})
        self.assertIn("Paid On", day.exception.message)
        with self.assertRaises(entity_service.EntityError) as planned:
            refuse({"transaction_status": "Prospective", "transaction_amount": 5}, {"paid_on": TODAY})
        self.assertIn("Incurred", planned.exception.message)
        with self.assertRaises(entity_service.EntityError):
            refuse({"transaction_status": "Committed", "transaction_amount": 0}, {"paid_on": TODAY})
        self.assertTrue(refuse({"transaction_status": "Committed", "amount_after_tax_gst": 118.0}, {"paid_on": TODAY}))

    def test_a_day_in_the_future_is_refused(self):
        with self.assertRaises(payables.PayableError):
            payables.pay_on_entry(object(), "EXT-1", 1, paid_date=TODAY + timedelta(days=1))


class WhoMayMarkItPaid(unittest.TestCase):
    BODY = {"data": {"transaction_amount": 5, "transaction_status": "Committed", "paid_on": TODAY.isoformat()}}
    URL = "/api/entities/Expense%20Transaction/records"

    def setUp(self):
        app.dependency_overrides.clear()
        self.addCleanup(app.dependency_overrides.clear)

    def test_the_extra_questions_are_offered_only_to_a_person_who_may_change_the_bank(self):
        for write, expected in ((True, True), (False, False)):
            app.dependency_overrides[get_current_user] = lambda write=write: {"id": 5, "role": "editor", "ods_access": True, "ods_write": True, "bank_access": write, "bank_write": write}
            found = TestClient(app).get("/api/entities").json()["entities"]
            expense = next(e for e in found if e["name"] == "Expense Transaction")
            self.assertEqual(bool(expense["create_fields"]), expected, write)
            self.assertEqual(next(e for e in found if e["name"] == "Client")["create_fields"], {})

    def test_marking_it_paid_needs_permission_to_change_the_bank_and_a_key_that_reaches_the_work(self):
        key = {"Idempotency-Key": "a-valid-key-12345"}
        app.dependency_overrides[get_current_user] = lambda: {"id": 5, "role": "editor", "ods_access": True, "ods_write": True, "bank_access": False, "bank_write": False}
        with mock.patch.object(entity_service, "create", return_value="EXT-9") as create:
            denied = TestClient(app).post(self.URL, json=self.BODY, headers=key)
            self.assertEqual(denied.status_code, 403)
            create.assert_not_called()
            app.dependency_overrides[get_current_user] = lambda: {"id": 5, "role": "editor", "ods_access": True, "ods_write": True, "bank_access": True, "bank_write": True}
            bad = TestClient(app).post(self.URL, json=self.BODY, headers={"Idempotency-Key": "x"})
            self.assertEqual(bad.status_code, 400)
            good = TestClient(app).post(self.URL, json=self.BODY, headers=key)
            self.assertEqual(good.status_code, 200)
            self.assertIsNotNone(create.call_args.args[3])  # the key reached the code that saves and pays
            plain = TestClient(app).post(self.URL, json={"data": {"transaction_amount": 5}})
            self.assertEqual(plain.status_code, 200)
            self.assertIsNone(create.call_args.args[3])  # an expense that is not paid needs no key


class WhoMayDoWhat(unittest.TestCase):
    def setUp(self):
        app.dependency_overrides.clear()
        self.addCleanup(app.dependency_overrides.clear)

    def routes(self):
        return [(method, "/api" + route.path) for route in payables_router.router.routes for method in sorted(route.methods - {"HEAD", "OPTIONS"})]

    def call(self, method, path, **kwargs):
        return TestClient(app).request(method, path.replace("{expense_code}", "EXT-1").replace("{payment_id}", "1"), **kwargs)

    def test_there_are_routes_to_test(self):
        self.assertGreaterEqual(len(self.routes()), 4)

    def test_nobody_signed_out_gets_anything(self):
        for method, path in self.routes():
            self.assertIn(self.call(method, path).status_code, (401, 403), f"{method} {path}")

    def test_a_person_without_bank_access_gets_nothing(self):
        app.dependency_overrides[get_current_user] = lambda: {"id": 5, "role": "admin", "bank_access": False, "bank_write": False}
        for method, path in self.routes():
            self.assertEqual(self.call(method, path).status_code, 403, f"{method} {path}")

    def test_a_person_who_can_only_look_cannot_pay_or_reverse(self):
        app.dependency_overrides[get_current_user] = lambda: {"id": 5, "role": "viewer", "bank_access": True, "bank_write": False}
        for method, path in self.routes():
            if method != "GET":
                self.assertEqual(self.call(method, path).status_code, 403, f"{method} {path}")

    def test_a_payment_takes_an_idempotency_key_and_it_reaches_the_code_that_does_the_work(self):
        app.dependency_overrides[get_current_user] = lambda: {"id": 5, "role": "viewer", "bank_access": True, "bank_write": True}
        body = {"amount": 5, "paid_date": TODAY.isoformat(), "seen_paid": 0, "confirm": True}
        with mock.patch.object(payables, "record_payment") as record:
            bad = TestClient(app).post("/api/payables/EXT-1/payments", json=body, headers={"Idempotency-Key": "x"})
            self.assertEqual(bad.status_code, 400)
            record.assert_not_called()
            record.return_value = {"payment_id": 9}
            good = TestClient(app).post("/api/payables/EXT-1/payments", json=body, headers={"Idempotency-Key": "a-valid-key-12345"})
        self.assertEqual(good.status_code, 200)
        self.assertIsNotNone(record.call_args.kwargs["idem"])

    def test_a_conflict_is_a_409_and_a_mistake_a_400(self):
        app.dependency_overrides[get_current_user] = lambda: {"id": 5, "role": "viewer", "bank_access": True, "bank_write": True}
        client = TestClient(app)
        body = {"reason": "wrong amount", "confirm": True}
        with mock.patch.object(payables, "reverse_payment", side_effect=payables.PayableConflict("no")):
            self.assertEqual(client.post("/api/payables/payments/1/reverse", json=body).status_code, 409)
        with mock.patch.object(payables, "reverse_payment", side_effect=payables.PayableError("no")):
            self.assertEqual(client.post("/api/payables/payments/1/reverse", json=body).status_code, 400)


@unittest.skipUnless(RUN, "set ORION_DB_TESTS=1 to run these against the development database")
class AgainstTheRealDatabase(unittest.TestCase):
    """The whole life of one expense, in one transaction that is rolled back: nothing stays, whatever accounts and expenses the database holds."""

    CODE = "ZZ-EXT-PAY-1"

    def setUp(self):
        from app.database import get_connection

        self.conn = get_connection()
        self.cur = self.conn.cursor()
        cur = self.cur

        @contextmanager
        def one_transaction(commit=False):
            yield cur

        for module in (payables, bank, entity_service, db_utils):
            patcher = mock.patch.object(module, "db_cursor", one_transaction)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(self.close)
        cur.execute(
            "INSERT INTO orion_ods.expense_transaction (expense_code, transaction_date, due_date, transaction_amount, tax, gst, amount_after_tax_gst, transaction_status) "
            "VALUES (%s, %s, %s, 1000, 0, 0, 1000, 'Committed')",
            (self.CODE, TODAY - timedelta(days=45), TODAY - timedelta(days=40)),
        )

    def close(self):
        self.conn.rollback()
        self.conn.close()

    def movements(self):
        self.cur.execute(
            "SELECT m.source_ref, m.amount, m.direction, m.move_date FROM orion_ods.bank_movement m "
            "JOIN orion_ods.expense_payment p ON p.payment_id::text = m.source_ref WHERE m.source = 'expense' AND p.expense_code = %s ORDER BY m.source_ref",
            (self.CODE,),
        )
        return self.cur.fetchall()

    def expected(self):
        self.cur.execute("SELECT amount, due_date FROM orion_ods.bank_expected WHERE source = 'expense' AND source_ref = %s", (self.CODE,))
        return self.cur.fetchall()

    def sql_refused(self, sql, args, constraint):
        from psycopg2 import errors

        self.cur.execute("SAVEPOINT attempt")
        with self.assertRaises(errors.CheckViolation) as caught:
            self.cur.execute(sql, args)
        self.assertEqual(caught.exception.diag.constraint_name, constraint)
        self.cur.execute("ROLLBACK TO SAVEPOINT attempt")

    def test_owed_part_paid_paid_and_taken_back(self):
        found = payables.get_expense(self.CODE)
        self.assertEqual((found["payment_status"], found["left"], found["bucket"]), ("Unpaid", Decimal("1000.00"), "31-60"))
        listed = payables.list_payables(limit=200)
        self.assertIn(self.CODE, [i["expense_code"] for i in listed["items"]])
        self.assertEqual(self.movements(), [])  # incurred, not paid: the bank has not moved
        self.assertEqual([(Decimal(a), d) for a, d in self.expected()], [(Decimal("1000.00"), TODAY - timedelta(days=40))])  # but it is due, on its due day

        # a payment that is not confirmed, or made against a stale view, or too large, writes nothing
        with self.assertRaises(payables.PayableError):
            payables.record_payment(self.CODE, 1, **pay(confirm=False))
        with self.assertRaises(payables.PayableConflict):
            payables.record_payment(self.CODE, 1, **pay(seen_paid="50"))
        with self.assertRaises(payables.PayableError) as over:
            payables.record_payment(self.CODE, 1, **pay(amount="1000.01"))
        self.assertIn("1,000.00", str(over.exception))
        self.assertEqual(self.movements(), [])

        first = payables.record_payment(self.CODE, 1, **pay(amount="400"))
        self.assertEqual((first["payment_status"], first["left"]), ("Part paid", "600.00"))
        self.assertEqual([(Decimal(a), d, w) for _, a, d, w in self.movements()], [(Decimal("400.00"), "out", TODAY)])
        self.assertEqual([Decimal(a) for a, _ in self.expected()], [Decimal("600.00")])  # only what is still owed is still to come

        second = payables.record_payment(self.CODE, 1, **pay(amount="600", seen_paid="400", reference="UTR2"))
        self.assertEqual(second["payment_status"], "Paid")
        self.assertEqual(len(self.movements()), 2)
        self.assertEqual(self.expected(), [])
        with self.assertRaises(payables.PayableError):
            payables.record_payment(self.CODE, 1, **pay(amount="1", seen_paid="1000"))

        # a paid expense stays committed, and is never worth less than was paid on it (the database says so, whatever wrote it)
        self.sql_refused("UPDATE orion_ods.expense_transaction SET transaction_status = 'Cancelled' WHERE expense_code = %s", (self.CODE,), "expense_paid_stays_committed")
        self.sql_refused("UPDATE orion_ods.expense_transaction SET amount_after_tax_gst = 999 WHERE expense_code = %s", (self.CODE,), "expense_amount_covers_payments")
        self.cur.execute("UPDATE orion_ods.expense_transaction SET transaction_description = 'a note' WHERE expense_code = %s", (self.CODE,))  # anything else is fine

        payables.reverse_payment(first["payment_id"], 1, confirm=True, reason="paid from the wrong account")
        again = payables.get_expense(self.CODE)
        self.assertEqual((again["payment_status"], again["left"]), ("Part paid", Decimal("400.00")))
        self.assertEqual(len(self.movements()), 1)  # the money is back in the account it left
        self.assertEqual([Decimal(a) for a, _ in self.expected()], [Decimal("400.00")])
        self.assertEqual(len(again["payments"]), 2)  # the reversed payment is kept, marked
        self.assertEqual([p["reversed"] for p in again["payments"]], [True, False])
        with self.assertRaises(payables.PayableConflict):
            payables.reverse_payment(first["payment_id"], 1, confirm=True, reason="again")

    def test_a_payment_is_taken_from_the_account_named_and_not_before_its_opening(self):
        self.cur.execute("SELECT MIN(account_id), MIN(opening_date) FROM orion_ods.bank_account")
        account, opening = self.cur.fetchone()
        if account is None:
            self.skipTest("no bank account to pay from")
        done = payables.record_payment(self.CODE, 1, **pay(amount="100", account_id=account))
        self.assertEqual(done["account_id"], account)
        with self.assertRaises(payables.PayableError) as early:
            payables.record_payment(self.CODE, 1, **pay(amount="100", seen_paid="100", paid_date=opening - timedelta(days=1)))
        self.assertIn("opening", str(early.exception))
        with self.assertRaises(payables.PayableError):
            payables.record_payment(self.CODE, 1, **pay(amount="100", seen_paid="100", account_id=987654))

    def test_the_same_request_twice_pays_once(self):
        from app.idempotency import Idempotency

        def attempt():
            return payables.record_payment(self.CODE, 1, **pay(amount="250"), idem=Idempotency(1, "zz-payables-key-0001", "expense.payment", "fp"))

        first = attempt()
        second = attempt()
        self.assertEqual(first["payment_id"], second["payment_id"])
        self.cur.execute("SELECT COUNT(*) FROM orion_ods.expense_payment WHERE expense_code = %s", (self.CODE,))
        self.assertEqual(self.cur.fetchone()[0], 1)

    def test_a_statement_line_matches_the_payment_and_a_reversal_breaks_the_match(self):
        self.cur.execute("SELECT account_id FROM orion_ods.bank_account WHERE account_kind = 'bank' ORDER BY account_id LIMIT 1")
        found = self.cur.fetchone()
        if found is None:
            self.skipTest("no bank account to reconcile")
        account = found[0]
        done = payables.record_payment(self.CODE, 1, **pay(amount="321.50", account_id=account, reference="UTR-ZZ-9"))
        self.cur.execute(
            "INSERT INTO orion_ods.bank_statement_import (account_id, filename, file_sha256) VALUES (%s, 'zz.csv', 'zz-sha') RETURNING import_id", (account,)
        )
        import_id = self.cur.fetchone()[0]
        self.cur.execute(
            "INSERT INTO orion_ods.bank_statement_line (import_id, account_id, line_date, description, reference, direction, amount, fingerprint) "
            "VALUES (%s, %s, %s, 'NEFT UTR-ZZ-9', 'UTR-ZZ-9', 'out', 321.50, 'zz-fp-1') RETURNING line_id",
            (import_id, account, TODAY),
        )
        line_id = self.cur.fetchone()[0]
        bank.match_line(line_id, [{"source": "expense", "source_ref": str(done["payment_id"])}], 1)
        self.assertEqual([i for i in bank.exceptions(account) if i["line_id"] == line_id], [])
        payables.reverse_payment(done["payment_id"], 1, confirm=True, reason="paid from the wrong account")
        broken = [i for i in bank.exceptions(account) if i["line_id"] == line_id]
        self.assertEqual(len(broken), 1)
        self.assertIn("expense payment was reversed", broken[0]["reason"])

    def test_an_expense_entered_as_paid_is_saved_and_paid_in_one_go(self):
        self.cur.execute("SELECT account_id FROM orion_ods.bank_account ORDER BY account_id")
        accounts = [r[0] for r in self.cur.fetchall()]
        if not accounts:
            self.skipTest("no bank account to pay from")
        data = {"transaction_date": TODAY.isoformat(), "transaction_amount": 700, "tax": 0, "gst": 0, "transaction_status": "Incurred"}
        # not paid: only the expense, and it is owed
        owed = entity_service.create("Expense Transaction", data, 1)
        self.assertEqual(payables.get_expense(owed)["payment_status"], "Unpaid")
        # paid: the expense and its full payment, from the account named, on the day given
        code = entity_service.create("Expense Transaction", {**data, "paid_on": TODAY.isoformat(), "paid_from": str(accounts[0]), "payment_reference": "CASH-1"}, 1)
        found = payables.get_expense(code)
        self.assertEqual((found["payment_status"], found["left"]), ("Paid", Decimal("0.00")))
        self.assertEqual([(p["amount"], p["account_id"], p["reference"]) for p in found["payments"]], [(Decimal("700.00"), accounts[0], "CASH-1")])
        # with several accounts the account must be named, and a planned expense cannot be paid
        if len(accounts) > 1:
            with self.assertRaises(entity_service.EntityError) as which:
                entity_service.create("Expense Transaction", {**data, "paid_on": TODAY.isoformat()}, 1)
            self.assertIn("account", which.exception.message)
        with self.assertRaises(entity_service.EntityError):
            entity_service.create("Expense Transaction", {**data, "transaction_status": "Planned", "paid_on": TODAY.isoformat(), "paid_from": str(accounts[0])}, 1)
        # a day before the account opened is fine for an expense entered as paid (it is already inside the opening balance)
        self.cur.execute("SELECT opening_date FROM orion_ods.bank_account WHERE account_id = %s", (accounts[0],))
        early = self.cur.fetchone()[0] - timedelta(days=30)
        old = entity_service.create("Expense Transaction", {**data, "paid_on": early.isoformat(), "paid_from": str(accounts[0])}, 1)
        self.assertEqual(payables.get_expense(old)["payment_status"], "Paid")

    def test_the_same_save_twice_pays_once(self):
        from app.idempotency import Idempotency

        self.cur.execute("SELECT MIN(account_id) FROM orion_ods.bank_account")
        account = self.cur.fetchone()[0]
        if account is None:
            self.skipTest("no bank account to pay from")
        data = {"transaction_date": TODAY.isoformat(), "transaction_amount": 321, "tax": 0, "gst": 0, "transaction_status": "Committed", "paid_on": TODAY.isoformat(), "paid_from": str(account)}
        first = entity_service.create("Expense Transaction", data, 1, Idempotency(1, "zz-entry-key-00001", "expense.create_paid", "fp"))
        second = entity_service.create("Expense Transaction", data, 1, Idempotency(1, "zz-entry-key-00001", "expense.create_paid", "fp"))
        self.assertEqual(first, second)
        self.cur.execute("SELECT COUNT(*) FROM orion_ods.expense_payment WHERE expense_code = %s", (first,))
        self.assertEqual(self.cur.fetchone()[0], 1)

    def test_an_excel_row_can_say_it_was_paid_but_only_a_new_expense(self):
        self.cur.execute("SELECT MIN(account_id) FROM orion_ods.bank_account")
        account = self.cur.fetchone()[0]
        if account is None:
            self.skipTest("no bank account to pay from")
        seen = []

        def after(cur, code, extra, row):
            seen.append(code)
            entity_service.pay_new_record(cur, "Expense Transaction", code, extra, 1)

        row = {"transaction_date": TODAY, "transaction_amount": 450, "tax": 0, "gst": 0, "amount_after_tax_gst": 450, "transaction_status": "Committed",
               "__row": 2, "__extra": {"paid_on": TODAY, "paid_from": str(account), "payment_reference": "XL-1"}}
        inserted, updated = db_utils.upsert_many("orion_ods.expense_transaction", [row], [], "expense_code", user_id=1, after_insert=after)
        self.assertEqual((inserted, updated, len(seen)), (1, 0, 1))
        self.assertEqual(payables.get_expense(seen[0])["payment_status"], "Paid")
        about_one_that_exists = {"__code": seen[0], "__row": 3, "transaction_description": "x", "__extra": {"paid_on": TODAY}}
        with self.assertRaises(db_utils.MergeError) as refused:
            db_utils.upsert_many("orion_ods.expense_transaction", [about_one_that_exists], [], "expense_code", user_id=1, after_insert=after)
        self.assertIn("new expense", str(refused.exception))
        self.assertEqual(refused.exception.row, 3)

    def test_only_an_incurred_expense_can_be_paid(self):
        self.cur.execute("UPDATE orion_ods.expense_transaction SET transaction_status = 'Prospective' WHERE expense_code = %s", (self.CODE,))
        with self.assertRaises(payables.PayableError) as caught:
            payables.record_payment(self.CODE, 1, **pay())
        self.assertIn("Committed", str(caught.exception))
        self.assertEqual([r for r in self.expected() if r], [(Decimal(1000), TODAY - timedelta(days=40))])  # a Prospective expense is still expected


if __name__ == "__main__":
    unittest.main()
