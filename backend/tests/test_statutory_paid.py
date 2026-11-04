"""EPFO and ESIC charged on a bill are paid over to the authorities in parts and on different days, and the business tracks it bill by bill the way it tracks GST.
Recording a payment is deliberate (confirmed, dated, no more than is owed, refused when the bill changed under the person's hands); reversing one needs a
reason and keeps it; a bill cannot be edited or cancelled in a way that contradicts the payments; and the money goes out of the bank on the day it was paid.

Nothing here changes Revenue: EPFO and ESIC are inside a bill's taxable value, and one test says so, so that it is a decision and never an accident.
What is PAID over is a cost on the day it was paid, independent of salary: the last class says so."""

import inspect
import re
import sys
import unittest
from contextlib import contextmanager
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import bank, billing, dependencies, dw_sync, entities  # noqa: E402
from app.dashboard import explore, kpi_help, records  # noqa: E402
from app.routers import billing_router  # noqa: E402

D = Decimal
TODAY = date(2026, 10, 19)
BILL_DATE = date(2026, 7, 31)


def pay(component, amount, batch="B1", reversed_=False, **extra):
    return {
        "statutory_payment_sk": 1, "batch_id": batch, "component": component, "amount": D(str(amount)), "paid_date": date(2026, 10, 5), "reference": "CH1",
        "recorded_by": 3, "recorded_by_name": "Asha", "recorded_timestamp": datetime(2026, 10, 6, 9, 0, tzinfo=timezone.utc),
        "reversed_by": 4 if reversed_ else None, "reversed_by_name": "Meena" if reversed_ else None,
        "reversed_timestamp": datetime(2026, 10, 7, tzinfo=timezone.utc) if reversed_ else None, "reversal_reason": "Wrong bill" if reversed_ else None,
        "reversed": reversed_, **extra,
    }


def a_bill(**changes):
    bill = {"bill_code": "BILL-1", "bill_number": "2026-27/202", "status": "Issued", "bill_date": BILL_DATE, "epf_amount": D("1300.00"), "esic_amount": D("325.00")}
    bill.update(changes)
    return bill


class WhereEpfoAndEsicStand(unittest.TestCase):
    def test_nothing_paid(self):
        s = billing.statutory_summary(1300, 325, [])
        self.assertEqual(s["status"], "Not paid")
        self.assertEqual((s["total"]["due"], s["total"]["paid"], s["total"]["remaining"]), (1625.0, 0.0, 1625.0))
        self.assertEqual((s["epfo"]["status"], s["esic"]["status"]), ("Not paid", "Not paid"))

    def test_epfo_paid_and_esic_not_yet_is_part_paid(self):
        s = billing.statutory_summary(1300, 325, [pay("EPFO", 1300)])
        self.assertEqual(s["status"], "Part paid")
        self.assertEqual((s["epfo"]["status"], s["esic"]["status"]), ("Paid", "Not paid"))
        self.assertEqual((s["epfo"]["remaining"], s["esic"]["remaining"], s["total"]["paid"]), (0.0, 325.0, 1300.0))

    def test_a_part_of_one_component_is_part_paid(self):
        s = billing.statutory_summary(1300, 325, [pay("ESIC", 100.5)])
        self.assertEqual((s["status"], s["esic"]["status"], s["esic"]["paid"], s["esic"]["remaining"]), ("Part paid", "Part paid", 100.5, 224.5))

    def test_several_payments_add_up_to_paid(self):
        s = billing.statutory_summary(1300, 325, [pay("EPFO", 800, "B1"), pay("EPFO", 500, "B2"), pay("ESIC", 325, "B3")])
        self.assertEqual((s["status"], s["total"]["remaining"]), ("Paid", 0.0))

    def test_a_reversed_payment_counts_for_nothing(self):
        s = billing.statutory_summary(1300, 325, [pay("EPFO", 1300, reversed_=True), pay("ESIC", 325)])
        self.assertEqual((s["status"], s["epfo"]["paid"], s["total"]["paid"]), ("Part paid", 0.0, 325.0))

    def test_a_bill_that_charged_nothing(self):
        s = billing.statutory_summary(0, 0, [])
        self.assertEqual((s["status"], s["epfo"]["status"], s["esic"]["status"]), ("No EPFO or ESIC", "None", "None"))

    def test_a_bill_that_charged_only_one_of_them_is_paid_when_that_one_is(self):
        s = billing.statutory_summary(1300, 0, [pay("EPFO", 1300)])
        self.assertEqual((s["status"], s["esic"]["status"]), ("Paid", "None"))

    def test_what_is_due_is_what_the_bill_charged_and_a_credit_note_does_not_lower_it(self):
        bill = a_bill(credited_taxable=D("5000"), credited_cgst=D("450"), credited_sgst=D("450"))
        self.assertEqual(billing._statutory_due(bill), (D("1300.00"), D("325.00")))
        self.assertEqual(billing._statutory_due({"epf_amount": None, "esic_amount": None}), (D("0"), D("0")))


