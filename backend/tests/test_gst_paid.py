"""The GST on a bill is paid to the government in instalments (CGST and SGST on different days, a part now and the rest later). Recording a payment is
deliberate: confirmed, dated, no more than is owed, refused when the bill has changed under the person's hands; reversing one needs a reason and
keeps it in the history; and a bill cannot be edited or cancelled in a way that contradicts the payments."""

import os
import sys
import unittest
from contextlib import contextmanager
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from app import billing  # noqa: E402
from app.dependencies import get_current_user  # noqa: E402
from app.main import app  # noqa: E402

D = Decimal
TODAY = date(2026, 10, 19)
BILL_DATE = date(2026, 7, 31)


def pay(component, amount, batch="B1", reversed_=False, **extra):
    return {
        "gst_payment_sk": 1, "batch_id": batch, "component": component, "amount": D(str(amount)), "paid_date": date(2026, 10, 5), "reference": "CH1",
        "recorded_by": 3, "recorded_by_name": "Asha", "recorded_timestamp": datetime(2026, 10, 6, 9, 0, tzinfo=timezone.utc),
        "reversed_by": 4 if reversed_ else None, "reversed_by_name": "Meena" if reversed_ else None,
        "reversed_timestamp": datetime(2026, 10, 7, tzinfo=timezone.utc) if reversed_ else None, "reversal_reason": "Wrong bill" if reversed_ else None,
        "reversed": reversed_, **extra,
    }


def a_bill(**changes):
    bill = {"bill_code": "BILL-1", "bill_number": "2026-27/202", "status": "Issued", "bill_date": BILL_DATE, "cgst_amount": D("1000.00"), "sgst_amount": D("1000.00")}
    bill.update(changes)
    return bill


class WhereTheGstStands(unittest.TestCase):
    def test_nothing_paid(self):
        s = billing.gst_summary(1000, 1000, [])
        self.assertEqual(s["status"], "Not paid")
        self.assertEqual((s["total"]["due"], s["total"]["paid"], s["total"]["remaining"]), (2000.0, 0.0, 2000.0))

    def test_cgst_paid_and_sgst_not_yet_is_part_paid(self):
        s = billing.gst_summary(1000, 1000, [pay("CGST", 1000)])
        self.assertEqual(s["status"], "Part paid")
        self.assertEqual((s["cgst"]["remaining"], s["sgst"]["remaining"], s["total"]["paid"]), (0.0, 1000.0, 1000.0))

    def test_a_part_of_one_component_is_part_paid(self):
        s = billing.gst_summary(1000, 1000, [pay("SGST", 400.5)])
        self.assertEqual((s["status"], s["sgst"]["paid"], s["sgst"]["remaining"]), ("Part paid", 400.5, 599.5))

    def test_several_payments_add_up_to_paid(self):
        s = billing.gst_summary(1000, 1000, [pay("CGST", 600, "B1"), pay("CGST", 400, "B2"), pay("SGST", 1000, "B3")])
        self.assertEqual((s["status"], s["total"]["remaining"]), ("Paid", 0.0))

    def test_a_reversed_payment_counts_for_nothing(self):
        s = billing.gst_summary(1000, 1000, [pay("CGST", 1000, reversed_=True), pay("SGST", 1000)])
        self.assertEqual((s["status"], s["cgst"]["paid"], s["total"]["paid"]), ("Part paid", 0.0, 1000.0))

    def test_a_bill_with_no_gst(self):
        self.assertEqual(billing.gst_summary(0, 0, [])["status"], "No GST")

    def test_the_two_components_can_differ(self):
        s = billing.gst_summary("1000.50", "1000.00", [pay("CGST", "1000.50")])
        self.assertEqual((s["cgst"]["remaining"], s["sgst"]["remaining"]), (0.0, 1000.0))


