"""A bill or a payment is saved once, however many times the request arrives.

The first half needs no database. The second half makes real bills in a far-future financial year (2099) in the development
database, and removes everything it made; it runs only with ORION_DB_TESTS=1:

    $env:ORION_DB_TESTS = "1"; python -m pytest backend/tests/test_idempotency.py
"""

import inspect
import os
import re
import sys
import threading
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from fastapi.testclient import TestClient  # noqa: E402

from app import billing, dependencies, idempotency  # noqa: E402
from app.idempotency import Idempotency, IdempotencyConflict, IdempotencyError  # noqa: E402
from app.main import app  # noqa: E402

RUN = os.environ.get("ORION_DB_TESTS") == "1"
KEY = "4f9a2c1e-7b3d-4e8a-9c52-1d6e0b7a3f10"


class FakeCursor:
    """Answers fetchone() from a queue and remembers what it was asked."""

    def __init__(self, *answers):
        self.answers, self.sql = list(answers), []

    def execute(self, sql, params=None):
        self.sql.append((" ".join(sql.split()), params))

    def fetchone(self):
        return self.answers.pop(0) if self.answers else None


class TheKey(unittest.TestCase):
    def test_no_key_is_fine_and_means_unprotected(self):
        for blank in (None, "", "   "):
            self.assertIsNone(idempotency.clean_key(blank))

    def test_a_sensible_key_is_accepted_as_it_is(self):
        self.assertEqual(idempotency.clean_key(f"  {KEY} "), KEY)
        self.assertEqual(idempotency.clean_key("a" * 100), "a" * 100)

    def test_a_key_that_is_there_but_wrong_is_refused_not_ignored(self):
        for bad in ("short", "a" * 101, "has spaces in it!!", "new\nline-0001", "semi;colon-0001", "ünïcode-123456"):
            with self.assertRaises(IdempotencyError, msg=repr(bad)):
                idempotency.clean_key(bad)

    def test_requiring_one_is_a_setting(self):
        self.assertFalse(idempotency.required({}))
        for on in ("1", "true", "YES", " on "):
            self.assertTrue(idempotency.required({"ORION_IDEMPOTENCY_REQUIRED": on}), on)
        self.assertFalse(idempotency.required({"ORION_IDEMPOTENCY_REQUIRED": "0"}))


class TheFingerprint(unittest.TestCase):
    def test_the_same_request_always_has_the_same_fingerprint(self):
        a = idempotency.fingerprint("bill.payment", 7, "BILL-1", "100.00", "2026-10-19")
        self.assertEqual(a, idempotency.fingerprint("bill.payment", 7, "BILL-1", "100.00", "2026-10-19"))

    def test_the_order_of_a_dictionarys_keys_does_not_matter(self):
        self.assertEqual(
            idempotency.fingerprint("bill.create", {"a": 1, "b": [1, 2], "c": {"x": 1, "y": 2}}),
            idempotency.fingerprint("bill.create", {"c": {"y": 2, "x": 1}, "b": [1, 2], "a": 1}),
        )

    def test_any_change_gives_a_different_one(self):
        base = idempotency.fingerprint("bill.payment", 7, "BILL-1", "100.00", "2026-10-19")
        for other in (
            idempotency.fingerprint("bill.payment", 7, "BILL-1", "100.01", "2026-10-19"),  # the amount
            idempotency.fingerprint("bill.payment", 7, "BILL-2", "100.00", "2026-10-19"),  # the bill
            idempotency.fingerprint("bill.payment", 7, "BILL-1", "100.00", "2026-10-20"),  # the date
            idempotency.fingerprint("bill.payment", 8, "BILL-1", "100.00", "2026-10-19"),  # the person
            idempotency.fingerprint("bill.create", 7, "BILL-1", "100.00", "2026-10-19"),  # what it is for
        ):
            self.assertNotEqual(base, other)

    def test_dates_and_decimals_are_hashed_not_crashed_on(self):
        self.assertEqual(len(idempotency.fingerprint("x", date(2026, 10, 19), Decimal("1.50"))), 64)