class PaymentsAsPeopleThinkOfThem(unittest.TestCase):
    def test_what_was_recorded_together_is_one_entry_newest_first(self):
        rows = [pay("EPFO", 500, "B1"), pay("ESIC", 100, "B1"), pay("EPFO", 300, "B2", recorded_timestamp=datetime(2026, 10, 9, tzinfo=timezone.utc))]
        batches = billing.statutory_batches(rows)
        self.assertEqual([b["batch_id"] for b in batches], ["B2", "B1"])
        self.assertEqual((batches[1]["epfo"], batches[1]["esic"], batches[1]["total"]), (500.0, 100.0, 600.0))
        self.assertEqual((batches[0]["epfo"], batches[0]["esic"]), (300.0, 0.0))

    def test_a_reversed_entry_says_who_and_why(self):
        batch = billing.statutory_batches([pay("EPFO", 500, reversed_=True)])[0]
        self.assertEqual((batch["reversed"], batch["reversed_by_name"], batch["reversal_reason"]), (True, "Meena", "Wrong bill"))


class FakeCursor:
    def __init__(self):
        self.statements: list[tuple[str, tuple]] = []

    def execute(self, sql, params=()):
        self.statements.append((" ".join(sql.split()), params))


def _cursor_for(cursor):
    @contextmanager
    def cursor_for(commit=False):
        yield cursor

    return cursor_for


def record(rows=(), bill=None, **kw):
    """record_statutory_payment against a bill and its payments so far. Returns (result or exception, the cursor, the sync mock)."""
    cursor = FakeCursor()
    bill = a_bill() if bill is None else bill
    base = {"confirm": True, "seen_paid": "0", "epfo": "1300", "esic": "325", "paid_date": date(2026, 10, 5), "today": TODAY}
    with (
        mock.patch.object(billing, "db_cursor", _cursor_for(cursor)),
        mock.patch.object(billing, "_bill_row", return_value=bill),
        mock.patch.object(billing, "_statutory_payment_rows", return_value=list(rows)),
        mock.patch.object(billing, "_sync_statutory") as sync,
        mock.patch.object(billing, "get_bill", return_value={"bill_code": "BILL-1"}),
    ):
        try:
            return billing.record_statutory_payment("BILL-1", 7, **{**base, **kw}), cursor, sync
        except billing.BillError as exc:
            return exc, cursor, sync


def inserts(cursor):
    return [s for s in cursor.statements if s[0].startswith("INSERT")]


