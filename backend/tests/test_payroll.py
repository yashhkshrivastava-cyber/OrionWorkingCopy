"""Payroll: a month's salary is paid by one transfer, a pay run. What may be recorded, who may do it, what the forms may do with a paid line, and (against
the development database, with ORION_DB_TESTS=1, inside one transaction that is always rolled back, so nobody's own records are touched) the whole life of a
month: unpaid, paid in runs, reversed, and what the bank book, the forecast and reconciliation make of each step."""

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

from app import bank, entities, entity_service, payroll  # noqa: E402
from app.dependencies import get_current_user  # noqa: E402
from app.main import app  # noqa: E402
from app.routers import payroll_router  # noqa: E402

TODAY = date.today()
RUN = os.environ.get("ORION_DB_TESTS") == "1"
ROOT = Path(__file__).resolve().parents[2]
MONTH = "2099-01"


def run_args(**changes):
    data = {"confirm": True, "month_year": "2026-09", "line_codes": ["ETR-1", "ETR-2"], "seen_count": 2, "seen_total": "300", "paid_date": TODAY, "reference": "NEFT-1"}
    data.update(changes)
    return data


class WhatMayBeRecorded(unittest.TestCase):
    def refused(self, **changes):
        with mock.patch.object(payroll, "db_cursor", side_effect=AssertionError("refused before the database was touched")):
            with self.assertRaises(payroll.PayrollError) as caught:
                payroll.record_run(1, **run_args(**changes))
        return str(caught.exception)

    def test_it_needs_the_confirmation_and_what_the_person_saw(self):
        self.assertIn("Confirm", self.refused(confirm=False))
        self.assertIn("Reload", self.refused(seen_total=None))
        self.assertIn("Reload", self.refused(seen_count=None))

    def test_the_month_the_lines_and_the_day_are_checked(self):
        for month in (None, "", "2026-13", "2026-9", "September"):
            with self.subTest(month=month):
                self.refused(month_year=month)
        for codes in (None, [], "ETR-1", ["ETR-1", "ETR-1"], ["", " "]):
            with self.subTest(codes=codes):
                self.refused(line_codes=codes)
        self.assertIn("future", self.refused(paid_date=TODAY + timedelta(days=1)))
        self.refused(paid_date="not a date")
        self.refused(seen_total="abc")
        self.refused(seen_count="x")

    def test_a_reversal_needs_the_confirmation_and_a_reason(self):
        with mock.patch.object(payroll, "db_cursor", side_effect=AssertionError("refused before the database was touched")):
            for kwargs in ({"confirm": False, "reason": "wrong month"}, {"confirm": True, "reason": ""}, {"confirm": True, "reason": "no"}):
                with self.subTest(**kwargs), self.assertRaises(payroll.PayrollError):
                    payroll.reverse_run(1, 1, **kwargs)


class WhatTheFormsMayDo(unittest.TestCase):
    def test_salary_paid_is_not_typed_in_it_is_set_by_payroll(self):
        entity = entities.ENTITIES["Employee Transaction"]
        config = entity["form_fields"]["salary_paid"]
        self.assertTrue(config["readonly"])
        self.assertIn("Bank > Payroll", config["hint"])
        # the form, the Copilot and the Excel upload never write it: a value sent for it is not used, and the template has no column for it
        cleaned = entity_service.validate(entity, {"employee_code": "EMP-1", "salary_amount": 10, "salary_paid": "Yes"})
        self.assertNotIn("salary_paid", cleaned)
        from app import excel_import

        self.assertNotIn("salary_paid", excel_import.excel_columns(entity))
        # an old line stored as paid before pay runs, with no run to point at, can still be edited
        self.assertIsNone(entities.invalid_reason("Employee Transaction", "ETR-1", {"salary_amount": 5}, {"salary_paid": "Yes", "salary_run_id": None}))

    def test_a_line_in_a_pay_run_is_locked_for_the_forms_and_the_copilot(self):
        self.assertIn("pay run", entities.locked_reason("Employee Transaction", {"salary_paid": "Yes", "salary_run_id": 7}))
        self.assertIsNone(entities.locked_reason("Employee Transaction", {"salary_paid": "No", "salary_run_id": None}))
        self.assertIsNone(entities.locked_reason("Employee Transaction", {"salary_paid": "Yes", "salary_run_id": None}))
        for name in ("salary_paid_needs_run", "salary_line_paid_is_locked", "salary_line_paid_cannot_be_deleted"):
            self.assertIn("Payroll", entity_service.CONSTRAINT_MESSAGES[name])

    def test_the_bank_knows_salary_as_a_source_with_its_own_label(self):
        self.assertIn("payroll", bank.SOURCES)
        self.assertEqual(bank.SOURCE_LABELS["payroll"], "Salary")
        self.assertIn("payroll", bank.SYSTEM_CATEGORIES)
        self.assertIn("reversed", bank._why_it_broke({"gone": True, "source": "payroll", "run_reversed": True}))


