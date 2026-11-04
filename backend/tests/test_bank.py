"""The Bank module: what a person may enter, who may see and change it, what the AI may be asked, and (against the development database, with
ORION_DB_TESTS=1) the whole life of an account: balance, entries, statement upload, matching, reconciliation."""

import os
import sys
import unittest
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from app import bank  # noqa: E402
from app.dependencies import get_current_user  # noqa: E402
from app.main import app  # noqa: E402
from app.routers import bank_router  # noqa: E402

TODAY = date.today()
RUN = os.environ.get("ORION_DB_TESTS") == "1"


def good_entry(**changes):
    data = {"direction": "in", "category": "interest", "amount": "1250.75", "entry_date": TODAY - timedelta(days=1), "counterparty": "Bank", "description": "Q4 interest"}
    data.update(changes)
    return data


class WhatMayBeEntered(unittest.TestCase):
    def refused(self, **changes):
        with mock.patch.object(bank, "db_cursor", side_effect=AssertionError("refused before the database was touched")):
            with self.assertRaises(bank.BankError) as caught:
                bank.create_entry(good_entry(**changes), 1)
        return str(caught.exception)

    def test_direction_and_category_must_fit(self):
        self.refused(direction="sideways")
        self.refused(direction=None)
        self.refused(category="bank_charges")  # a charge is money out
        self.refused(direction="out", category="interest")
        self.refused(category="made_up")

    def test_a_receipt_with_no_bill_needs_a_reason(self):
        for note in (None, "", "   "):
            self.assertIn("what this receipt is for", self.refused(category="other_receipt", description=note))
        self.assertIn("other_receipt", bank.ENTRY_CATEGORIES["in"])
        self.assertNotIn("other_receipt", bank.INCOME_CATEGORIES)  # an advance or a deposit is not income

    def test_the_amount_is_positive_a_number_and_not_absurd(self):
        for amount in ("0", "-5", "abc", "", None, "1e400", "NaN", "999999999999"):
            self.refused(amount=amount)

    def test_the_date_cannot_be_in_the_future_or_missing(self):
        self.assertIn("future", self.refused(entry_date=TODAY + timedelta(days=1)))
        self.refused(entry_date="not a date")

    def test_text_is_limited(self):
        self.refused(description="x" * 301)
        self.refused(counterparty="y" * 121)

    def test_the_account_must_exist_first(self):
        class Cur:
            description = []

            def execute(self, *a, **k):
                pass

            def fetchall(self):
                return []

        class Ctx:
            def __enter__(self):
                return Cur()

            def __exit__(self, *a):
                return False

        with mock.patch.object(bank, "db_cursor", return_value=Ctx()):
            with self.assertRaisesRegex(bank.BankError, "opening balance"):
                bank.create_entry(good_entry(), 1)

    def test_the_account_details_are_checked(self):
        base = {"account_name": "Current account", "bank_name": "HDFC", "account_last4": "1234", "opening_balance": "100000.50", "opening_date": TODAY - timedelta(days=30)}
        for change in ({"account_name": ""}, {"account_last4": "12"}, {"account_last4": "12ab"}, {"opening_balance": "lots"}, {"opening_date": TODAY + timedelta(days=1)},
                       {"opening_balance": "1" + "0" * 15}):
            with self.assertRaises(bank.BankError, msg=str(change)):
                with mock.patch.object(bank, "db_cursor", side_effect=AssertionError("refused before the database was touched")):
                    bank.save_account({**base, **change}, 1)

    def test_a_void_needs_a_reason(self):
        with self.assertRaises(bank.BankError):
            bank.void_entry(1, "", 1)
        with self.assertRaises(bank.BankError):
            bank.void_entry(1, "no", 1)

    def test_filters_are_checked(self):
        for bad in ({"direction": "up"}, {"source": "tally"}, {"reconciled": "maybe"}, {"date_from": "yesterday"}):
            with self.assertRaises(bank.BankError, msg=str(bad)):
                bank.ledger(**bad)
        with self.assertRaises(bank.BankError):
            bank.series("many")