class PaymentsAsPeopleThinkOfThem(unittest.TestCase):
    def test_what_was_recorded_together_is_one_entry_newest_first(self):
        rows = [
            pay("CGST", 500, "B1"), pay("SGST", 500, "B1"),
            pay("CGST", 300, "B2", recorded_timestamp=datetime(2026, 10, 9, tzinfo=timezone.utc)),
        ]
        batches = billing.gst_batches(rows)
        self.assertEqual([b["batch_id"] for b in batches], ["B2", "B1"])
        self.assertEqual((batches[1]["cgst"], batches[1]["sgst"], batches[1]["total"]), (500.0, 500.0, 1000.0))
        self.assertEqual((batches[0]["cgst"], batches[0]["sgst"]), (300.0, 0.0))

    def test_a_reversed_entry_says_who_and_why(self):
        batch = billing.gst_batches([pay("CGST", 500, reversed_=True)])[0]
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
    """record_gst_payment against a bill and its payments so far. Returns (result or exception, the cursor, the sync mock)."""
    cursor = FakeCursor()
    bill = a_bill() if bill is None else bill
    base = {"confirm": True, "seen_paid": "0", "cgst": "1000", "sgst": "1000", "paid_date": date(2026, 10, 5), "today": TODAY}
    with (
        mock.patch.object(billing, "db_cursor", _cursor_for(cursor)),
        mock.patch.object(billing, "_bill_row", return_value=bill),
        mock.patch.object(billing, "_gst_payment_rows", return_value=list(rows)),
        mock.patch.object(billing, "_sync_gst") as sync,
        mock.patch.object(billing, "get_bill", return_value={"bill_code": "BILL-1"}),
    ):
        try:
            return billing.record_gst_payment("BILL-1", 7, **{**base, **kw}), cursor, sync
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
        for none in ({"cgst": None, "sgst": None}, {"cgst": "", "sgst": "0"}, {"cgst": 0, "sgst": 0}):
            self.refused("Enter how much", **none)

    def test_an_amount_that_is_not_a_number_or_is_negative(self):
        self.refused("must be a number", cgst="lots", sgst="0")
        self.refused("cannot be negative", cgst="-5", sgst="100")

    def test_the_day_is_needed_and_must_be_a_day(self):
        for bad in (None, "", "yesterday"):
            self.refused("Give the day", paid_date=bad)

    def test_a_day_in_the_future(self):
        self.refused("future", paid_date=date(2026, 10, 20))

    def test_a_day_before_the_bill_was_dated(self):
        self.refused("before the bill was dated", paid_date=date(2026, 7, 30))

    def test_more_than_is_left_on_a_component(self):
        self.refused("Only ₹1,000.00 of CGST is left", cgst="1000.01", sgst="0")
        self.refused("Only ₹400.00 of SGST is left", rows=[pay("SGST", 600)], seen_paid="600", cgst="0", sgst="500")

    def test_a_component_that_is_already_paid_in_full(self):
        self.refused("CGST on this bill is already paid in full", rows=[pay("CGST", 1000)], seen_paid="1000", cgst="1", sgst="0")

    def test_a_cancelled_bill(self):
        result, cursor, _ = record(bill=a_bill(status="Cancelled"))
        self.assertIn("cancelled", str(result))
        self.assertEqual(inserts(cursor), [])

    def test_no_such_bill(self):
        cursor = FakeCursor()
        with mock.patch.object(billing, "db_cursor", _cursor_for(cursor)), mock.patch.object(billing, "_bill_row", return_value=None):
            with self.assertRaisesRegex(billing.BillError, "does not exist"):
                billing.record_gst_payment("NOPE", 7, confirm=True, seen_paid="0", cgst="1", paid_date=date(2026, 10, 5), today=TODAY)


class WhenSomebodyElseGotThereFirst(unittest.TestCase):
    def test_payments_were_recorded_while_this_person_had_the_bill_open(self):
        result, cursor, _ = record(rows=[pay("CGST", 1000)], seen_paid="0", cgst="0", sgst="1000")
        self.assertIsInstance(result, billing.GstConflict)
        self.assertIn("₹1,000.00 is now recorded as paid", str(result))
        self.assertEqual(inserts(cursor), [])

    def test_two_clicks_on_one_screen_cannot_both_write(self):
        first, _, _ = record(seen_paid="0")
        self.assertNotIsInstance(first, Exception)
        second, cursor, _ = record(rows=[pay("CGST", 1000), pay("SGST", 1000)], seen_paid="0")
        self.assertIsInstance(second, billing.GstConflict)
        self.assertEqual(inserts(cursor), [])

    def test_the_amount_seen_is_compared_to_the_paisa(self):
        result, _, _ = record(rows=[pay("CGST", "400.10")], seen_paid="400.1", cgst="0", sgst="100")
        self.assertNotIsInstance(result, Exception)