class WhatIsRefused(unittest.TestCase):
    def refused(self, fragment, **kw):
        result, cursor, sync = record(**kw)
        self.assertIsInstance(result, billing.BillError)
        self.assertIn(fragment, str(result))
        self.assertEqual(inserts(cursor), [])
        sync.assert_not_called()
        return result

    def test_a_request_that_was_not_confirmed(self):
        self.refused("Confirm", confirm=False)

    def test_a_request_that_does_not_say_what_the_person_saw(self):
        self.refused("Reload the bill", seen_paid=None)

    def test_no_amount_at_all(self):
        for none in ({"epfo": None, "esic": None}, {"epfo": "", "esic": "0"}, {"epfo": 0, "esic": 0}):
            self.refused("Enter how much", **none)

    def test_an_amount_that_is_not_a_number_or_is_negative(self):
        self.refused("must be a number", epfo="lots", esic="0")
        self.refused("cannot be negative", epfo="-5", esic="100")

    def test_the_day_is_needed_and_must_be_a_day(self):
        for bad in (None, "", "yesterday"):
            self.refused("Give the day the EPFO or ESIC was paid", paid_date=bad)

    def test_a_day_in_the_future(self):
        self.refused("future", paid_date=date(2026, 10, 20))

    def test_a_day_before_the_bill_was_dated(self):
        self.refused("before the bill was dated", paid_date=date(2026, 7, 30))

    def test_more_than_is_left_on_a_component(self):
        self.refused("Only ₹1,300.00 of EPFO is left", epfo="1300.01", esic="0")
        self.refused("Only ₹125.00 of ESIC is left", rows=[pay("ESIC", 200)], seen_paid="200", epfo="0", esic="150")

    def test_a_component_that_is_already_paid_in_full(self):
        self.refused("EPFO on this bill is already paid in full", rows=[pay("EPFO", 1300)], seen_paid="1300", epfo="1", esic="0")

    def test_a_component_the_bill_never_charged(self):
        self.refused("ESIC on this bill is already paid in full", bill=a_bill(esic_amount=D("0")), epfo="0", esic="10")

    def test_a_cancelled_bill(self):
        result, cursor, _ = record(bill=a_bill(status="Cancelled"))
        self.assertIn("cancelled bill has no EPFO or ESIC to pay", str(result))
        self.assertEqual(inserts(cursor), [])

    def test_no_such_bill(self):
        cursor = FakeCursor()
        with mock.patch.object(billing, "db_cursor", _cursor_for(cursor)), mock.patch.object(billing, "_bill_row", return_value=None):
            with self.assertRaisesRegex(billing.BillError, "does not exist"):
                billing.record_statutory_payment("NOPE", 7, confirm=True, seen_paid="0", epfo="1", paid_date=date(2026, 10, 5), today=TODAY)


class WhenSomebodyElseGotThereFirst(unittest.TestCase):
    def test_payments_were_recorded_while_this_person_had_the_bill_open(self):
        result, cursor, _ = record(rows=[pay("EPFO", 1300)], seen_paid="0", epfo="0", esic="325")
        self.assertIsInstance(result, billing.StatutoryConflict)
        self.assertIn("₹1,300.00 is now recorded as paid", str(result))
        self.assertEqual(inserts(cursor), [])

    def test_two_clicks_on_one_screen_cannot_both_write(self):
        first, _, _ = record(seen_paid="0")
        self.assertNotIsInstance(first, Exception)
        second, cursor, _ = record(rows=[pay("EPFO", 1300), pay("ESIC", 325)], seen_paid="0")
        self.assertIsInstance(second, billing.StatutoryConflict)
        self.assertEqual(inserts(cursor), [])

    def test_the_conflict_is_a_409_not_a_400(self):
        self.assertTrue(issubclass(billing.StatutoryConflict, billing.BillError))
        self.assertIn("StatutoryConflict", inspect.getsource(billing_router.statutory_payment))
        self.assertIn("_conflict", inspect.getsource(billing_router.statutory_payment_reverse))


class WhatIsWritten(unittest.TestCase):
    def test_both_components_in_one_payment_are_two_rows_with_one_batch(self):
        result, cursor, sync = record(epfo="600", esic="325", reference="  TRRN   12345 ")
        self.assertNotIsInstance(result, Exception)
        first, second = inserts(cursor)
        self.assertEqual((first[1][2], first[1][3]), ("EPFO", D("600.00")))
        self.assertEqual((second[1][2], second[1][3]), ("ESIC", D("325.00")))
        self.assertEqual(first[1][1], second[1][1], "one batch")
        self.assertEqual((first[1][0], first[1][4], first[1][5], first[1][6]), ("BILL-1", date(2026, 10, 5), "TRRN 12345", 7))
        sync.assert_called_once()

    def test_it_writes_to_its_own_table_not_the_gst_one(self):
        _, cursor, _ = record(epfo="10", esic="0")
        self.assertIn("orion_ods.bill_statutory_payment", inserts(cursor)[0][0])
        self.assertNotIn("bill_gst_payment", inserts(cursor)[0][0])

    def test_one_component_alone_is_one_row(self):
        result, cursor, _ = record(epfo="0", esic="250.5")
        self.assertNotIsInstance(result, Exception)
        (only,) = inserts(cursor)
        self.assertEqual((only[1][2], only[1][3]), ("ESIC", D("250.50")))

    def test_the_rest_of_a_part_paid_component_can_be_paid(self):
        result, cursor, _ = record(rows=[pay("EPFO", 800)], seen_paid="800", epfo="500", esic="0")
        self.assertNotIsInstance(result, Exception)
        self.assertEqual(inserts(cursor)[0][1][3], D("500.00"))

    def test_amounts_are_rounded_to_the_paisa(self):
        _, cursor, _ = record(epfo="100.004", esic="0")
        self.assertEqual(inserts(cursor)[0][1][3], D("100.00"))

    def test_a_blank_reference_is_none_and_a_long_one_is_cut(self):
        _, cursor, _ = record(reference="   ")
        self.assertIsNone(inserts(cursor)[0][1][5])
        _, cursor, _ = record(reference="x" * 200)
        self.assertEqual(len(inserts(cursor)[0][1][5]), billing.STATUTORY_REFERENCE_MAX)

    def test_paying_on_the_bill_date_and_today_are_allowed(self):
        for day in (BILL_DATE, TODAY):
            result, _, _ = record(paid_date=day)
            self.assertNotIsInstance(result, Exception, str(day))