class SmallThings(unittest.TestCase):
    def test_the_financial_year_starts_in_april(self):
        self.assertEqual(bank.financial_year_start(date(2026, 3, 31)), date(2025, 4, 1))
        self.assertEqual(bank.financial_year_start(date(2026, 4, 1)), date(2026, 4, 1))
        self.assertEqual(bank.financial_year_start(date(2026, 12, 31)), date(2026, 4, 1))

    def test_a_spreadsheet_cannot_be_made_to_run_a_formula(self):
        for text in ("=HYPERLINK(1)", "+1", "-1", "@SUM(A1)"):
            self.assertTrue(bank._safe_cell(text).startswith("'"), text)
        self.assertEqual(bank._safe_cell("Rent"), "Rent")
        self.assertEqual(bank._safe_cell(None), "")

    def test_every_category_has_a_label_and_the_income_ones_exist(self):
        for direction in ("in", "out"):
            for key in bank.ENTRY_CATEGORIES[direction]:
                self.assertIn(key, bank.CATEGORY_LABELS)
        for key in bank.INCOME_CATEGORIES:
            self.assertIn(key, bank.ENTRY_CATEGORIES["in"])

    def test_the_rules_for_guessing_only_name_categories_a_person_can_choose(self):
        from app import bank_match

        for category, direction, _pattern, _why in bank_match.RULES:
            self.assertIn(category, bank.ENTRY_CATEGORIES[direction], category)

    def test_money_is_written_the_indian_way(self):
        self.assertEqual(bank._inr(Decimal("1234.5")), "₹1,234.50")


class WhoMaySeeAndChange(unittest.TestCase):
    def setUp(self):
        app.dependency_overrides.clear()
        self.addCleanup(app.dependency_overrides.clear)

    def routes(self):
        found = []
        for route in bank_router.router.routes:
            for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
                found.append((method, "/api" + route.path))
        return found

    def call(self, method, path):
        concrete = path.replace("{line_id}", "1").replace("{entry_id}", "1").replace("{import_id}", "1")
        return TestClient(app).request(method, concrete)

    def test_there_are_routes_to_test(self):
        self.assertGreater(len(self.routes()), 20)

    def test_nobody_signed_out_gets_anything(self):
        for method, path in self.routes():
            self.assertIn(self.call(method, path).status_code, (401, 403), f"{method} {path}")

    def test_a_person_without_bank_access_gets_nothing(self):
        app.dependency_overrides[get_current_user] = lambda: {"id": 5, "role": "editor", "bank_access": False, "bank_write": False}
        for method, path in self.routes():
            self.assertEqual(self.call(method, path).status_code, 403, f"{method} {path}")

    def test_an_ordinary_admin_flag_alone_is_not_enough_when_the_flags_say_no(self):
        app.dependency_overrides[get_current_user] = lambda: {"id": 5, "role": "admin", "bank_access": False, "bank_write": False}
        for method, path in self.routes():
            self.assertEqual(self.call(method, path).status_code, 403, f"{method} {path}")

    def test_a_person_who_can_only_look_cannot_change_anything(self):
        app.dependency_overrides[get_current_user] = lambda: {"id": 5, "role": "viewer", "bank_access": True, "bank_write": False}
        for method, path in self.routes():
            if method != "GET":
                self.assertEqual(self.call(method, path).status_code, 403, f"{method} {path}")

    def test_the_idempotency_key_is_checked(self):
        app.dependency_overrides[get_current_user] = lambda: {"id": 5, "role": "viewer", "bank_access": True, "bank_write": True}
        body = {"entry_date": TODAY.isoformat(), "direction": "in", "amount": 5, "category": "interest"}
        with mock.patch.object(bank, "create_entry") as create:
            response = TestClient(app).post("/api/bank/entries", json=body, headers={"Idempotency-Key": "x"})
        self.assertEqual(response.status_code, 400)
        create.assert_not_called()

    def test_a_repeat_is_answered_not_repeated(self):
        app.dependency_overrides[get_current_user] = lambda: {"id": 5, "role": "viewer", "bank_access": True, "bank_write": True}
        body = {"entry_date": TODAY.isoformat(), "direction": "in", "amount": 5, "category": "interest"}
        with mock.patch.object(bank, "create_entry", return_value={"entry_id": 9}) as create:
            response = TestClient(app).post("/api/bank/entries", json=body, headers={"Idempotency-Key": "a-valid-key-12345"})
        self.assertEqual(response.status_code, 201)
        self.assertIsNotNone(create.call_args.args[2])  # the key reached the code that does the work

    def test_a_conflict_is_a_409_and_a_mistake_a_400(self):
        app.dependency_overrides[get_current_user] = lambda: {"id": 5, "role": "viewer", "bank_access": True, "bank_write": True}
        client = TestClient(app)
        with mock.patch.object(bank, "unmatch_line", side_effect=bank.BankConflict("no")):
            self.assertEqual(client.post("/api/bank/lines/1/unmatch").status_code, 409)
        with mock.patch.object(bank, "unmatch_line", side_effect=bank.BankError("no")):
            self.assertEqual(client.post("/api/bank/lines/1/unmatch").status_code, 400)

    def test_a_huge_upload_is_refused_and_the_column_choices_are_checked(self):
        app.dependency_overrides[get_current_user] = lambda: {"id": 5, "role": "viewer", "bank_access": True, "bank_write": True}
        client = TestClient(app)
        with mock.patch.object(bank, "preview_statement") as preview:
            big = client.post("/api/bank/statements/preview", files={"file": ("s.csv", b"x" * (6 * 1024 * 1024 + 1))})
            self.assertEqual(big.status_code, 413)
            for bad in ('{"nope": 1}', '{"date": "a"}', '{"date": -1}', "[1]", "{", '{"date": true}'):
                response = client.post("/api/bank/statements/preview", files={"file": ("s.csv", b"a,b")}, data={"mapping": bad})
                self.assertEqual(response.status_code, 400, bad)
            preview.assert_not_called()
            preview.return_value = {"ok": True}
            ok = client.post("/api/bank/statements/preview", files={"file": ("s.csv", b"a,b")}, data={"mapping": '{"date": 0, "description": 1}', "header_row": "2"})
            self.assertEqual(ok.status_code, 200)
            self.assertEqual(preview.call_args.args[2:], ({"date": 0, "description": 1}, 2, None))