class WhatIsWritten(unittest.TestCase):
    def test_both_components_in_one_payment_are_two_rows_with_one_batch(self):
        result, cursor, sync = record(cgst="600", sgst="1000", reference="  CHALLAN   12345 ")
        self.assertNotIsInstance(result, Exception)
        first, second = inserts(cursor)
        self.assertEqual((first[1][2], first[1][3]), ("CGST", D("600.00")))
        self.assertEqual((second[1][2], second[1][3]), ("SGST", D("1000.00")))
        self.assertEqual(first[1][1], second[1][1], "one batch")
        self.assertEqual((first[1][0], first[1][4], first[1][5], first[1][6]), ("BILL-1", date(2026, 10, 5), "CHALLAN 12345", 7))
        sync.assert_called_once()

    def test_one_component_alone_is_one_row(self):
        result, cursor, _ = record(cgst="0", sgst="250.5")
        self.assertNotIsInstance(result, Exception)
        (only,) = inserts(cursor)
        self.assertEqual((only[1][2], only[1][3]), ("SGST", D("250.50")))

    def test_the_rest_of_a_part_paid_component_can_be_paid(self):
        result, cursor, _ = record(rows=[pay("CGST", 600)], seen_paid="600", cgst="400", sgst="0")
        self.assertNotIsInstance(result, Exception)
        self.assertEqual(inserts(cursor)[0][1][3], D("400.00"))

    def test_amounts_are_rounded_to_the_paisa(self):
        _, cursor, _ = record(cgst="100.004", sgst="0")
        self.assertEqual(inserts(cursor)[0][1][3], D("100.00"))

    def test_a_blank_reference_is_none_and_a_long_one_is_cut(self):
        _, cursor, _ = record(reference="   ")
        self.assertIsNone(inserts(cursor)[0][1][5])
        _, cursor, _ = record(reference="x" * 200)
        self.assertEqual(len(inserts(cursor)[0][1][5]), billing.GST_REFERENCE_MAX)

    def test_paying_on_the_bill_date_and_today_are_allowed(self):
        for day in (BILL_DATE, TODAY):
            result, _, _ = record(paid_date=day)
            self.assertNotIsInstance(result, Exception, str(day))


class KeepingTheBillInStep(unittest.TestCase):
    def sync(self, bill, rows):
        cursor = FakeCursor()
        with mock.patch.object(billing, "_gst_payment_rows", return_value=rows):
            return billing._sync_gst(cursor, bill), cursor

    def test_paid_in_full_sets_the_flag_the_total_and_who_and_when(self):
        summary, cursor = self.sync(a_bill(), [pay("CGST", 1000), pay("SGST", 1000, "B2")])
        self.assertEqual(summary["status"], "Paid")
        params = cursor.statements[0][1]
        self.assertEqual((params[0], params[1], params[2], params[3]), (True, D("2000.0"), True, 3))

    def test_part_paid_keeps_the_flag_off_and_the_running_total(self):
        summary, cursor = self.sync(a_bill(), [pay("CGST", 1000)])
        self.assertEqual(summary["status"], "Part paid")
        params = cursor.statements[0][1]
        self.assertEqual((params[0], params[1], params[2], params[3]), (False, D("1000.0"), False, 3))

    def test_reversing_everything_clears_it(self):
        _, cursor = self.sync(a_bill(), [pay("CGST", 1000, reversed_=True), pay("SGST", 1000, "B2", reversed_=True)])
        params = cursor.statements[0][1]
        self.assertEqual((params[0], params[1], params[3]), (False, D("0.0"), None))

    def test_a_bill_whose_gst_falls_below_what_was_paid_is_refused(self):
        with self.assertRaisesRegex(billing.BillError, "cannot go below that"):
            self.sync(a_bill(cgst_amount=D("900.00")), [pay("CGST", 1000)])

    def test_a_bill_whose_gst_rises_becomes_part_paid(self):
        summary, _ = self.sync(a_bill(cgst_amount=D("1200.00")), [pay("CGST", 1000), pay("SGST", 1000, "B2")])
        self.assertEqual((summary["status"], summary["cgst"]["remaining"]), ("Part paid", 200.0))