class Claiming(unittest.TestCase):
    def idem(self):
        return Idempotency(7, KEY, "bill.create", "fp-1")

    def test_the_first_time_it_says_go_ahead(self):
        cur = FakeCursor((1,))  # the INSERT returned a row
        idem = self.idem()
        self.assertIsNone(idem.claim(cur))
        self.assertFalse(idem.replayed)
        self.assertIn("INSERT INTO orion_ods.idempotency_key", cur.sql[-1][0])
        self.assertIn("ON CONFLICT (user_id, idem_key) DO NOTHING", cur.sql[-1][0])

    def test_a_repeat_gets_the_first_ones_result_and_is_marked(self):
        cur = FakeCursor(None, ("bill.create", "fp-1", {"bill_code": "BILL-9"}))  # no insert; the stored row
        idem = self.idem()
        self.assertEqual(idem.claim(cur), {"bill_code": "BILL-9"})
        self.assertTrue(idem.replayed)

    def test_the_same_key_for_something_else_is_a_conflict_not_a_repeat(self):
        for stored in (("bill.payment", "fp-1", {"x": 1}), ("bill.create", "fp-OTHER", {"x": 1})):
            cur = FakeCursor(None, stored)
            idem = self.idem()
            with self.assertRaises(IdempotencyConflict):
                idem.claim(cur)
            self.assertFalse(idem.replayed)

    def test_a_claim_without_a_result_is_never_guessed_at(self):
        with self.assertRaises(IdempotencyConflict):
            self.idem().claim(FakeCursor(None, ("bill.create", "fp-1", None)))

    def test_a_key_forgotten_between_the_two_statements_is_just_new(self):
        cur = FakeCursor(None, None, (1,))  # conflict, then the row was gone, then the second try inserts
        self.assertIsNone(self.idem().claim(cur))

    def test_remember_stores_the_result_as_json_for_this_key(self):
        cur = FakeCursor()
        self.idem().remember(cur, {"bill_code": "BILL-9"})
        sql, params = cur.sql[-1]
        self.assertIn("UPDATE orion_ods.idempotency_key SET result", sql)
        self.assertEqual(params, ('{"bill_code": "BILL-9"}', 7, KEY))

    def test_each_person_has_their_own_keys(self):
        sql = (ROOT / ".cursor" / "db" / "migrate_idempotency.sql").read_text(encoding="utf-8")
        self.assertIn("UNIQUE (user_id, idem_key)", sql)


class TheWorkAndTheKeyAreSavedTogether(unittest.TestCase):
    """The whole point: claimed and remembered inside the transaction that does the work, before it commits."""

    def test_each_protected_operation_claims_first_and_remembers_before_it_commits(self):
        for function, first_write in (
            (billing.create_bill, "_insert_bill("),
            (billing.update_bill, "INSERT INTO orion_ods.bill_version"),
            (billing.record_payment, "_sync_revenue("),
        ):
            source = inspect.getsource(function)
            self.assertIn("idem.claim(cur)", source, function.__name__)
            self.assertLess(source.index("idem.claim(cur)"), source.index(first_write), f"{function.__name__} claims after it has started")
            self.assertLess(source.index("idem.remember("), source.rindex("conn.commit()"), f"{function.__name__} remembers after committing")
            self.assertIn("conn.rollback()", source[source.index("idem.claim(cur)"):source.index(first_write)], "a repeat must end its transaction")

    def test_a_repeat_returns_the_bill_the_first_request_made(self):
        for function in (billing.create_bill, billing.update_bill, billing.record_payment):
            self.assertIn('get_bill(prior["bill_code"])', inspect.getsource(function), function.__name__)