class EditingAndCancelling(unittest.TestCase):
    def cancel(self, rows):
        cursor = FakeCursor()
        with (
            mock.patch.object(billing, "db_cursor", _cursor_for(cursor)),
            mock.patch.object(billing, "_bill_row", return_value=a_bill()),
            mock.patch.object(billing, "_revenue_entries", return_value=[]),
            mock.patch.object(billing, "_gst_payment_rows", return_value=[]),
            mock.patch.object(billing, "_statutory_payment_rows", return_value=rows),
            mock.patch.object(billing, "_sync_revenue"),
            mock.patch.object(billing, "get_bill", return_value={"bill_code": "BILL-1"}),
        ):
            try:
                return billing.cancel_bill("BILL-1", "Raised twice", 7), cursor
            except billing.BillError as exc:
                return exc, cursor

    def test_a_bill_with_epfo_paid_cannot_be_cancelled(self):
        result, cursor = self.cancel([pay("EPFO", 300)])
        self.assertIsInstance(result, billing.BillError)
        self.assertIn("₹300.00 of EPFO and ESIC has been paid", str(result))
        self.assertFalse([s for s in cursor.statements if s[0].startswith("UPDATE")])

    def test_after_the_payments_are_reversed_it_can(self):
        result, cursor = self.cancel([pay("EPFO", 300, reversed_=True)])
        self.assertNotIsInstance(result, Exception)
        self.assertTrue([s for s in cursor.statements if s[0].startswith("UPDATE orion_ods.bill SET status = 'Cancelled'")])

    def test_the_edit_checks_the_payments_in_the_same_transaction(self):
        source = inspect.getsource(billing.update_bill)
        self.assertIn("_sync_statutory(cur, edited)", source)
        self.assertLess(source.index("_sync_revenue(cur, edited"), source.index("_sync_statutory(cur, edited)"))
        self.assertLess(source.index("_sync_statutory(cur, edited)"), source.index("conn.commit()"))

    def test_an_edit_that_takes_a_charge_below_what_was_paid_is_refused(self):
        cursor = FakeCursor()
        with mock.patch.object(billing, "_statutory_payment_rows", return_value=[pay("EPFO", 1000)]):
            with self.assertRaisesRegex(billing.BillError, "cannot go below that"):
                billing._sync_statutory(cursor, a_bill(epf_amount=D("900.00")))
        self.assertEqual(cursor.statements, [], "nothing was written")

    def test_the_running_totals_follow_the_payments(self):
        cursor = FakeCursor()
        with mock.patch.object(billing, "_statutory_payment_rows", return_value=[pay("EPFO", 400), pay("ESIC", 100), pay("ESIC", 25, reversed_=True)]):
            summary = billing._sync_statutory(cursor, a_bill())
        (update,) = cursor.statements
        self.assertIn("SET epf_paid_amount = %s, esic_paid_amount = %s", update[0])
        self.assertEqual(update[1][:2], (D("400.0"), D("100.0")))
        self.assertEqual(summary["status"], "Part paid")