class WhoMayDoWhat(unittest.TestCase):
    def setUp(self):
        app.dependency_overrides.clear()
        self.addCleanup(app.dependency_overrides.clear)

    def routes(self):
        return [(method, "/api" + route.path) for route in payroll_router.router.routes for method in sorted(route.methods - {"HEAD", "OPTIONS"})]

    def call(self, method, path, **kwargs):
        return TestClient(app).request(method, path.replace("{month_year}", "2026-09").replace("{run_id}", "1"), **kwargs)

    def test_there_are_routes_to_test(self):
        self.assertGreaterEqual(len(self.routes()), 5)

    def test_nobody_signed_out_gets_anything(self):
        for method, path in self.routes():
            self.assertIn(self.call(method, path).status_code, (401, 403), f"{method} {path}")

    def test_a_person_without_bank_access_gets_nothing(self):
        app.dependency_overrides[get_current_user] = lambda: {"id": 5, "role": "admin", "bank_access": False, "bank_write": False}
        for method, path in self.routes():
            self.assertEqual(self.call(method, path).status_code, 403, f"{method} {path}")

    def test_a_person_who_can_only_look_sees_totals_but_not_who_was_paid_and_cannot_pay(self):
        app.dependency_overrides[get_current_user] = lambda: {"id": 5, "role": "viewer", "bank_access": True, "bank_write": False}
        for method, path in self.routes():
            if method != "GET" or path.endswith("/unpaid"):
                self.assertEqual(self.call(method, path).status_code, 403, f"{method} {path}")

    def test_a_pay_run_takes_an_idempotency_key_and_it_reaches_the_code_that_does_the_work(self):
        app.dependency_overrides[get_current_user] = lambda: {"id": 5, "role": "viewer", "bank_access": True, "bank_write": True}
        body = {"month_year": "2026-09", "line_codes": ["ETR-1"], "seen_count": 1, "seen_total": 100, "paid_date": TODAY.isoformat(), "confirm": True}
        with mock.patch.object(payroll, "record_run") as record:
            bad = TestClient(app).post("/api/payroll/runs", json=body, headers={"Idempotency-Key": "x"})
            self.assertEqual(bad.status_code, 400)
            record.assert_not_called()
            record.return_value = {"run_id": 9}
            good = TestClient(app).post("/api/payroll/runs", json=body, headers={"Idempotency-Key": "a-valid-key-12345"})
        self.assertEqual(good.status_code, 200)
        self.assertIsNotNone(record.call_args.kwargs["idem"])

    def test_a_conflict_is_a_409_and_a_mistake_a_400(self):
        app.dependency_overrides[get_current_user] = lambda: {"id": 5, "role": "viewer", "bank_access": True, "bank_write": True}
        client = TestClient(app)
        body = {"reason": "wrong month", "confirm": True}
        with mock.patch.object(payroll, "reverse_run", side_effect=payroll.PayrollConflict("no")):
            self.assertEqual(client.post("/api/payroll/runs/1/reverse", json=body).status_code, 409)
        with mock.patch.object(payroll, "reverse_run", side_effect=payroll.PayrollError("no")):
            self.assertEqual(client.post("/api/payroll/runs/1/reverse", json=body).status_code, 400)