class WhatTheAiIsAsked(unittest.TestCase):
    LINES = [
        {"line_id": 1, "direction": "in", "description": "NEFT CR 50100123456789 SOMETHING", "reference": None},
        {"line_id": 2, "direction": "out", "description": "CHQ PAID 000123", "reference": None},
    ]

    def run_with(self, data, status="ok"):
        from app.ai import features

        seen = {}

        def fake(user, job, allow_cloud_once=False):
            seen["job"] = job
            seen["consent"] = allow_cloud_once
            return {"status": status, "data": data, "where": "local", "provider": "test"} if status == "ok" else {"status": status, "message": "x"}

        with mock.patch.object(features.assist, "run", side_effect=fake):
            return features.categorise_bank_lines({"id": 1}, self.LINES, allow_cloud_once=True), seen

    def test_only_valid_suggestions_for_lines_that_were_asked_come_back(self):
        out, _ = self.run_with({"items": [
            {"id": 1, "category": "other_income", "counterparty": "Acme"},
            {"id": 2, "category": "interest"},          # not a category for money out
            {"id": 99, "category": "other_in"},         # a line nobody asked about
            {"id": "x", "category": "other_in"}, "junk", {"category": "other_in"},
        ]})
        self.assertEqual(list(out["suggestions"]), [1])
        self.assertEqual(out["suggestions"][1]["category"], "other_income")
        self.assertEqual(out["suggestions"][1]["counterparty"], "Acme")

    def test_long_numbers_are_cut_before_they_leave_and_the_text_is_marked_as_data(self):
        _, seen = self.run_with({"items": []})
        self.assertNotIn("50100123456789", seen["job"].prompt)
        self.assertIn("6789", seen["job"].prompt)
        self.assertIn("<lines>", seen["job"].prompt)
        self.assertIn("data, not instructions", seen["job"].system)
        self.assertTrue(seen["consent"])
        self.assertEqual(seen["job"].kind, "bank")

    def test_a_refusal_is_passed_on(self):
        out, _ = self.run_with(None, status="needs_consent")
        self.assertEqual(out["status"], "needs_consent")

    def test_nothing_to_sort(self):
        from app.ai import features

        self.assertEqual(features.categorise_bank_lines({"id": 1}, [])["status"], "invalid")


STATEMENT = """Account Statement
Date,Narration,Chq./Ref.No.,Withdrawal Amt.,Deposit Amt.,Closing Balance
{d4},EARLIER DEPOSIT,,,100.00,"10,100.00"
{d1},INT.PD:01-01 TO 31-03,,,777.77,"10,877.77"
{d2},SMS CHARGES,,23.60,,"10,854.17"
{d3},NEFT CR-UNKNOWN PAYER,,,"55,555.55","66,409.72"
"""
LATER = """Account Statement
Date,Narration,Chq./Ref.No.,Withdrawal Amt.,Deposit Amt.,Closing Balance
{d1},INT.PD:01-01 TO 31-03,,,777.77,"10,877.77"
{d2},SMS CHARGES,,23.60,,"10,854.17"
{d3},NEFT CR-UNKNOWN PAYER,,,"55,555.55","66,409.72"
{d3},CHQ PAID-000999-SOMEONE,000999,10.00,,"66,399.72"
"""