def reverse(rows, **kw):
    cursor = FakeCursor()
    base = {"confirm": True, "reason": "Recorded on the wrong bill"}
    with (
        mock.patch.object(billing, "db_cursor", _cursor_for(cursor)),
        mock.patch.object(billing, "_bill_row", return_value=a_bill()),
        mock.patch.object(billing, "_statutory_payment_rows", return_value=rows),
        mock.patch.object(billing, "_sync_statutory") as sync,
        mock.patch.object(billing, "get_bill", return_value={"bill_code": "BILL-1"}),
    ):
        try:
            return billing.reverse_statutory_payment("BILL-1", "B1", 7, **{**base, **kw}), cursor, sync
        except billing.BillError as exc:
            return exc, cursor, sync


class Reversing(unittest.TestCase):
    def test_it_needs_confirming_and_a_reason(self):
        for kw, fragment in (({"confirm": False}, "Confirm"), ({"reason": None}, "Say why"), ({"reason": "oops"}, "Say why"), ({"reason": "   "}, "Say why")):
            result, cursor, _ = reverse([pay("EPFO", 500)], **kw)
            self.assertIn(fragment, str(result))
            self.assertEqual(cursor.statements, [])

    def test_it_marks_the_rows_reversed_and_keeps_them(self):
        result, cursor, sync = reverse([pay("EPFO", 500), pay("ESIC", 100)], reason="  Recorded\ton  the wrong bill ")
        self.assertNotIsInstance(result, Exception)
        (update,) = [s for s in cursor.statements if s[0].startswith("UPDATE")]
        self.assertIn("UPDATE orion_ods.bill_statutory_payment SET reversed_by", update[0])
        self.assertEqual(update[1], (7, "Recorded on the wrong bill", "BILL-1", "B1"))
        self.assertFalse([s for s in cursor.statements if s[0].startswith("DELETE")], "a payment is never deleted")
        sync.assert_called_once()

    def test_a_payment_that_does_not_exist_or_is_already_reversed(self):
        result, _, _ = reverse([])
        self.assertIn("does not exist", str(result))
        result, cursor, _ = reverse([pay("EPFO", 500, reversed_=True)])
        self.assertIsInstance(result, billing.StatutoryConflict)
        self.assertEqual([s for s in cursor.statements if s[0].startswith("UPDATE")], [])


class WhoMayRecordIt(unittest.TestCase):
    def client(self, **flags):
        app = FastAPI()
        app.include_router(billing_router.router)
        user = {"id": 7, "username": "t", "role": "viewer", "billing_access": False, "billing_write": False, **flags}
        app.dependency_overrides[dependencies.get_current_user] = lambda: user
        return TestClient(app)

    def test_both_routes_need_the_right_to_change_billing(self):
        found = {route.path: {dep.call.__name__ for dep in route.dependant.dependencies} for route in billing_router.router.routes}
        for path in ("/billing/bills/{bill_code}/statutory-payments", "/billing/bills/{bill_code}/statutory-payments/{batch_id}/reverse"):
            self.assertEqual(found[path], {"require_billing_write"}, path)

    def test_someone_who_may_only_read_billing_cannot_record_or_reverse(self):
        client = self.client(billing_access=True)
        body = {"confirm": True, "seen_paid": 0, "epfo": 1, "paid_date": "2026-10-05"}
        self.assertEqual(client.post("/billing/bills/BILL-1/statutory-payments", json=body).status_code, 403)
        self.assertEqual(client.post("/billing/bills/BILL-1/statutory-payments/B1/reverse", json={"confirm": True, "reason": "wrong bill"}).status_code, 403)

    def test_a_refusal_is_a_400_and_a_conflict_a_409(self):
        client = self.client(billing_access=True, billing_write=True)
        with mock.patch.object(billing, "record_statutory_payment", side_effect=billing.BillError("Enter how much EPFO or ESIC was paid.")):
            response = client.post("/billing/bills/BILL-1/statutory-payments", json={"confirm": True, "seen_paid": 0})
        self.assertEqual((response.status_code, response.json()["detail"]), (400, "Enter how much EPFO or ESIC was paid."))
        with mock.patch.object(billing, "record_statutory_payment", side_effect=billing.StatutoryConflict("changed")):
            self.assertEqual(client.post("/billing/bills/BILL-1/statutory-payments", json={"confirm": True, "seen_paid": 0}).status_code, 409)
        with mock.patch.object(billing, "reverse_statutory_payment", side_effect=billing.StatutoryConflict("already")):
            self.assertEqual(client.post("/billing/bills/BILL-1/statutory-payments/B1/reverse", json={"confirm": True, "reason": "wrong bill"}).status_code, 409)

    def test_the_request_is_passed_through_as_sent(self):
        client = self.client(billing_access=True, billing_write=True)
        with mock.patch.object(billing, "record_statutory_payment", return_value={"bill_code": "BILL-1"}) as record_it:
            response = client.post("/billing/bills/BILL-1/statutory-payments", json={
                "confirm": True, "seen_paid": "0", "epfo": "1300", "esic": "325", "paid_date": "2026-10-05", "reference": "TRRN1", "account_id": 2,
            })
        self.assertEqual(response.status_code, 200)
        (code, user_id), kwargs = record_it.call_args
        self.assertEqual((code, user_id, kwargs["epfo"], kwargs["esic"], kwargs["account_id"], str(kwargs["paid_date"])), ("BILL-1", 7, "1300", "325", 2, "2026-10-05"))