class EditingAndCancelling(unittest.TestCase):
    def cancel(self, rows):
        cursor = FakeCursor()
        with (
            mock.patch.object(billing, "db_cursor", _cursor_for(cursor)),
            mock.patch.object(billing, "_bill_row", return_value=a_bill()),
            mock.patch.object(billing, "_revenue_entries", return_value=[]),
            mock.patch.object(billing, "_gst_payment_rows", return_value=rows),
            mock.patch.object(billing, "_statutory_payment_rows", return_value=[]),  # no EPFO or ESIC has been paid on this bill
            mock.patch.object(billing, "_sync_revenue"),
            mock.patch.object(billing, "get_bill", return_value={"bill_code": "BILL-1"}),
        ):
            try:
                return billing.cancel_bill("BILL-1", "Raised twice", 7), cursor
            except billing.BillError as exc:
                return exc, cursor

    def test_a_bill_with_gst_paid_cannot_be_cancelled(self):
        result, cursor = self.cancel([pay("CGST", 300)])
        self.assertIsInstance(result, billing.BillError)
        self.assertIn("₹300.00 of GST has been paid", str(result))
        self.assertFalse([s for s in cursor.statements if s[0].startswith("UPDATE")])

    def test_after_the_payments_are_reversed_it_can(self):
        result, cursor = self.cancel([pay("CGST", 300, reversed_=True)])
        self.assertNotIsInstance(result, Exception)
        self.assertTrue([s for s in cursor.statements if s[0].startswith("UPDATE orion_ods.bill SET status = 'Cancelled'")])

    def test_the_edit_checks_the_payments_in_the_same_transaction(self):
        import inspect

        source = inspect.getsource(billing.update_bill)
        self.assertIn("_sync_gst(cur, edited)", source)
        self.assertLess(source.index("_sync_revenue(cur, edited"), source.index("_sync_gst(cur, edited)"))
        self.assertLess(source.index("_sync_gst(cur, edited)"), source.index("conn.commit()"))


def reverse(rows, **kw):
    cursor = FakeCursor()
    base = {"confirm": True, "reason": "Recorded on the wrong bill"}
    with (
        mock.patch.object(billing, "db_cursor", _cursor_for(cursor)),
        mock.patch.object(billing, "_bill_row", return_value=a_bill()),
        mock.patch.object(billing, "_gst_payment_rows", return_value=rows),
        mock.patch.object(billing, "_sync_gst") as sync,
        mock.patch.object(billing, "get_bill", return_value={"bill_code": "BILL-1"}),
    ):
        try:
            return billing.reverse_gst_payment("BILL-1", "B1", 7, **{**base, **kw}), cursor, sync
        except billing.BillError as exc:
            return exc, cursor, sync


class Reversing(unittest.TestCase):
    def test_it_needs_confirming_and_a_reason(self):
        for kw, fragment in (({"confirm": False}, "Confirm"), ({"reason": None}, "Say why"), ({"reason": "oops"}, "Say why"), ({"reason": "   "}, "Say why")):
            result, cursor, _ = reverse([pay("CGST", 500)], **kw)
            self.assertIn(fragment, str(result))
            self.assertEqual(cursor.statements, [])

    def test_it_marks_the_rows_reversed_and_keeps_them(self):
        result, cursor, sync = reverse([pay("CGST", 500), pay("SGST", 500)], reason="  Recorded\ton  the wrong bill ")
        self.assertNotIsInstance(result, Exception)
        (update,) = cursor.statements
        self.assertTrue(update[0].startswith("UPDATE orion_ods.bill_gst_payment SET reversed_by"))
        self.assertNotIn("DELETE", update[0])
        self.assertEqual(update[1], (7, "Recorded on the wrong bill", "BILL-1", "B1"))
        sync.assert_called_once()

    def test_a_payment_that_does_not_exist(self):
        result, _, _ = reverse([pay("CGST", 500, "OTHER")])
        self.assertIn("does not exist", str(result))

    def test_a_payment_somebody_already_reversed(self):
        result, cursor, _ = reverse([pay("CGST", 500, reversed_=True)])
        self.assertIsInstance(result, billing.GstConflict)
        self.assertEqual(cursor.statements, [])