@unittest.skipUnless(RUN, "set ORION_DB_TESTS=1 to run these against the development database")
class AgainstTheRealDatabase(unittest.TestCase):
    """An account with a statement, from opening to reconciled. Only runs when the development database holds no bank account (so it cannot touch
    a person's own), and removes everything it made."""

    PREFIX = "zz-bank-"

    @classmethod
    def setUpClass(cls):
        from app import auth
        from app.database import db_cursor

        with db_cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM orion_ods.bank_account")
            if cur.fetchone()[0]:
                raise unittest.SkipTest("the development database already has a bank account; this test will not touch it")
        with db_cursor(commit=True) as cur:
            cur.execute("DELETE FROM orion_ods.app_user WHERE username = 'zz_bank'")
        auth.create_user("zz_bank", "Bank test", "a long private pass phrase 1", role="admin")
        cls.user = auth._fetch_user_by_username("zz_bank")["id"]
        cls.addClassCleanup(cls.cleanup)

    @classmethod
    def cleanup(cls):
        from app.database import db_cursor

        with db_cursor(commit=True) as cur:
            for table in ("bank_match", "bank_statement_line", "bank_statement_import", "bank_entry", "bank_audit", "bank_account"):
                cur.execute(f"DELETE FROM orion_ods.{table}")
            cur.execute("DELETE FROM orion_ods.idempotency_key WHERE idem_key LIKE %s", (cls.PREFIX + "%",))
            cur.execute("DELETE FROM orion_ods.app_user WHERE username = 'zz_bank'")

    def dates(self):
        d = lambda n: TODAY - timedelta(days=n)  # noqa: E731 - a throwaway
        return {"d4": d(40).strftime("%d/%m/%Y"), "d1": d(3).strftime("%d/%m/%Y"), "d2": d(2).strftime("%d/%m/%Y"), "d3": d(1).strftime("%d/%m/%Y")}

    def test_the_whole_life_of_an_account(self):
        from app.idempotency import Idempotency

        self.assertEqual(bank.get_account(), {"configured": False})
        with self.assertRaisesRegex(bank.BankError, "opening balance"):
            bank.create_entry(good_entry(), self.user)
        opening_date = TODAY - timedelta(days=30)
        account = bank.save_account({"account_name": "Current account", "bank_name": "Test bank", "account_last4": "1234",
                                     "opening_balance": "10100.00", "opening_date": opening_date}, self.user)
        self.assertTrue(account["configured"])
        base = Decimal(str(account["balance"]))

        # changing the opening balance needs the confirmation, and says what the balance will become
        with self.assertRaises(bank.BankConflict):
            bank.save_account({**account, "opening_balance": "20000.00"}, self.user)
        preview = bank.preview_account_change("20000.00", opening_date)
        self.assertEqual(Decimal(str(preview["new_balance"])) - Decimal(str(preview["current_balance"])), Decimal("9900.00"))

        # an entry raises the balance, shows in the ledger with the balance after it, and a repeat of the same request does nothing
        key = Idempotency(self.user, self.PREFIX + "interest-0001", "bank.entry", "fp-1")
        interest = bank.create_entry(good_entry(amount="777.77", entry_date=TODAY - timedelta(days=3), counterparty="Test bank"), self.user, key)
        again = bank.create_entry(good_entry(amount="777.77", entry_date=TODAY - timedelta(days=3), counterparty="Test bank"),
                                  self.user, Idempotency(self.user, self.PREFIX + "interest-0001", "bank.entry", "fp-1"))
        self.assertEqual(interest["entry_id"], again["entry_id"])
        self.assertEqual(Decimal(str(bank.get_account()["balance"])), base + Decimal("777.77"))
        listing = bank.ledger(q="Test bank")
        self.assertEqual(listing["total"], 1)
        self.assertEqual(listing["rows"][0]["category"], "interest")
        self.assertFalse(listing["rows"][0]["reconciled"])
        everything = bank.ledger(limit=200)
        self.assertEqual(Decimal(str(everything["rows"][0]["balance"])), Decimal(str(bank.get_account()["balance"])))
        with self.assertRaises(bank.BankError):  # before the opening date: already inside the opening balance
            bank.create_entry(good_entry(entry_date=opening_date - timedelta(days=1)), self.user)

        summary = bank.summary()
        self.assertEqual(Decimal(str(summary["financial_year"]["interest"])), Decimal("777.77"))
        self.assertGreaterEqual(Decimal(str(summary["financial_year"]["interest_and_other_income"])), Decimal("777.77"))
        months = bank.series(6)
        self.assertEqual(Decimal(str(months["months"][-1]["closing_balance"])), Decimal(str(bank.get_account()["balance"])))
        self.assertTrue(bank.forecast()["configured"])
        self.assertIn("Date,Kind", bank.ledger_csv())

        # a statement: read, shown, imported; the interest is found by itself; the same file again is refused
        dates = self.dates()
        file_one = STATEMENT.format(**dates).encode()
        shown = bank.preview_statement("one.csv", file_one)
        self.assertTrue(shown["can_import"])
        self.assertEqual((shown["new_lines"], shown["before_opening_date"], shown["balanced"]), (4, 1, True))
        done = bank.import_statement("one.csv", file_one, self.user)
        self.assertEqual((done["new_count"], done["duplicate_count"], done["auto_matched"]), (4, 0, 1))
        with self.assertRaises(bank.BankConflict):
            bank.import_statement("one.csv", file_one, self.user)
        self.assertFalse(bank.preview_statement("one.csv", file_one)["can_import"])
        self.assertEqual(bank.lines(status="Matched")["total"], 1)
        self.assertEqual(bank.lines(status="Ignored")["total"], 1)  # the line before the opening date

        # a later upload that overlaps adds only what is new
        file_two = LATER.format(**dates).encode()
        later = bank.import_statement("two.csv", file_two, self.user)
        self.assertEqual((later["new_count"], later["duplicate_count"]), (1, 3))

        unmatched = {row["description"]: row for row in bank.lines(status="Unmatched")["rows"]}
        self.assertEqual(set(unmatched), {"SMS CHARGES", "NEFT CR-UNKNOWN PAYER", "CHQ PAID-000999-SOMEONE"})
        self.assertEqual(unmatched["SMS CHARGES"]["guess"]["category"], "bank_charges")
        self.assertIsNone(unmatched["NEFT CR-UNKNOWN PAYER"]["guess"])

        # the bank charge has no record in Orion: make it from the line, and the two are matched in one step
        charge = bank.entry_from_line(unmatched["SMS CHARGES"]["line_id"], {"category": "bank_charges"}, self.user)
        self.assertEqual(charge["amount"], 23.6)
        with self.assertRaises(bank.BankConflict):
            bank.entry_from_line(unmatched["SMS CHARGES"]["line_id"], {"category": "bank_charges"}, self.user)
        self.assertTrue(bank.ledger(q="SMS")["rows"][0]["reconciled"])

        # a deposit nobody can explain is set aside with a reason; a cheque is matched by hand to an entry made for it
        stranger = unmatched["NEFT CR-UNKNOWN PAYER"]["line_id"]
        bank.ignore_line(stranger, "Test: a transfer from the owner", self.user)
        with self.assertRaises(bank.BankConflict):
            bank.match_line(stranger, [{"source": "entry", "source_ref": str(interest["entry_id"])}], self.user)
        bank.unignore_line(stranger, self.user)
        cheque = unmatched["CHQ PAID-000999-SOMEONE"]["line_id"]
        entry = bank.create_entry(good_entry(direction="out", category="other_out", amount="10.00", entry_date=TODAY - timedelta(days=1), counterparty="Someone"), self.user)
        found = bank.suggestions(cheque)
        self.assertEqual([c["movement"]["source_ref"] for c in found["candidates"]], [str(entry["entry_id"])])
        with self.assertRaises(bank.BankError):  # an entry in the other direction cannot be it
            bank.match_line(cheque, [{"source": "entry", "source_ref": str(interest["entry_id"])}], self.user)
        bank.match_line(cheque, [{"source": "entry", "source_ref": str(entry["entry_id"])}], self.user)
        with self.assertRaises(bank.BankConflict):  # a movement is on one line at most (the interest is already on its own line)
            bank.match_line(stranger, [{"source": "entry", "source_ref": str(interest["entry_id"])}], self.user)

        # book and bank agree once the unmatched items are accounted for
        state = bank.reconciliation()
        self.assertEqual(Decimal(str(state["unexplained"])), 0)
        self.assertEqual(state["statement_only"]["count"], 1)  # the stranger's deposit
        self.assertEqual(Decimal(str(state["statement_balance"])), Decimal("66399.72"))

        # a wrong entry is voided, not deleted: it stops counting and its line is unmatched again
        before = Decimal(str(bank.get_account()["balance"]))
        with self.assertRaises(bank.BankError):
            bank.void_entry(entry["entry_id"], "x", self.user)
        bank.void_entry(entry["entry_id"], "Test: entered by mistake", self.user)
        self.assertEqual(Decimal(str(bank.get_account()["balance"])), before + Decimal("10.00"))
        with self.assertRaises(bank.BankConflict):
            bank.void_entry(entry["entry_id"], "Test: again", self.user)
        self.assertEqual(bank.lines(status="Unmatched")["total"], 2)
        self.assertEqual(Decimal(str(bank.reconciliation()["unexplained"])), 0)

        # a wrong upload is taken back, unless some of it is matched
        with self.assertRaises(bank.BankError):
            bank.remove_import(done["import_id"], self.user)
        bank.remove_import(later["import_id"], self.user)
        self.assertEqual(bank.lines(status="Unmatched")["total"], 1)

        actions = [a["action"] for a in bank.activity(100)]
        for expected in ("account.create", "entry.create", "statement.import", "match.manual", "entry.void", "statement.remove"):
            self.assertIn(expected, actions)