class TheRoutes(unittest.TestCase):
    """What the API does with the header, with the billing functions replaced by fakes."""

    body = {"bill_date": "2026-10-19", "service_month": "2026-10", "case_code": "CS-1", "party_name": "Acme", "lines": [{"particulars": "x", "qty": 1, "rate": 10}]}

    def setUp(self):
        app.dependency_overrides[dependencies.require_billing_write] = lambda: {"id": 7, "role": "admin"}
        self.addCleanup(app.dependency_overrides.pop, dependencies.require_billing_write, None)
        self.client = TestClient(app, raise_server_exceptions=False)

    def call(self, fake, key=KEY, env=None, method="post", url="/api/billing/bills", json=None):
        headers = {"Idempotency-Key": key} if key is not None else {}
        target = {"/api/billing/bills": "create_bill", "/api/billing/bills/BILL-1": "update_bill", "/api/billing/bills/BILL-1/payments": "record_payment"}[url]
        with mock.patch.dict("os.environ", env or {}), mock.patch.object(billing, target, fake):
            return getattr(self.client, method)(url, json=json if json is not None else self.body, headers=headers)

    def test_the_key_reaches_the_work_with_a_fingerprint_of_what_was_asked(self):
        seen = {}

        def fake(data, user_id, idem=None):
            seen.update(idem=idem, user=user_id)
            return {"id": "BILL-1"}

        response = self.call(fake)
        self.assertEqual(response.status_code, 201)
        self.assertEqual((seen["idem"].key, seen["idem"].operation, seen["user"]), (KEY, "bill.create", 7))
        self.assertNotIn("Idempotent-Replayed", response.headers)

    def test_a_repeat_is_marked_and_still_201(self):
        def fake(data, user_id, idem=None):
            idem.replayed = True
            return {"id": "BILL-1"}

        response = self.call(fake)
        self.assertEqual((response.status_code, response.headers["Idempotent-Replayed"]), (201, "true"))

    def test_the_same_form_changed_has_a_different_fingerprint(self):
        prints = []

        def fake(data, user_id, idem=None):
            prints.append(idem.fingerprint)
            return {"id": "BILL-1"}

        self.call(fake)
        self.call(fake, json={**self.body, "party_name": "Someone else"})
        self.call(fake)
        self.assertEqual(prints[0], prints[2])
        self.assertNotEqual(prints[0], prints[1])

    def test_a_key_used_for_something_else_is_a_409_with_a_message_a_person_can_act_on(self):
        def fake(data, user_id, idem=None):
            raise IdempotencyConflict("This form was already used to save something else. Check the list.")

        response = self.call(fake)
        self.assertEqual(response.status_code, 409)
        self.assertIn("Check the list", response.json()["detail"])

    def test_a_malformed_key_is_a_400_and_nothing_is_done(self):
        did = []
        response = self.call(lambda *a, **k: did.append(1), key="bad key!!")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(did, [])

    def test_no_key_still_works_but_is_unprotected_by_default(self):
        seen = {}

        def fake(data, user_id, idem=None):
            seen["idem"] = idem
            return {"id": "BILL-1"}

        self.assertEqual(self.call(fake, key=None).status_code, 201)
        self.assertIsNone(seen["idem"])

    def test_required_mode_refuses_a_request_with_no_key(self):
        did = []
        response = self.call(lambda *a, **k: did.append(1), key=None, env={"ORION_IDEMPOTENCY_REQUIRED": "1"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("out of date", response.json()["detail"])
        self.assertEqual(did, [])

    def test_payments_and_edits_take_the_key_too(self):
        seen = {}

        def pay(bill_code, amount, received, user_id, idem=None, account_id=None, deductions=None):
            seen["pay"] = (bill_code, idem.operation)
            return {"id": bill_code}

        def edit(bill_code, data, reason, user_id, idem=None):
            seen["edit"] = (bill_code, idem.operation)
            return {"id": bill_code}

        self.assertEqual(self.call(pay, method="post", url="/api/billing/bills/BILL-1/payments", json={"amount": "100.00", "received_date": "2026-10-19"}).status_code, 200)
        self.assertEqual(self.call(edit, method="put", url="/api/billing/bills/BILL-1", json={**self.body, "reason": "typo"}).status_code, 200)
        self.assertEqual(seen, {"pay": ("BILL-1", "bill.payment"), "edit": ("BILL-1", "bill.update")})

    def test_a_payment_for_a_different_amount_has_a_different_fingerprint(self):
        prints = []

        def pay(bill_code, amount, received, user_id, idem=None, account_id=None, deductions=None):
            prints.append(idem.fingerprint)
            return {"id": bill_code}

        for amount in ("100.00", "100.00", "250.00"):
            self.call(pay, url="/api/billing/bills/BILL-1/payments", json={"amount": amount, "received_date": "2026-10-19"})
        self.assertEqual(prints[0], prints[1])
        self.assertNotEqual(prints[0], prints[2])

    def test_a_payment_into_a_different_account_has_a_different_fingerprint(self):
        prints = []

        def pay(bill_code, amount, received, user_id, idem=None, account_id=None, deductions=None):
            prints.append(idem.fingerprint)
            return {"id": bill_code}

        for account in (None, 2, 3):
            self.call(pay, url="/api/billing/bills/BILL-1/payments", json={"amount": "100.00", "received_date": "2026-10-19", "account_id": account})
        self.assertEqual(len({*prints}), 3)

    def test_a_payment_with_different_deductions_has_a_different_fingerprint(self):
        prints = []

        def pay(bill_code, amount, received, user_id, idem=None, account_id=None, deductions=None):
            prints.append((idem.fingerprint, deductions))
            return {"id": bill_code}

        tds = {"kind": "TDS", "amount": "200", "section": "194C"}
        for held in ([], [tds], [tds], [{**tds, "amount": "300"}]):
            self.call(pay, url="/api/billing/bills/BILL-1/payments", json={"amount": "100.00", "received_date": "2026-10-19", "deductions": held})
        self.assertEqual(len({fingerprint for fingerprint, _ in prints}), 3)
        self.assertEqual(prints[1][0], prints[2][0])
        self.assertEqual(prints[1][1][0]["section"], "194C")  # what the route passes on is what was sent


class TheBrowser(unittest.TestCase):
    """The frontend must send the key and must not let one click become two."""

    src = ROOT / "frontend" / "src"

    def test_the_api_functions_send_the_key_as_a_header(self):
        client = (self.src / "api" / "client.ts").read_text(encoding="utf-8")
        helper = (self.src / "api" / "idempotency.ts").read_text(encoding="utf-8")
        self.assertIn("'Idempotency-Key'", helper)  # the name the server reads
        for name in ("createBill", "updateBill", "recordBillPayment"):
            block = re.split(r"\r?\n\r?\n", client.split(f"{name}:", 1)[1], maxsplit=1)[0]  # up to the next blank line
            self.assertIn("key?: string", block, f"{name} must take a key")
            self.assertIn("idempotencyHeader(key)", block, f"{name} must send it")

    def test_a_call_that_passes_its_own_header_does_not_lose_content_type(self):
        """request() once spread the caller's options AFTER building the headers, which replaced them all."""
        client = (self.src / "api" / "client.ts").read_text(encoding="utf-8")
        request = client.split("async function request", 1)[1].split("if (!res.ok)", 1)[0]
        self.assertLess(request.index("...options"), request.index("'Content-Type'"), "the merged headers must come after ...options")

    def test_a_key_can_be_made_where_crypto_randomuuid_does_not_exist(self):
        """crypto.randomUUID only exists on https and localhost; the office LAN is plain http."""
        helper = (self.src / "api" / "idempotency.ts").read_text(encoding="utf-8")
        self.assertIn("getRandomValues", helper)
        self.assertIn("randomUUID", helper)

    def test_the_bill_editor_keeps_one_key_per_form_and_ignores_a_second_click(self):
        page = (self.src / "pages" / "utility" / "BillEditorPage.tsx").read_text(encoding="utf-8")
        self.assertIn("newIdempotencyKey()", page)
        self.assertRegex(page, r"if \(savingRef\.current\) return")  # a state flag is not set until the next render: two clicks get through it
        self.assertIn("idemKey.current", page)

    def test_the_payment_form_gets_a_new_key_each_time_it_opens_and_ignores_a_second_click(self):
        page = (self.src / "components" / "billing" / "BillPayments.tsx").read_text(encoding="utf-8")
        self.assertIn("newIdempotencyKey()", page)
        self.assertRegex(page, r"if \(busyRef\.current\) return")
        self.assertIn("idemKey.current", page)


@unittest.skipUnless(RUN, "set ORION_DB_TESTS=1 to run these against the development database")
class AgainstTheRealDatabase(unittest.TestCase):
    """Real bills, in financial year 2099 so they cannot touch the real numbering, and all removed afterwards."""

    PREFIX = "zz-idem-"

    @classmethod
    def setUpClass(cls):
        from app import entities
        from app.database import db_cursor

        entities.ensure_bill_table()
        with db_cursor() as cur:
            cur.execute("SELECT case_code FROM orion_ods.case WHERE client_code IS NOT NULL ORDER BY case_code LIMIT 1")
            row = cur.fetchone()
        if not row:
            raise unittest.SkipTest("the development database has no case with a client to bill")
        cls.case = row[0]
        cls.user = cls.make_user()

    @classmethod
    def make_user(cls):
        from app import auth
        from app.database import db_cursor

        with db_cursor(commit=True) as cur:
            cur.execute("DELETE FROM orion_ods.app_user WHERE username = 'zz_idem'")
        auth.create_user("zz_idem", "Idem", "a long private pass phrase 1", role="admin")
        return auth._fetch_user_by_username("zz_idem")["id"]

    @classmethod
    def tearDownClass(cls):
        cls.cleanup()

    @classmethod
    def cleanup(cls):
        from app.database import db_cursor

        with db_cursor(commit=True) as cur:
            cur.execute("SELECT bill_code FROM orion_ods.bill WHERE fy_start_year = 2099")
            codes = [row[0] for row in cur.fetchall()]
            if codes:
                cur.execute("DELETE FROM orion_ods.case_transaction WHERE bill_code = ANY(%s)", (codes,))
                cur.execute("DELETE FROM orion_ods.bill_version WHERE bill_code = ANY(%s)", (codes,))
                cur.execute("DELETE FROM orion_ods.bill WHERE bill_code = ANY(%s)", (codes,))
            cur.execute("DELETE FROM orion_ods.bill_counter WHERE fy_start_year = 2099")
            cur.execute("DELETE FROM orion_ods.idempotency_key WHERE idem_key LIKE %s", (cls.PREFIX + "%",))
            cur.execute("DELETE FROM orion_ods.app_user WHERE username = 'zz_idem'")

    def setUp(self):
        self.addCleanup(self.cleanup_bills)

    def cleanup_bills(self):
        from app.database import db_cursor

        with db_cursor(commit=True) as cur:
            cur.execute("SELECT bill_code FROM orion_ods.bill WHERE fy_start_year = 2099")
            codes = [row[0] for row in cur.fetchall()]
            if codes:
                cur.execute("DELETE FROM orion_ods.case_transaction WHERE bill_code = ANY(%s)", (codes,))
                cur.execute("DELETE FROM orion_ods.bill_version WHERE bill_code = ANY(%s)", (codes,))
                cur.execute("DELETE FROM orion_ods.bill WHERE bill_code = ANY(%s)", (codes,))
            cur.execute("DELETE FROM orion_ods.bill_counter WHERE fy_start_year = 2099")
            cur.execute("DELETE FROM orion_ods.idempotency_key WHERE idem_key LIKE %s", (self.PREFIX + "%",))

    def data(self, **changes):
        return {
            "bill_date": date(2099, 4, 15), "service_month": "2099-04", "case_code": self.case, "party_name": "Idempotency Test Ltd",
            "lines": [{"particulars": "Guard", "qty": 2, "rate": 1000}], **changes,
        }

    def idem(self, key, operation="bill.create", *parts):
        return Idempotency(self.user, self.PREFIX + key, operation, idempotency.fingerprint(operation, *parts))

    def count_bills(self):
        from app.database import db_cursor

        with db_cursor() as cur:
            cur.execute("SELECT count(*) FROM orion_ods.bill WHERE fy_start_year = 2099")
            return cur.fetchone()[0]

    def test_a_repeated_request_makes_one_bill_and_returns_the_same_one(self):
        first_idem, second_idem = self.idem("a1b2c3d4", "bill.create", "x"), self.idem("a1b2c3d4", "bill.create", "x")
        first = billing.create_bill(self.data(), self.user, first_idem)
        second = billing.create_bill(self.data(), self.user, second_idem)
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(first["bill_number"], second["bill_number"])
        self.assertFalse(first_idem.replayed)
        self.assertTrue(second_idem.replayed)
        self.assertEqual(self.count_bills(), 1)

    def test_without_a_key_it_still_makes_two_which_is_why_the_browser_sends_one(self):
        billing.create_bill(self.data(), self.user)
        billing.create_bill(self.data(), self.user)
        self.assertEqual(self.count_bills(), 2)

    def test_a_different_key_is_a_different_bill(self):
        billing.create_bill(self.data(), self.user, self.idem("k1k1k1k1", "bill.create", "a"))
        billing.create_bill(self.data(), self.user, self.idem("k2k2k2k2", "bill.create", "b"))
        self.assertEqual(self.count_bills(), 2)

    def test_the_same_key_for_something_else_is_refused_and_makes_nothing(self):
        billing.create_bill(self.data(), self.user, self.idem("c0nf11ct", "bill.create", "first"))
        with self.assertRaises(IdempotencyConflict):
            billing.create_bill(self.data(party_name="Changed"), self.user, self.idem("c0nf11ct", "bill.create", "changed"))
        self.assertEqual(self.count_bills(), 1)

    def test_a_failed_save_does_not_use_up_its_key(self):
        """Validation fails, the person fixes the form and saves again with the same key: that must work."""
        with self.assertRaises(billing.BillError):
            billing.create_bill(self.data(party_name=""), self.user, self.idem("retry-ok1", "bill.create", "p"))
        self.assertEqual(self.count_bills(), 0)
        saved = billing.create_bill(self.data(), self.user, self.idem("retry-ok1", "bill.create", "p"))
        self.assertEqual(self.count_bills(), 1)
        self.assertTrue(saved["id"])

    def test_a_failed_save_does_not_burn_a_bill_number_either(self):
        first = billing.create_bill(self.data(), self.user, self.idem("num-aaaa1", "bill.create", "1"))
        with self.assertRaises(billing.BillError):
            billing.create_bill(self.data(party_name=""), self.user, self.idem("num-bbbb2", "bill.create", "2"))
        third = billing.create_bill(self.data(), self.user, self.idem("num-cccc3", "bill.create", "3"))
        self.assertEqual(int(third["bill_number"].split("/")[-1]), int(first["bill_number"].split("/")[-1]) + 1)

    def test_five_requests_at_the_same_instant_make_exactly_one_bill(self):
        barrier, results, errors = threading.Barrier(5), [], []

        def go():
            try:
                barrier.wait()
                results.append(billing.create_bill(self.data(), self.user, self.idem("race-key01", "bill.create", "same")))
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=go) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(60)
        self.assertEqual(errors, [])
        self.assertEqual(self.count_bills(), 1)
        self.assertEqual(len({r["id"] for r in results}), 1)

    def test_a_repeated_partial_payment_is_recorded_once(self):
        bill = billing.create_bill(self.data(), self.user, self.idem("pay-bill-01", "bill.create", "p"))
        total = Decimal(str(bill["grand_total"]))
        part = (total / 4).quantize(Decimal("0.01"))
        key = ("pay-part-01", "bill.payment", bill["id"], str(part), "2099-04-20")
        for _ in range(3):  # a double-click, then a retry
            saved = billing.record_payment(bill["id"], part, date(2099, 4, 20), self.user, self.idem(*key))
        received = Decimal(str(saved["revenue"]["received"]))
        self.assertEqual(received, part, "three identical requests must record one payment")
        committed = [e for e in saved["revenue"]["entries"] if e["status"] == "Committed"]
        self.assertEqual(len(committed), 1)

    def test_a_second_real_payment_of_the_same_amount_is_not_mistaken_for_a_repeat(self):
        bill = billing.create_bill(self.data(), self.user, self.idem("pay-bill-02", "bill.create", "p"))
        part = (Decimal(str(bill["grand_total"])) / 4).quantize(Decimal("0.01"))
        billing.record_payment(bill["id"], part, date(2099, 4, 20), self.user, self.idem("pay-one-001", "bill.payment", bill["id"], str(part), "d"))
        saved = billing.record_payment(bill["id"], part, date(2099, 4, 20), self.user, self.idem("pay-two-002", "bill.payment", bill["id"], str(part), "d"))
        self.assertEqual(Decimal(str(saved["revenue"]["received"])), part * 2)

    def test_payments_name_their_account_and_the_bank_book_follows(self):
        from datetime import timedelta

        from app import bank
        from app.database import db_cursor

        with db_cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM orion_ods.bank_account")
            if cur.fetchone()[0]:
                self.skipTest("the development database already has a bank account; this test will not touch it")

        def wipe():
            with db_cursor(commit=True) as cur:
                cur.execute("UPDATE orion_ods.case_transaction SET account_id = NULL WHERE account_id IS NOT NULL")
                for table in ("bank_match", "bank_statement_line", "bank_statement_import", "bank_entry", "bank_audit", "bank_account"):
                    cur.execute(f"DELETE FROM orion_ods.{table}")

        self.addCleanup(wipe)
        today = date.today()
        first = bank.save_account({"account_name": "Current", "opening_balance": "0", "opening_date": today - timedelta(days=400)}, self.user)
        cash = bank.save_account({"account_name": "Cash", "account_kind": "cash", "opening_balance": "0", "opening_date": today - timedelta(days=400)}, self.user, create=True)

        bill = billing.create_bill(self.data(), self.user, self.idem("acc-bill-01", "bill.create", "a"))
        total = Decimal(str(bill["grand_total"]))
        part = (total / 4).quantize(Decimal("0.01"))
        with self.assertRaises(billing.BillError):  # an account that does not exist: nothing is recorded
            billing.record_payment(bill["id"], part, date(2099, 4, 20), self.user, self.idem("acc-pay-00", "bill.payment", bill["id"], "x"), account_id=999999)
        self.assertEqual(Decimal(str(billing.get_bill(bill["id"])["revenue"]["received"])), 0)
        billing.record_payment(bill["id"], part, date(2099, 4, 20), self.user, self.idem("acc-pay-01", "bill.payment", bill["id"], "1"), account_id=cash["account_id"])
        saved = billing.record_payment(bill["id"], total - part, date(2099, 4, 21), self.user, self.idem("acc-pay-02", "bill.payment", bill["id"], "2"), account_id=first["account_id"])
        self.assertEqual(Decimal(str(saved["revenue"]["received"])), total)

        # the bank book (read through the view, which has no "not in the future" limit) puts each receipt in the account it names
        with db_cursor() as cur:
            cur.execute("SELECT account_id, amount FROM orion_ods.bank_movement WHERE source = 'revenue' AND bill_code = %s ORDER BY move_date", (bill["id"],))
            found = cur.fetchall()
        self.assertEqual([a for a, _amount in found], [cash["account_id"], first["account_id"]])
        self.assertEqual(sum(Decimal(str(amount)) for _a, amount in found), total)

    def test_saving_an_edit_twice_answers_success_not_nothing_changed(self):
        bill = billing.create_bill(self.data(), self.user, self.idem("edit-bill-1", "bill.create", "e"))
        change = self.data(party_name="Renamed Ltd")
        first = billing.update_bill(bill["id"], change, "renamed", self.user, self.idem("edit-key-01", "bill.update", bill["id"], "r"))
        second = billing.update_bill(bill["id"], change, "renamed", self.user, self.idem("edit-key-01", "bill.update", bill["id"], "r"))
        self.assertEqual(first["party_name"], second["party_name"])
        self.assertEqual(second["version_no"], 2, "one new version, not two")
        with self.assertRaises(billing.BillError):  # without the key the second is the old, confusing refusal
            billing.update_bill(bill["id"], change, "renamed", self.user)

    def test_the_whole_thing_through_the_api(self):
        from app import sessions

        token = sessions.create_session(self.user, ip="127.0.0.9", user_agent="idem-test")
        client = TestClient(app)
        client.cookies.set("orion_session", token)
        body = {**self.data(), "bill_date": "2099-04-15"}
        headers = {"Idempotency-Key": self.PREFIX + "http-key-1"}
        first = client.post("/api/billing/bills", json=body, headers=headers)
        second = client.post("/api/billing/bills", json=body, headers=headers)
        self.assertEqual((first.status_code, second.status_code), (201, 201))
        self.assertEqual(first.json()["id"], second.json()["id"])
        self.assertNotIn("idempotent-replayed", first.headers)
        self.assertEqual(second.headers["idempotent-replayed"], "true")
        changed = client.post("/api/billing/bills", json={**body, "party_name": "Other"}, headers=headers)
        self.assertEqual(changed.status_code, 409)
        self.assertEqual(self.count_bills(), 1)


if __name__ == "__main__":
    unittest.main()