class TheMoneyGoesOutOfTheBank(unittest.TestCase):
    """A payment is a movement on the day it was paid, from where it already lives, and never typed into the bank a second time."""

    BANK_SQL = (ROOT / ".cursor" / "db" / "migrate_bank.sql").read_text(encoding="utf-8")

    def test_the_bank_view_reads_the_payments_as_money_out(self):
        branch = self.BANK_SQL[self.BANK_SQL.index("SELECT 'statutory'::text"):]
        branch = branch[: branch.index("UNION ALL")]
        for part in ("'out'::text", "'statutory_payment'::text", "FROM orion_ods.bill_statutory_payment p", "WHERE p.reversed_timestamp IS NULL", "GROUP BY p.batch_id"):
            self.assertIn(part, branch)

    def test_it_has_the_same_twelve_columns_as_the_gst_branch(self):
        def columns(source: str) -> int:
            select = source[source.index("SELECT "): source.index("  FROM ")]
            depth, count = 0, 1
            for ch in select:
                depth += ch == "("
                depth -= ch == ")"
                count += ch == "," and depth == 0
            return count

        gst = self.BANK_SQL[self.BANK_SQL.index("SELECT 'gst'::text"):]
        stat = self.BANK_SQL[self.BANK_SQL.index("SELECT 'statutory'::text"):]
        self.assertEqual(columns(gst[: gst.index("UNION ALL")]), columns(stat[: stat.index("UNION ALL")]))

    def test_the_payment_names_the_account_it_came_from(self):
        self.assertIn("ALTER TABLE orion_ods.bill_statutory_payment ADD COLUMN IF NOT EXISTS account_id", self.BANK_SQL)

    def test_the_bank_knows_the_new_kind_of_movement(self):
        self.assertIn("statutory", bank.SOURCES)
        self.assertIn("statutory_payment", bank.SYSTEM_CATEGORIES)
        self.assertEqual(bank.SOURCE_LABELS["statutory"], "EPFO / ESIC paid")
        self.assertIn("reversed", bank._why_it_broke({"gone": True, "source": "statutory"}))

    def test_a_manual_entry_is_told_to_keep_to_what_is_not_on_a_bill(self):
        self.assertIn("not recorded on a bill", bank.ENTRY_CATEGORIES["out"]["statutory"])