class AccountsInTheBilling(unittest.TestCase):
    """A payment names the account it went into; an account that does not exist is refused, and none means the default account."""

    def cursor(self, exists):
        class Cur:
            def execute(self, *a, **k):
                self.args = a

            def fetchone(self):
                return (1,) if exists else None

        return Cur()

    def test_none_is_the_default_account_and_a_real_one_is_kept(self):
        from app import billing

        self.assertIsNone(billing._checked_account(self.cursor(True), None))
        self.assertIsNone(billing._checked_account(self.cursor(True), ""))
        self.assertEqual(billing._checked_account(self.cursor(True), "3"), 3)

    def test_an_unknown_or_malformed_account_is_refused(self):
        from app import billing

        with self.assertRaises(billing.BillError):
            billing._checked_account(self.cursor(False), 99)
        with self.assertRaises(billing.BillError):
            billing._checked_account(self.cursor(True), "abc")


@unittest.skipUnless(RUN, "set ORION_DB_TESTS=1 to run these against the development database")
class SeveralAccountsAgainstTheRealDatabase(unittest.TestCase):
    """A bank account and a cash account: balances, the ledger, statements and matching stay inside the account they belong to."""

    PREFIX = "zz-acc-"

    @classmethod
    def setUpClass(cls):
        from app import auth
        from app.database import db_cursor

        with db_cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM orion_ods.bank_account")
            if cur.fetchone()[0]:
                raise unittest.SkipTest("the development database already has a bank account; this test will not touch it")
        with db_cursor(commit=True) as cur:
            cur.execute("DELETE FROM orion_ods.app_user WHERE username = 'zz_accounts'")
        auth.create_user("zz_accounts", "Accounts test", "a long private pass phrase 1", role="admin")
        cls.user = auth._fetch_user_by_username("zz_accounts")["id"]
        cls.addClassCleanup(cls.cleanup)

    @classmethod
    def cleanup(cls):
        from app.database import db_cursor

        with db_cursor(commit=True) as cur:
            for table in ("bank_match", "bank_statement_line", "bank_statement_import", "bank_entry", "bank_audit", "bank_account"):
                cur.execute(f"DELETE FROM orion_ods.{table}")
            cur.execute("DELETE FROM orion_ods.idempotency_key WHERE idem_key LIKE %s", (cls.PREFIX + "%",))
            cur.execute("DELETE FROM orion_ods.app_user WHERE username = 'zz_accounts'")

    def dev_movements(self, account_id):
        """What the book already holds for the first account (the development data's payments and expenses), so the test does not assume an empty book."""
        from app.database import db_cursor

        with db_cursor() as cur:
            cur.execute(
                "SELECT COALESCE(SUM(CASE WHEN direction = 'in' THEN amount ELSE -amount END), 0) FROM orion_ods.bank_movement m "
                "JOIN orion_ods.bank_account a ON a.account_id = m.account_id WHERE m.account_id = %s AND m.source <> 'entry' "
                "AND m.move_date >= a.opening_date AND m.move_date <= CURRENT_DATE",
                (account_id,),
            )
            return Decimal(cur.fetchone()[0])

    def test_two_accounts(self):
        today = TODAY
        first = bank.save_account({"account_name": "Current", "account_kind": "bank", "opening_balance": "1000.00", "opening_date": today - timedelta(days=60)}, self.user)
        cash = bank.save_account({"account_name": "Petty cash", "account_kind": "cash", "opening_balance": "200.00", "opening_date": today - timedelta(days=20)}, self.user, create=True)
        self.assertNotEqual(first["account_id"], cash["account_id"])
        self.assertEqual(cash["account_kind"], "cash")
        self.assertEqual([a["account_name"] for a in bank.list_accounts()["accounts"]], ["Current", "Petty cash"])

        # money goes into the account it names; the default is the first account
        a = bank.create_entry(good_entry(amount="500.00", entry_date=today - timedelta(days=10), category="interest"), self.user)
        b = bank.create_entry(good_entry(amount="30.00", entry_date=today - timedelta(days=5), category="refund", account_id=cash["account_id"]), self.user)
        bank.create_entry(good_entry(direction="out", category="other_out", amount="10.00", entry_date=today - timedelta(days=3), account_id=cash["account_id"]), self.user)
        self.assertEqual(a["account_id"], first["account_id"])
        self.assertEqual(b["account_id"], cash["account_id"])
        balances = {x["account_name"]: Decimal(str(x["balance"])) for x in bank.list_accounts()["accounts"]}
        self.assertEqual(balances["Current"], Decimal("1500.00") + self.dev_movements(first["account_id"]))
        self.assertEqual(balances["Petty cash"], Decimal("220.00"))
        total = Decimal(str(bank.list_accounts()["total"]))
        self.assertEqual(total, sum(balances.values()))

        # the consolidated view is the sum, the account view is its own
        self.assertEqual(Decimal(str(bank.summary()["balance"])), total)
        self.assertEqual(Decimal(str(bank.summary(cash["account_id"])["balance"])), Decimal("220.00"))
        self.assertEqual(Decimal(str(bank.series(3)["months"][-1]["closing_balance"])), total)
        self.assertEqual(Decimal(str(bank.series(3, cash["account_id"])["months"][-1]["closing_balance"])), Decimal("220.00"))
        everything = bank.ledger(limit=200)
        self.assertEqual(Decimal(str(everything["rows"][0]["balance"])), total)  # each account counts from its own opening date
        mine = bank.ledger(account_id=cash["account_id"], limit=200)
        self.assertEqual([r["account_name"] for r in mine["rows"]], ["Petty cash", "Petty cash"])
        self.assertEqual(Decimal(str(mine["rows"][0]["balance"])), Decimal("220.00"))

        # a cash account has no statement, and a statement belongs to one bank account
        text = f"Date,Narration,Withdrawal Amt.,Deposit Amt.,Closing Balance\n{(today - timedelta(days=5)).strftime('%d/%m/%Y')},REFUND,,30.00,\"1,530.00\"\n".encode()
        with self.assertRaisesRegex(bank.BankError, "cash account"):
            bank.preview_statement("s.csv", text, account_id=cash["account_id"])
        done = bank.import_statement("s.csv", text, self.user, account_id=first["account_id"])
        self.assertEqual(done["auto_matched"], 0)  # the 30.00 refund is in the cash account, so it cannot be this line
        line = bank.lines(account_id=first["account_id"])["rows"][0]
        self.assertEqual(bank.lines(account_id=cash["account_id"])["total"], 0)
        with self.assertRaisesRegex(bank.BankError, "another account"):
            bank.match_line(line["line_id"], [{"source": "entry", "source_ref": str(b["entry_id"])}], self.user)
        self.assertEqual(bank.suggestions(line["line_id"])["candidates"], [])
        self.assertTrue(bank.reconciliation(cash["account_id"])["cash"])

        # an entry made from a line goes into the line's account
        made = bank.entry_from_line(line["line_id"], {"category": "refund"}, self.user)
        self.assertEqual(made["account_id"], first["account_id"])

        # a bank account with statement lines cannot become a cash account; an unknown account is refused
        with self.assertRaisesRegex(bank.BankError, "cannot change"):
            bank.save_account({"account_name": "Current", "account_kind": "cash", "opening_balance": "1000.00", "opening_date": today - timedelta(days=60)}, self.user, account_id=first["account_id"])
        with self.assertRaises(bank.BankError):
            bank.summary(999999)