@unittest.skipUnless(RUN, "set ORION_DB_TESTS=1 to run these against the development database")
class AgainstTheRealDatabase(unittest.TestCase):
    """The whole life of one month of salary, in one transaction that is rolled back: nothing stays, whatever accounts and salary the database holds."""

    def setUp(self):
        from app.database import get_connection

        self.conn = get_connection()
        self.cur = self.conn.cursor()
        cur = self.cur

        @contextmanager
        def one_transaction(commit=False):
            yield cur

        for module in (payroll, bank):
            patcher = mock.patch.object(module, "db_cursor", one_transaction)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(self.close)
        self.codes = []
        for number, amount in enumerate((1000, 2000, "3000.50"), start=1):
            cur.execute(
                "INSERT INTO orion_ods.employee_transaction (employee_transaction_code, transaction_date, month_year, days_worked, salary_amount, salary_paid) "
                "VALUES (%s, %s, %s, 30, %s, 'No')",
                (f"ZZ-ETR-{number}", date(2099, 1, 31), MONTH, amount),
            )
            self.codes.append(f"ZZ-ETR-{number}")
        cur.execute("SELECT account_id, opening_date FROM orion_ods.bank_account ORDER BY account_id")
        self.accounts = cur.fetchall()

    def close(self):
        self.conn.rollback()
        self.conn.close()

    def seen(self, codes):
        found = payroll.unpaid_lines(MONTH)
        chosen = [line for line in found["lines"] if line["code"] in codes]
        return {"seen_count": len(chosen), "seen_total": str(sum((Decimal(str(line["amount"])) for line in chosen), Decimal(0)))}

    def account(self):
        return {"account_id": self.accounts[0][0]} if self.accounts else {}

    def movements(self):
        self.cur.execute("SELECT m.source_ref, m.amount, m.direction, m.move_date, m.reference FROM orion_ods.bank_movement m WHERE m.source = 'payroll' AND m.description LIKE %s ORDER BY m.source_ref", (f"Salary for {MONTH}%",))
        return self.cur.fetchall()

    def expected(self):
        self.cur.execute("SELECT amount, due_date FROM orion_ods.bank_expected WHERE source = 'payroll_due' AND source_ref = %s", (MONTH,))
        return self.cur.fetchall()

    def sql_refused(self, sql, args, constraint):
        from psycopg2 import errors

        self.cur.execute("SAVEPOINT attempt")
        with self.assertRaises(errors.CheckViolation) as caught:
            self.cur.execute(sql, args)
        self.assertEqual(caught.exception.diag.constraint_name, constraint)
        self.cur.execute("ROLLBACK TO SAVEPOINT attempt")

    def test_unpaid_paid_in_runs_and_taken_back(self):
        month = next(m for m in payroll.months(120) if m["month_year"] == MONTH)
        self.assertEqual((month["lines"], month["unpaid_lines"], month["unpaid_total"], month["runs"]), (3, 3, Decimal("6000.50"), 0))
        self.assertEqual(self.movements(), [])  # owed, not paid: the bank has not moved
        self.assertEqual([(Decimal(a), d) for a, d in self.expected()], [(Decimal("6000.50"), date(2099, 1, 31))])  # but it is due, at the month end

        first_codes = self.codes[:2]
        # not confirmed, a stale view, another month, and a future day all write nothing
        with self.assertRaises(payroll.PayrollError):
            payroll.record_run(1, **run_args(month_year=MONTH, line_codes=first_codes, confirm=False, **self.seen(first_codes)))
        with self.assertRaises(payroll.PayrollConflict):
            payroll.record_run(1, **run_args(month_year=MONTH, line_codes=first_codes, seen_count=2, seen_total="3000.01", **self.account()))
        with self.assertRaises(payroll.PayrollConflict):
            payroll.record_run(1, **run_args(month_year="2099-02", line_codes=first_codes, **self.seen(first_codes), **self.account()))
        if len(self.accounts) > 1:
            with self.assertRaises(payroll.PayrollError) as which:
                payroll.record_run(1, **run_args(month_year=MONTH, line_codes=first_codes, **self.seen(first_codes)))
            self.assertIn("account", str(which.exception))
        self.assertEqual(self.movements(), [])

        run = payroll.record_run(1, **run_args(month_year=MONTH, line_codes=first_codes, paid_date=TODAY, reference="NEFT-ZZ", **self.seen(first_codes), **self.account()))
        self.assertEqual((run["lines"], Decimal(run["total"])), (2, Decimal("3000.00")))
        self.assertEqual([(Decimal(a), d, r) for _, a, d, _, r in self.movements()], [(Decimal("3000.00"), "out", "NEFT-ZZ")])  # one movement for the run
        self.assertEqual([Decimal(a) for a, _ in self.expected()], [Decimal("3000.50")])  # only what is still unpaid is still to come
        self.cur.execute("SELECT salary_paid, salary_run_id FROM orion_ods.employee_transaction WHERE employee_transaction_code = %s", (first_codes[0],))
        self.assertEqual(self.cur.fetchone(), ("Yes", run["run_id"]))
        with self.assertRaises(payroll.PayrollConflict):  # the same lines cannot be paid twice
            payroll.record_run(1, **run_args(month_year=MONTH, line_codes=first_codes, seen_count=2, seen_total="3000", **self.account()))

        # what a run paid stays as it was paid (the database says so, whatever wrote it)
        paid = first_codes[0]
        self.sql_refused("UPDATE orion_ods.employee_transaction SET salary_amount = 1 WHERE employee_transaction_code = %s", (paid,), "salary_line_paid_is_locked")
        self.sql_refused("UPDATE orion_ods.employee_transaction SET salary_paid = 'No' WHERE employee_transaction_code = %s", (paid,), "salary_line_paid_is_locked")
        self.sql_refused("DELETE FROM orion_ods.employee_transaction WHERE employee_transaction_code = %s", (paid,), "salary_line_paid_cannot_be_deleted")
        self.sql_refused("UPDATE orion_ods.employee_transaction SET salary_paid = 'Yes' WHERE employee_transaction_code = %s", (self.codes[2],), "salary_paid_needs_run")
        self.sql_refused(
            "INSERT INTO orion_ods.employee_transaction (transaction_date, month_year, salary_amount, salary_paid) VALUES (%s, %s, 5, 'Yes')", (date(2099, 1, 31), MONTH), "salary_paid_needs_run",
        )
        self.cur.execute("UPDATE orion_ods.employee_transaction SET days_worked = 28 WHERE employee_transaction_code = %s", (paid,))  # anything else is fine

        second = payroll.record_run(1, **run_args(month_year=MONTH, line_codes=[self.codes[2]], reference="NEFT-ZZ-2", **self.seen([self.codes[2]]), **self.account()))
        self.assertEqual(len(self.movements()), 2)
        self.assertEqual(self.expected(), [])
        listed = payroll.runs(month_year=MONTH)
        self.assertEqual([(r["lines"], r["reversed"]) for r in listed], [(1, False), (2, False)])

        payroll.reverse_run(run["run_id"], 1, confirm=True, reason="paid from the wrong account")
        self.assertEqual(len(self.movements()), 1)  # the money is back in the account it left
        self.assertEqual([Decimal(a) for a, _ in self.expected()], [Decimal("3000.00")])  # and the two lines are owed again
        self.cur.execute("SELECT salary_paid, salary_run_id FROM orion_ods.employee_transaction WHERE employee_transaction_code = %s", (paid,))
        self.assertEqual(self.cur.fetchone(), ("No", None))
        self.cur.execute("UPDATE orion_ods.employee_transaction SET salary_amount = 1100 WHERE employee_transaction_code = %s", (paid,))  # a line of a reversed run can be corrected
        with self.assertRaises(payroll.PayrollConflict):
            payroll.reverse_run(run["run_id"], 1, confirm=True, reason="again")
        self.assertTrue(next(r for r in payroll.runs(month_year=MONTH) if r["run_id"] == run["run_id"])["reversed"])  # the reversed run is kept, marked
        self.assertEqual(second["lines"], 1)

    def test_a_line_with_no_answer_is_a_line_not_yet_paid(self):
        self.cur.execute(
            "INSERT INTO orion_ods.employee_transaction (employee_transaction_code, transaction_date, month_year, salary_amount) VALUES ('ZZ-ETR-9', %s, %s, 50)",
            (date(2099, 1, 31), MONTH),
        )
        self.cur.execute(
            "INSERT INTO orion_ods.employee_transaction (employee_transaction_code, transaction_date, month_year, salary_amount, salary_paid) VALUES ('ZZ-ETR-10', %s, %s, 60, NULL)",
            (date(2099, 1, 31), MONTH),
        )
        self.cur.execute("SELECT employee_transaction_code, salary_paid FROM orion_ods.employee_transaction WHERE employee_transaction_code IN ('ZZ-ETR-9', 'ZZ-ETR-10') ORDER BY 1")
        self.assertEqual(self.cur.fetchall(), [("ZZ-ETR-10", "No"), ("ZZ-ETR-9", "No")])  # left out, or sent empty, it is No: Payroll finds it
        month = next(m for m in payroll.months(120) if m["month_year"] == MONTH)
        self.assertEqual(month["unpaid_lines"], 5)

    def test_the_same_request_twice_pays_once(self):
        from app.idempotency import Idempotency

        def attempt():
            return payroll.record_run(
                1, **run_args(month_year=MONTH, line_codes=self.codes, **self.seen(self.codes), **self.account()), idem=Idempotency(1, "zz-payroll-key-0001", "salary.run", "fp"),
            )

        first, second = attempt(), attempt()
        self.assertEqual(first["run_id"], second["run_id"])
        self.cur.execute("SELECT COUNT(*) FROM orion_ods.salary_run WHERE month_year = %s", (MONTH,))
        self.assertEqual(self.cur.fetchone()[0], 1)

    def test_a_statement_line_matches_the_run_and_a_reversal_breaks_the_match(self):
        banks = [a for a, _ in self.accounts]
        if not banks:  # a database with no account yet: make one here (rolled back with everything else)
            self.cur.execute("INSERT INTO orion_ods.bank_account (account_name, opening_balance, opening_date) VALUES ('ZZ pay check', 0, %s) RETURNING account_id", (TODAY - timedelta(days=5),))
            banks = [self.cur.fetchone()[0]]
        run = payroll.record_run(1, **run_args(month_year=MONTH, line_codes=self.codes, reference="UTR-ZZ-PAY", account_id=banks[0], **self.seen(self.codes)))
        self.cur.execute("INSERT INTO orion_ods.bank_statement_import (account_id, filename, file_sha256) VALUES (%s, 'zz.csv', 'zz-sha-pay') RETURNING import_id", (banks[0],))
        import_id = self.cur.fetchone()[0]
        self.cur.execute(
            "INSERT INTO orion_ods.bank_statement_line (import_id, account_id, line_date, description, reference, direction, amount, fingerprint) "
            "VALUES (%s, %s, %s, 'BULK SALARY UTR-ZZ-PAY', 'UTR-ZZ-PAY', 'out', 6000.50, 'zz-fp-pay') RETURNING line_id",
            (import_id, banks[0], TODAY),
        )
        line_id = self.cur.fetchone()[0]
        bank.match_line(line_id, [{"source": "payroll", "source_ref": str(run["run_id"])}], 1)  # one transfer, one movement
        self.assertEqual([i for i in bank.exceptions(banks[0]) if i["line_id"] == line_id], [])
        payroll.reverse_run(run["run_id"], 1, confirm=True, reason="paid from the wrong account")
        broken = [i for i in bank.exceptions(banks[0]) if i["line_id"] == line_id]
        self.assertEqual(len(broken), 1)
        self.assertIn("salary pay run was reversed", broken[0]["reason"])


if __name__ == "__main__":
    unittest.main()