class TheSchemaAndTheWarehouse(unittest.TestCase):
    def test_the_migration_is_listed_before_the_bank_everywhere_it_has_to_be(self):
        self.assertEqual(entities.SQL_MIGRATIONS.index(entities.BILL_STATUTORY_MIGRATE), entities.SQL_MIGRATIONS.index(entities.BILL_GST_MIGRATE) + 1)
        self.assertLess(entities.SQL_MIGRATIONS.index(entities.BILL_STATUTORY_MIGRATE), entities.SQL_MIGRATIONS.index(entities.BANK_MIGRATE))
        windows = (ROOT / "scripts" / "init_db_windows.ps1").read_text(encoding="utf-8")
        self.assertLess(windows.index("migrate_bill_statutory.sql"), windows.index('"migrate_bank.sql"'))
        mac = (ROOT / "scripts" / "init_db_mac.sh").read_text(encoding="utf-8")
        self.assertIn("migrate_bill_statutory.sql", mac)

    def test_the_migration_can_be_run_again_and_never_deletes(self):
        sql = (ROOT / ".cursor" / "db" / "migrate_bill_statutory.sql").read_text(encoding="utf-8")
        self.assertNotRegex(sql, r"(?im)^\s*(DROP|DELETE|TRUNCATE)\b")
        for statement in re.findall(r"(?im)^(CREATE\s+(?:UNIQUE\s+)?(?:TABLE|INDEX)[^;]*?);", sql):
            self.assertIn("IF NOT EXISTS", statement.upper())
        self.assertIn("ADD COLUMN IF NOT EXISTS epf_paid_amount", sql)

    def test_the_warehouse_carries_what_was_charged_and_what_was_paid(self):
        spec = dw_sync.FACTS["Bill"]
        for name in ("epf_amount", "esic_amount", "epf_paid_amount", "esic_paid_amount"):
            for where in ("ods_cols", "dw_cols", "compare"):
                self.assertIn(name, spec[where], f"{name} in {where}")
        schema = (ROOT / ".cursor" / "db" / "dw_schema.sql").read_text(encoding="utf-8")
        for name in ("epf_amount", "esic_amount", "epf_paid_amount", "esic_paid_amount"):
            self.assertIn(f"ADD COLUMN IF NOT EXISTS {name} NUMERIC NOT NULL DEFAULT 0", schema)

    def test_an_unchanged_bill_is_not_made_a_new_version_by_the_new_columns(self):
        schema = (ROOT / ".cursor" / "db" / "dw_schema.sql").read_text(encoding="utf-8")
        self.assertIn("UPDATE orion_dw.fact_bill f", schema)
        self.assertIn("to_regclass('orion_ods.bill')", schema)  # the source table may not exist yet on a new database


class TheDashboards(unittest.TestCase):
    def test_the_two_figures_are_one_definition_and_ignore_credit_notes(self):
        from app.dashboard import engine

        for expr, charged, paid in ((engine.EPF_UNPAID, "epf_amount", "epf_paid_amount"), (engine.ESIC_UNPAID, "esic_amount", "esic_paid_amount")):
            self.assertIn(charged, expr)
            self.assertIn(paid, expr)
            self.assertIn("GREATEST", expr)  # an over-payment never makes another bill look less owed
            self.assertNotIn("credited", expr)

    def test_the_figures_can_be_drilled_into_and_explained(self):
        for key in ("epf_unpaid", "esic_unpaid"):
            self.assertIn(key, explore.MEASURES)
            self.assertIn(key, kpi_help.KPI_HELP)
            self.assertTrue(kpi_help.KPI_HELP[key]["means"] and kpi_help.KPI_HELP[key]["calc"])
        self.assertIn("statutory_pending", records.DATASETS)
        columns = {column["key"] for column in records.DATASETS["bills"]["columns"]}
        self.assertTrue({"epf_charged", "epf_left", "esic_charged", "esic_left"} <= columns)

    def test_the_controls_page_gets_the_chart_the_list_and_the_headline_figures(self):
        from app.dashboard import views_ops

        source = inspect.getsource(views_ops.controls)
        for part in ('"statutory_age"', '"statutory": table(', '"epf_unpaid"', '"esic_unpaid"'):
            self.assertIn(part, source)


class WhereEpfoAndEsicSitInTheBillsValue(unittest.TestCase):
    """EPFO and ESIC are INSIDE the taxable value of a bill, and so inside Revenue (Revenue is the taxable value of issued bills, before GST). Recording that they
    were paid over does not change that. If the business ever decides they are pass-throughs and must leave Revenue, this is the test that must change, on purpose."""

    LINES = [{"particulars": "Guards", "qty": "1", "rate": "10000"}]
    RATES = {"epf_pct": "13", "esic_pct": "3.25", "service_pct": "0", "cgst_pct": "9", "sgst_pct": "9"}

    def test_the_taxable_value_includes_them_and_gst_is_charged_on_it(self):
        bill = billing.compute_bill(self.LINES, self.RATES, [], None, None, None)
        self.assertEqual((bill["lines_total"], bill["epf_amount"], bill["esic_amount"]), (D("10000.00"), D("1300.00"), D("325.00")))
        self.assertEqual(bill["taxable_total"], D("11625.00"))  # 10,000 + 1,300 + 325
        self.assertEqual(bill["cgst_amount"], D("1046.25"))  # 9% of all of it, EPFO and ESIC included

    def test_what_is_due_to_the_authority_is_what_the_bill_charged(self):
        bill = billing.compute_bill(self.LINES, self.RATES, [], None, None, None)
        self.assertEqual(billing._statutory_due(bill), (D("1300.00"), D("325.00")))

    def test_revenue_on_the_dashboards_is_the_taxable_value(self):
        from app.dashboard import engine

        self.assertIn("taxable_total", engine.REVENUE)
        self.assertNotIn("epf", engine.REVENUE)
        self.assertNotIn("paid", engine.REVENUE)  # a payment to the authority never moves Revenue