@unittest.skipUnless(RUN, "set ORION_DB_TESTS=1 to run these against the development database")
class MatchedThenChangedAgainstTheRealDatabase(unittest.TestCase):
    """A statement line matched to something that later changed in the book is shown as an exception until a person returns it to unmatched."""

    @classmethod
    def setUpClass(cls):
        from app import auth
        from app.database import db_cursor

        with db_cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM orion_ods.bank_account")
            if cur.fetchone()[0]:
                raise unittest.SkipTest("the development database already has a bank account; this test will not touch it")
        with db_cursor(commit=True) as cur:
            cur.execute("DELETE FROM orion_ods.app_user WHERE username = 'zz_changed'")
        auth.create_user("zz_changed", "Changed test", "a long private pass phrase 1", role="admin")
        cls.user = auth._fetch_user_by_username("zz_changed")["id"]
        cls.addClassCleanup(cls.cleanup)

    @classmethod
    def cleanup(cls):
        from app.database import db_cursor

        with db_cursor(commit=True) as cur:
            for table in ("bank_match", "bank_statement_line", "bank_statement_import", "bank_entry", "bank_audit", "bank_account"):
                cur.execute(f"DELETE FROM orion_ods.{table}")
            cur.execute("DELETE FROM orion_ods.app_user WHERE username = 'zz_changed'")

    def raw(self, sql, args=()):
        from app.database import db_cursor

        with db_cursor(commit=True) as cur:
            cur.execute(sql, args)

    def test_a_reversed_and_an_edited_movement_are_found_and_cleared(self):
        today = TODAY
        account = bank.save_account({"account_name": "Current", "opening_balance": "0", "opening_date": today - timedelta(days=60)}, self.user, create=True)
        mine = account["account_id"]
        first = bank.create_entry(good_entry(amount="500.00", entry_date=today - timedelta(days=10), counterparty="Alpha Traders", account_id=mine), self.user)
        second = bank.create_entry(good_entry(amount="700.00", entry_date=today - timedelta(days=8), counterparty="Beta Traders", account_id=mine), self.user)
        d = lambda n: (today - timedelta(days=n)).strftime("%d/%m/%Y")  # noqa: E731
        text = f"Date,Narration,Withdrawal Amt.,Deposit Amt.,Closing Balance\n{d(10)},ALPHA TRADERS,,500.00,500.00\n{d(8)},BETA TRADERS,,700.00,\"1,200.00\"\n".encode()
        done = bank.import_statement("s.csv", text, self.user, account_id=account["account_id"])
        self.assertEqual(done["auto_matched"], 2)
        self.assertEqual(bank.exceptions(mine), [])
        self.assertEqual(bank.summary(mine)["reconciliation"]["changed_after_matching"], 0)
        self.assertEqual(bank.reconciliation(mine)["state"], "reconciled")

        # the first entry vanishes from the book (voided behind the match's back, as a payment reversed on its bill does), the second is edited
        self.raw("UPDATE orion_ods.bank_entry SET voided_timestamp = CURRENT_TIMESTAMP, void_reason = 'test' WHERE entry_id = %s", (first["entry_id"],))
        self.raw("UPDATE orion_ods.bank_entry SET amount = 650 WHERE entry_id = %s", (second["entry_id"],))
        found = {row["description"]: row for row in bank.exceptions(mine)}
        self.assertEqual(set(found), {"ALPHA TRADERS", "BETA TRADERS"})
        self.assertIn("voided", found["ALPHA TRADERS"]["reason"])
        self.assertIn("changed from", found["BETA TRADERS"]["reason"])
        self.assertEqual(bank.summary(mine)["reconciliation"]["changed_after_matching"], 2)
        self.assertEqual(bank.reconciliation(mine)["changed_after_matching"], 2)
        self.assertNotEqual(bank.reconciliation(mine)["state"], "reconciled")
        self.assertEqual(bank.exceptions(mine + 1000), [])  # another account has none

        # returned to unmatched: the line is open again, the history says why, and a clean line cannot be "cleared"
        cleared = bank.clear_exception(found["ALPHA TRADERS"]["line_id"], self.user)
        self.assertEqual(cleared["rematched"], 0)
        self.assertEqual({r["description"] for r in bank.lines(status="Unmatched", account_id=mine)["rows"]}, {"ALPHA TRADERS"})
        with self.assertRaises(bank.BankConflict):
            bank.clear_exception(found["ALPHA TRADERS"]["line_id"], self.user)
        self.assertIn("match.exception_cleared", [a["action"] for a in bank.activity(20)])

        # the edited entry is put right (amount back), so its match holds again and nothing is left to clear
        self.raw("UPDATE orion_ods.bank_entry SET amount = 700 WHERE entry_id = %s", (second["entry_id"],))
        self.assertEqual(bank.exceptions(mine), [])


if __name__ == "__main__":
    unittest.main()