class TheRoute(unittest.TestCase):
    def tearDown(self):
        app.dependency_overrides.clear()

    def signed_in(self, **flags):
        app.dependency_overrides[get_current_user] = lambda: {"id": 5, "role": "viewer", "billing_access": True, "billing_write": True, **flags}

    def post(self, path, body):
        return TestClient(app).post(f"/api/billing/bills/BILL-1/{path}", json=body)

    def test_it_needs_a_sign_in_and_the_right_to_change_bills(self):
        self.assertEqual(self.post("gst-payments", {"cgst": 1}).status_code, 401)
        self.signed_in(billing_write=False)
        with mock.patch.object(billing, "record_gst_payment") as call, mock.patch.object(billing, "reverse_gst_payment") as back:
            self.assertEqual(self.post("gst-payments", {"confirm": True}).status_code, 403)
            self.assertEqual(self.post("gst-payments/B1/reverse", {"confirm": True}).status_code, 403)
        call.assert_not_called()
        back.assert_not_called()

    def test_the_old_flag_endpoint_is_gone(self):
        self.signed_in()
        self.assertIn(self.post("gst-paid", {"paid": True}).status_code, (404, 405))

    def test_a_payment_that_was_not_confirmed_is_refused_not_obeyed(self):
        self.signed_in()
        with mock.patch.object(billing, "db_cursor") as cursor:
            response = self.post("gst-payments", {"cgst": 100, "sgst": 100, "paid_date": "2026-10-05", "seen_paid": 0})
        self.assertEqual(response.status_code, 400)
        self.assertIn("Confirm", response.json()["detail"])
        cursor.assert_not_called()

    def test_everything_the_screen_sends_reaches_the_function(self):
        self.signed_in()
        with mock.patch.object(billing, "record_gst_payment", return_value={"id": "BILL-1"}) as call:
            response = self.post("gst-payments", {"confirm": True, "seen_paid": "0", "cgst": "600", "sgst": 400.5, "paid_date": "2026-10-05", "reference": "CH1"})
        self.assertEqual(response.status_code, 200)
        args, kwargs = call.call_args
        self.assertEqual(args, ("BILL-1", 5))
        self.assertEqual((kwargs["confirm"], kwargs["seen_paid"], kwargs["cgst"], kwargs["sgst"], kwargs["paid_date"], kwargs["reference"]), (True, "0", "600", 400.5, date(2026, 10, 5), "CH1"))

    def test_the_reversal_reaches_the_function(self):
        self.signed_in()
        with mock.patch.object(billing, "reverse_gst_payment", return_value={"id": "BILL-1"}) as call:
            response = self.post("gst-payments/B1/reverse", {"confirm": True, "reason": "Wrong bill"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(call.call_args[0], ("BILL-1", "B1", 5))
        self.assertEqual((call.call_args[1]["confirm"], call.call_args[1]["reason"]), (True, "Wrong bill"))

    def test_a_conflict_is_a_409_and_a_mistake_is_a_400(self):
        self.signed_in()
        for function in ("record_gst_payment", "reverse_gst_payment"):
            path = "gst-payments" if function == "record_gst_payment" else "gst-payments/B1/reverse"
            with mock.patch.object(billing, function, side_effect=billing.GstConflict("changed")):
                self.assertEqual(self.post(path, {"confirm": True}).status_code, 409, function)
            with mock.patch.object(billing, function, side_effect=billing.BillError("no")):
                self.assertEqual(self.post(path, {"confirm": True}).status_code, 400, function)


@unittest.skipUnless(os.environ.get("ORION_DB_TESTS") == "1", "set ORION_DB_TESTS=1 to run these against the development database")
class AgainstTheRealDatabase(unittest.TestCase):
    """Pays a bill's GST in instalments, reverses one, and puts the bill and its payments back as they were."""

    def setUp(self):
        from app.database import db_cursor

        with db_cursor() as cur:
            cur.execute(
                """
                SELECT b.bill_code FROM orion_ods.bill b
                 WHERE b.status = 'Issued' AND b.cgst_amount > 10 AND b.sgst_amount > 10
                   AND NOT EXISTS (SELECT 1 FROM orion_ods.bill_gst_payment p WHERE p.bill_code = b.bill_code)
                 ORDER BY b.bill_date DESC LIMIT 1
                """
            )
            found = cur.fetchone()
        if not found:
            self.skipTest("the development database has no issued bill with GST and no GST payments")
        self.code = found[0]
        self.addCleanup(self.restore)

    def restore(self):
        """Remove only what this test wrote, and put the bill back only if nobody else has paid anything on it meanwhile."""
        from app.database import db_cursor

        with db_cursor(commit=True) as cur:
            cur.execute("DELETE FROM orion_ods.bill_gst_payment WHERE bill_code = %s AND reference LIKE 'TEST-%%'", (self.code,))
            cur.execute("SELECT NOT EXISTS (SELECT 1 FROM orion_ods.bill_gst_payment WHERE bill_code = %s)", (self.code,))
            if cur.fetchone()[0]:
                cur.execute("UPDATE orion_ods.bill SET gst_paid = FALSE, gst_paid_amount = 0, gst_paid_by = NULL, gst_paid_timestamp = NULL WHERE bill_code = %s", (self.code,))

    def test_instalments_status_reversal_and_the_guards(self):
        bill = billing.get_bill(self.code)
        cgst, sgst = D(str(bill["cgst_amount"])), D(str(bill["sgst_amount"]))
        self.assertEqual(bill["gst"]["status"], "Not paid")
        first = D("5.00")
        after_first = billing.record_gst_payment(self.code, None, confirm=True, seen_paid="0", cgst=first, paid_date=date.today(), reference="TEST-1")
        self.assertEqual((after_first["gst"]["status"], after_first["gst_paid"], after_first["gst_paid_amount"]), ("Part paid", False, 5.0))
        with self.assertRaises(billing.GstConflict):  # the same screen, a second time
            billing.record_gst_payment(self.code, None, confirm=True, seen_paid="0", cgst=first, paid_date=date.today(), reference="TEST-X")
        with self.assertRaises(billing.BillError):  # more than is left
            billing.record_gst_payment(self.code, None, confirm=True, seen_paid="5", cgst=cgst, paid_date=date.today(), reference="TEST-X")
        with self.assertRaises(billing.BillError):  # a bill with GST paid cannot be cancelled
            billing.cancel_bill(self.code, "Test: should be refused", None)
        rest = billing.record_gst_payment(self.code, None, confirm=True, seen_paid="5", cgst=cgst - first, sgst=sgst, paid_date=date.today(), reference="TEST-2")
        self.assertEqual((rest["gst"]["status"], rest["gst_paid"]), ("Paid", True))
        self.assertEqual(len(rest["gst"]["payments"]), 2)
        newest = rest["gst"]["payments"][0]["batch_id"]
        back = billing.reverse_gst_payment(self.code, newest, None, confirm=True, reason="Test: taken back")
        self.assertEqual((back["gst"]["status"], back["gst_paid"], back["gst_paid_amount"]), ("Part paid", False, 5.0))
        self.assertTrue(back["gst"]["payments"][0]["reversed"])
        self.assertEqual(back["gst"]["payments"][0]["reversal_reason"], "Test: taken back")
        with self.assertRaises(billing.GstConflict):
            billing.reverse_gst_payment(self.code, newest, None, confirm=True, reason="Test: again")


if __name__ == "__main__":
    unittest.main()