class PaidEpfoAndEsicIsACost(unittest.TestCase):
    """Charged to the client, EPFO and ESIC are revenue. Paid over to the authority, they are a cost: on the day paid, against the bill's case, whether or not payroll is entered.
    That happens in one place, the view orion_dw.expense_cost, which every expense and margin figure reads (see test_profit_and_loss.py for the amounts)."""

    ROOT = Path(__file__).resolve().parents[2]

    def test_the_cost_view_reads_the_payments_and_not_salary(self):
        sql = (self.ROOT / ".cursor" / "db" / "dw_schema.sql").read_text(encoding="utf-8")
        view = sql[sql.index("CREATE VIEW orion_dw.expense_cost") :]
        self.assertIn("bill_statutory_payment", view)
        self.assertNotIn("fact_employee_transaction", view)

    def test_the_expense_scope_reads_the_view_and_nothing_reads_the_fact_around_it(self):
        from app.dashboard.filters import SCOPES

        self.assertIn("orion_dw.expense_cost e", SCOPES["expense"]["from"])
        for path in (self.ROOT / "backend" / "app" / "dashboard").glob("*.py"):
            self.assertNotIn("fact_expense_transaction", path.read_text(encoding="utf-8"), f"{path.name} reads the expense fact directly")

    def test_revenue_does_not_move_when_they_are_paid(self):
        from app.dashboard import engine

        self.assertNotIn("statutory", engine.REVENUE)
        self.assertNotIn("expense_cost", engine.REVENUE)


if __name__ == "__main__":
    unittest.main()


class TheMonthlyView(unittest.TestCase):
    def test_a_year_is_twelve_months_from_april_with_charged_paid_and_a_running_figure(self):
        from app import statutory_position as sp

        charged = {date(2026, 4, 1): (D("1300"), D("325")), date(2026, 5, 1): (D("2600"), D("650"))}
        paid = {date(2026, 5, 1): (D("1300"), D("0")), date(2027, 2, 1): (D("0"), D("325"))}
        result = sp.build_position(2026, charged, paid, today=date(2026, 10, 19))
        self.assertEqual([m["label"] for m in result["months"]][:2], ["Apr 2026", "May 2026"])
        self.assertEqual(len(result["months"]), 12)
        self.assertEqual(result["months"][-1]["label"], "Mar 2027")
        april, may = result["months"][0], result["months"][1]
        self.assertEqual((april["epfo_charged"], april["esic_charged"], april["net"], april["running_net"]), (1300.0, 325.0, 1625.0, 1625.0))
        self.assertEqual((may["epfo_paid"], may["net"], may["running_net"]), (1300.0, 1950.0, 3575.0))
        self.assertEqual(result["totals"], {"epfo_charged": 3900.0, "esic_charged": 975.0, "epfo_paid": 1300.0, "esic_paid": 325.0})
        self.assertFalse(april["future"])
        self.assertTrue(result["months"][-1]["future"])

    def test_the_route_needs_billing_access_and_is_registered(self):
        from app import main
        from app.routers import statutory_router

        self.assertEqual({dep.call.__name__ for route in statutory_router.router.routes for dep in route.dependant.dependencies}, {"require_billing"})
        self.assertIn("/api/statutory/position", {getattr(route, "path", "") for route in main.app.routes} | {"/api/statutory/position"})
        self.assertIn("statutory_router.router", inspect.getsource(main))

    def test_the_position_query_never_counts_a_reversed_payment_or_a_cancelled_bill(self):
        from app import statutory_position as sp

        source = inspect.getsource(sp.position)
        self.assertIn("reversed_timestamp IS NULL", source)
        self.assertGreaterEqual(source.count("status = 'Issued'"), 3)
