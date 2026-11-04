"""Credit notes and write-offs: who may approve, what approval does to a bill, and where the dashboards and the GST position follow.

The first half needs no database. The second half makes a bill inside one transaction that is rolled back at the end (nothing is left behind); it
runs only with ORION_DB_TESTS=1:

    $env:ORION_DB_TESTS = "1"; python -m pytest backend/tests/test_credit_notes.py
"""

import contextlib
import itertools
import os
import sys
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app import billing, credit_notes, entities, gst_position  # noqa: E402

RUN = os.environ.get("ORION_DB_TESTS") == "1"
SQL = ROOT / ".cursor" / "db"
DASH = ROOT / "backend" / "app" / "dashboard"


class WhoMayApproveTests(unittest.TestCase):
    note = {"kind": "Credit note", "created_by": 1}

    def test_the_maker_cannot_approve_their_own_unless_an_admin(self):
        self.assertIsNotNone(credit_notes.can_approve(self.note, 1, False))
        self.assertIsNone(credit_notes.can_approve(self.note, 1, True))

    def test_someone_else_can(self):
        self.assertIsNone(credit_notes.can_approve(self.note, 2, False))

    def test_a_write_off_needs_an_admin_even_from_someone_else(self):
        write_off = {"kind": "Bad debt write-off", "created_by": 1}
        self.assertIn("admin", credit_notes.can_approve(write_off, 2, False))
        self.assertIsNone(credit_notes.can_approve(write_off, 2, True))
        self.assertIsNone(credit_notes.can_approve(write_off, 1, True))  # an admin who made it may approve it: a team of one

    def test_the_rights_are_worked_out_on_the_server(self):
        note = {**self.note, "status": "Pending"}
        got = credit_notes._with_rights(dict(note), 2, False)
        self.assertEqual((got["can_approve"], got["can_withdraw"], got["can_reverse"]), (True, False, False))
        got = credit_notes._with_rights(dict(note), 1, False)
        self.assertEqual((got["can_approve"], got["can_withdraw"]), (False, True))
        self.assertTrue(got["approve_blocked"])
        done = credit_notes._with_rights({**self.note, "status": "Approved"}, 2, True)
        self.assertEqual((done["can_approve"], done["can_reverse"]), (False, True))


class NumberingTests(unittest.TestCase):
    def test_a_number_is_cn_year_and_sequence(self):
        self.assertEqual(credit_notes.cn_number(2026, 1), "CN 2026-27/1")
        self.assertEqual(credit_notes.cn_number(2026, 12), "CN 2026-27/12")

    def test_a_reason_is_needed(self):
        with self.assertRaises(billing.BillError):
            credit_notes._reason("  ab ")
        self.assertEqual(credit_notes._reason("  rate   dispute "), "rate dispute")


class StatusTests(unittest.TestCase):
    def test_a_bill_settled_with_the_help_of_a_credit_note_is_settled_not_paid(self):
        self.assertEqual(billing.payment_status("Issued", 1000, 600, 400), "Settled")
        self.assertEqual(billing.payment_status("Issued", 1000, 1000, 0), "Paid")
        self.assertEqual(billing.payment_status("Issued", 1000, 0, 400), "Unpaid")
        self.assertEqual(billing.payment_status("Issued", 1000, 300, 400), "Part paid")

    def test_the_gst_due_is_the_gst_less_what_was_credited(self):
        bill = {"cgst_amount": Decimal("90"), "sgst_amount": Decimal("90"), "credited_cgst": Decimal("9"), "credited_sgst": Decimal("9")}
        self.assertEqual(billing._gst_due(bill), (Decimal("81"), Decimal("81")))
        self.assertEqual(billing._gst_due({"cgst_amount": Decimal("90"), "sgst_amount": Decimal("90")}), (Decimal("90"), Decimal("90")))


class ReaderContractTests(unittest.TestCase):
    """Everything that reads a bill's money must follow what credit notes took off. These fail when a reader is added without it."""

    def test_the_file_is_registered_everywhere_and_before_the_bank_one(self):
        order = [p.name for p in entities.SQL_MIGRATIONS]
        self.assertLess(order.index("migrate_credit_notes.sql"), order.index("migrate_bank.sql"))
        for script in ("init_db_mac.sh", "init_db_windows.ps1"):
            text = (ROOT / "scripts" / script).read_text(encoding="utf-8")
            self.assertLess(text.index("migrate_credit_notes.sql"), text.index("migrate_bank.sql"))

    def test_the_forecast_expects_the_gst_after_credit_notes(self):
        bank = (SQL / "migrate_bank.sql").read_text(encoding="utf-8")
        expected = bank[bank.index("SELECT 'gst_due'::text"):bank.index("-- Salary still to pay")]
        self.assertEqual(expected.count("b.credited_cgst"), 2)
        self.assertEqual(expected.count("b.credited_sgst"), 2)

    def test_the_dashboards_net_the_credit(self):
        engine = (DASH / "engine.py").read_text(encoding="utf-8")
        self.assertIn("b.credited_taxable", engine.split("REVENUE =", 1)[1].split("\n", 1)[0])
        self.assertIn("b.credited_amount", engine.split("BILLED =", 1)[1].split("\n", 1)[0])
        self.assertIn("b.credited_cgst", engine.split("GST =", 1)[1].split("\n", 1)[0])
        self.assertIn("b.credited_amount", (DASH / "filters.py").read_text(encoding="utf-8").split("BILL_OPEN =", 1)[1].split("\n", 1)[0])
        for path in DASH.glob("*.py"):
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                if "b.cgst_amount + b.sgst_amount" in line:
                    self.assertIn("credited_cgst", line, f"{path.name}:{number} reads a bill's GST without what credit notes took off")

    def test_the_warehouse_carries_what_was_credited(self):
        from app import dw_sync

        spec = dw_sync.FACTS["Bill"]
        for column in ("credited_taxable", "credited_cgst", "credited_sgst", "credited_amount"):
            for key in ("ods_cols", "dw_cols", "compare"):
                self.assertIn(column, spec[key], f"{column} missing from {key}")
            self.assertIn(f"ADD COLUMN IF NOT EXISTS {column}", (SQL / "dw_schema.sql").read_text(encoding="utf-8"))

    def test_a_credit_note_is_kept_for_ever(self):
        sql = (SQL / "migrate_credit_notes.sql").read_text(encoding="utf-8")
        self.assertIn("BEFORE UPDATE OR DELETE ON orion_ods.credit_note", sql)
        self.assertIn("kept for ever", sql)
        self.assertNotIn("DROP TABLE", sql)
        for guard in ("status IN ('Pending', 'Approved', 'Rejected', 'Withdrawn', 'Reversed')", "CHECK (total > 0)"):
            self.assertIn(guard, sql)

    def test_the_sql_editor_treats_it_as_the_applications_own_table(self):
        from app import sql_guard

        for name in ("credit_note", "credit_note_counter"):
            self.assertTrue(sql_guard.OWNED_TABLES.match(name), name)

    def test_receivables_take_the_credit_off(self):
        from app import receivables

        row = {"client_code": "C", "client_name": "C", "grand_total": 1000, "received": 300, "credited": 700, "bill_date": date(2026, 4, 1), "id": "B", "bill_number": "1",
               "service_month": date(2026, 4, 1), "case_code": "CS", "case_name": "x"}
        self.assertEqual(receivables.build_receivables([row], date(2026, 6, 1))["clients"], [])  # nothing is left to receive
        owed = receivables.build_receivables([{**row, "credited": 200}], date(2026, 6, 1))["clients"]
        self.assertEqual(owed[0]["total"], 500.0)


class PositionTests(unittest.TestCase):
    def test_a_credit_note_comes_off_the_tax_in_the_month_of_the_note(self):
        out = {date(2026, 4, 1): Decimal("1000")}
        notes = {date(2026, 5, 1): Decimal("100")}
        got = gst_position.build_position(2026, out, {}, {}, today=date(2026, 6, 1), notes=notes)
        months = {m["month"]: m for m in got["months"]}
        self.assertEqual((months["2026-04-01"]["net"], months["2026-05-01"]["net"]), (1000, -100))
        self.assertEqual(got["totals"]["net"], 900.0)
        self.assertEqual(got["totals"]["notes"], 100.0)


class FakeConnection:
    """A connection whose commit keeps everything and whose rollback goes back only to where it began, so a refusal does not undo the test's own setup."""

    names = itertools.count(1)

    def __init__(self, raw):
        self.raw, self.name = raw, f"cn_test_{next(self.names)}"
        self._run(f"SAVEPOINT {self.name}")

    def _run(self, sql):
        cur = self.raw.cursor()
        try:
            cur.execute(sql)
        finally:
            cur.close()

    def cursor(self, *args, **kwargs):
        return self.raw.cursor(*args, **kwargs)

    def commit(self):
        pass

    def rollback(self):
        self._run(f"ROLLBACK TO SAVEPOINT {self.name}")

    def close(self):
        pass


@unittest.skipUnless(RUN, "needs the development database: set ORION_DB_TESTS=1")
class CreditNoteOnABillTests(unittest.TestCase):
    MAKER, OTHER, ADMIN = 910001, 910002, 910003

    def setUp(self):
        from app import database

        self.raw = database.raw_connection()
        self.addCleanup(self.raw.close)
        self.addCleanup(self.raw.rollback)
        names = itertools.count(1)

        @contextlib.contextmanager
        def cursor(commit=False):
            cur = self.raw.cursor()
            name = f"cn_cur_{next(names)}"
            cur.execute(f"SAVEPOINT {name}")
            try:
                yield cur
            except Exception:
                cur.execute(f"ROLLBACK TO SAVEPOINT {name}")
                raise
            finally:
                cur.close()

        patched = {m: (m.get_connection, m.db_cursor) for m in (billing, credit_notes)}
        for module in patched:
            module.get_connection = lambda: FakeConnection(self.raw)
            module.db_cursor = cursor
        self.addCleanup(lambda: [(setattr(m, "get_connection", g), setattr(m, "db_cursor", c)) for m, (g, c) in patched.items()])
        with cursor() as cur:
            cur.execute("SELECT case_code FROM orion_ods.case WHERE client_code IS NOT NULL ORDER BY case_code LIMIT 1")
            row = cur.fetchone()
        if not row:
            self.skipTest("the development database has no case with a client to bill")
        self.bill = billing.create_bill(
            {"bill_date": date(2026, 4, 15), "service_month": "2026-04", "case_code": row[0], "party_name": "Credit Note Test Ltd",
             "lines": [{"particulars": "Guard", "qty": 10, "rate": 10000}]},
            self.MAKER,
        )
        self.code = self.bill["id"]
        self.total = Decimal(str(self.bill["grand_total"]))

    def next_number(self):
        """The number the next approved note in 2026-27 will get (the dev database may already hold some, so it is read, not assumed)."""
        with billing.db_cursor() as cur:
            cur.execute("SELECT last_no FROM orion_ods.credit_note_counter WHERE fy_start_year = 2026")
            row = cur.fetchone()
        return credit_notes.cn_number(2026, (row[0] if row else 0) + 1)

    def made(self, amount, kind="Credit note"):
        return credit_notes.create(self.code, kind, amount, date(2026, 5, 1), "rate dispute with the client", self.MAKER)

    def bill_now(self):
        return billing.get_bill(self.code)

    def test_a_pending_note_changes_nothing(self):
        note = self.made("10000")
        self.assertEqual(note["status"], "Pending")
        self.assertIsNone(note["cn_number"])
        self.assertEqual(self.bill_now()["revenue"]["remaining"], float(self.total))

    def test_the_maker_cannot_approve_and_someone_else_can(self):
        note = self.made("10000")
        expected = self.next_number()
        with self.assertRaises(billing.BillError):
            credit_notes.approve(note["id"], self.MAKER, False, confirm=True, seen_total="10000")
        done = credit_notes.approve(note["id"], self.OTHER, False, confirm=True, seen_total="10000")
        self.assertEqual(done["status"], "Approved")
        self.assertEqual(done["cn_number"], expected)

    def test_an_admin_may_approve_their_own(self):
        note = credit_notes.create(self.code, "Credit note", "10000", date(2026, 5, 1), "an admin's own credit note", self.ADMIN)
        self.assertEqual(credit_notes.approve(note["id"], self.ADMIN, True, confirm=True, seen_total="10000")["status"], "Approved")

    def test_approval_needs_the_confirmation_and_the_amount_that_was_seen(self):
        note = self.made("10000")
        with self.assertRaises(billing.BillError):
            credit_notes.approve(note["id"], self.OTHER, False, confirm=False, seen_total="10000")
        with self.assertRaises(billing.BillError):
            credit_notes.approve(note["id"], self.OTHER, False, confirm=True, seen_total="9999")
        self.assertEqual(credit_notes.get(note["id"])["status"], "Pending")

    def test_a_write_off_is_for_an_admin_only(self):
        note = self.made("10000", "Bad debt write-off")
        with self.assertRaises(billing.BillError):
            credit_notes.approve(note["id"], self.OTHER, False, confirm=True, seen_total="10000")
        self.assertEqual(credit_notes.approve(note["id"], self.ADMIN, True, confirm=True, seen_total="10000")["status"], "Approved")

    def test_approval_takes_the_credit_off_what_is_owed_the_revenue_and_the_gst(self):
        before = self.bill_now()
        note = self.made("11800")
        done = credit_notes.approve(note["id"], self.OTHER, False, confirm=True, seen_total="11800")
        self.assertEqual(round(done["taxable"] + done["cgst"] + done["sgst"], 2), 11800.0)
        after = self.bill_now()
        revenue = after["revenue"]
        self.assertEqual(revenue["credited"], 11800.0)
        self.assertEqual(Decimal(str(revenue["remaining"])), self.total - Decimal("11800"))
        open_entry = next(e for e in revenue["entries"] if e["status"] == "Prospective")
        self.assertEqual(Decimal(str(open_entry["amount"])), self.total - Decimal("11800"))
        # the GST due on the bill comes down by the GST in the credit note, the bill's own figures never change
        self.assertEqual(after["grand_total"], before["grand_total"])
        self.assertEqual(round(after["gst"]["total"]["due"], 2), round(before["gst"]["total"]["due"] - done["cgst"] - done["sgst"], 2))
        self.assertEqual(billing.payment_status("Issued", after["grand_total"], revenue["received"], revenue["credited"]), "Unpaid")

    def test_a_bill_credited_in_full_has_nothing_left_to_receive(self):
        note = self.made(str(self.total))
        credit_notes.approve(note["id"], self.OTHER, False, confirm=True, seen_total=str(self.total))
        revenue = self.bill_now()["revenue"]
        self.assertEqual(revenue["remaining"], 0)
        self.assertEqual([e for e in revenue["entries"] if e["status"] == "Prospective"], [])
        with self.assertRaises(billing.BillError):
            self.made("1")  # nothing left to credit

    def test_a_credit_cannot_be_more_than_is_still_owed_and_payments_count(self):
        with self.assertRaises(billing.BillError):
            self.made(str(self.total + 1))
        billing.record_payment(self.code, "100000", date(2026, 5, 2), self.MAKER)
        with self.assertRaises(billing.BillError):
            self.made(str(self.total - Decimal("99999")))
        self.made(str(self.total - Decimal("100000")))

    def test_a_note_made_before_a_payment_is_refused_at_approval_if_it_no_longer_fits(self):
        note = self.made(str(self.total - Decimal("1000")))
        billing.record_payment(self.code, "50000", date(2026, 5, 2), self.MAKER)
        with self.assertRaises(billing.BillError):
            credit_notes.approve(note["id"], self.OTHER, False, confirm=True, seen_total=str(self.total - Decimal("1000")))
        self.assertEqual(credit_notes.get(note["id"])["status"], "Pending")

    def test_gst_already_paid_beyond_what_would_be_due_stops_the_approval(self):
        due = Decimal(str(self.bill_now()["gst"]["total"]["due"]))
        billing.record_gst_payment(self.code, self.MAKER, confirm=True, seen_paid="0", cgst=str(due / 2), sgst=str(due / 2), paid_date=date(2026, 5, 3))
        note = self.made("11800")
        with self.assertRaises(billing.BillError) as caught:
            credit_notes.approve(note["id"], self.OTHER, False, confirm=True, seen_total="11800")
        self.assertIn("paid to the government", str(caught.exception))
        self.assertEqual(credit_notes.get(note["id"])["status"], "Pending")

    def test_a_bill_with_a_credit_note_cannot_be_cancelled(self):
        note = self.made("10000")
        credit_notes.approve(note["id"], self.OTHER, False, confirm=True, seen_total="10000")
        with self.assertRaises(billing.BillError):
            billing.cancel_bill(self.code, "mistake", self.MAKER)

    def test_refusing_needs_a_reason_and_leaves_no_gap_in_the_numbers(self):
        first = self.made("10000")
        with self.assertRaises(billing.BillError):
            credit_notes.reject(first["id"], self.OTHER, False, "")
        rejected = credit_notes.reject(first["id"], self.OTHER, False, "not agreed with the client")
        self.assertEqual((rejected["status"], rejected["cn_number"]), ("Rejected", None))
        expected = self.next_number()
        second = self.made("10000")
        self.assertEqual(credit_notes.approve(second["id"], self.OTHER, False, confirm=True, seen_total="10000")["cn_number"], expected)

    def test_the_maker_can_withdraw_but_not_someone_else(self):
        note = self.made("10000")
        with self.assertRaises(billing.BillError):
            credit_notes.withdraw(note["id"], self.OTHER, False)
        self.assertEqual(credit_notes.withdraw(note["id"], self.MAKER, False)["status"], "Withdrawn")

    def test_an_admin_can_reverse_an_approved_note_and_what_it_credited_is_owed_again(self):
        note = self.made("11800")
        expected = self.next_number()
        credit_notes.approve(note["id"], self.OTHER, False, confirm=True, seen_total="11800")
        with self.assertRaises(billing.BillError):
            credit_notes.reverse(note["id"], self.OTHER, False, "entered by mistake")
        with self.assertRaises(billing.BillError):
            credit_notes.reverse(note["id"], self.ADMIN, True, "no")  # a reason is needed
        undone = credit_notes.reverse(note["id"], self.ADMIN, True, "entered by mistake")
        self.assertEqual((undone["status"], undone["cn_number"]), ("Reversed", expected))  # the number is kept
        after = self.bill_now()
        self.assertEqual(after["revenue"]["credited"], 0)
        self.assertEqual(Decimal(str(after["revenue"]["remaining"])), self.total)
        self.assertEqual(round(after["gst"]["total"]["due"], 2), round(float(self.bill["cgst_amount"] + self.bill["sgst_amount"]), 2))

    def test_a_credit_note_is_never_deleted_or_changed(self):
        import psycopg2

        note = self.made("10000")
        for sql in ("DELETE FROM orion_ods.credit_note WHERE credit_note_id = %s", "UPDATE orion_ods.credit_note SET total = 1 WHERE credit_note_id = %s"):
            with self.subTest(sql=sql[:20]):
                cur = self.raw.cursor()
                cur.execute("SAVEPOINT s")
                try:
                    with self.assertRaises(psycopg2.Error):
                        cur.execute(sql, (note["id"],))
                finally:
                    cur.execute("ROLLBACK TO SAVEPOINT s")
                    cur.close()

    def test_the_listing_counts_what_waits(self):
        self.made("10000")
        got = credit_notes.listing("Pending", None, self.OTHER, False)
        self.assertGreaterEqual(got["pending"], 1)
        self.assertTrue(all(r["status"] == "Pending" for r in got["rows"]))

    def test_the_gst_position_takes_the_credit_note_off_in_the_month_of_the_note(self):
        note = self.made("11800")
        done = credit_notes.approve(note["id"], self.OTHER, False, confirm=True, seen_total="11800")
        original = gst_position.db_cursor
        gst_position.db_cursor = billing.db_cursor  # the position reads through this test's own transaction
        self.addCleanup(lambda: setattr(gst_position, "db_cursor", original))
        got = gst_position.position(2026)
        may = next(m for m in got["months"] if m["month"] == "2026-05-01")
        self.assertEqual(may["notes"], round(done["cgst"] + done["sgst"], 2))


if __name__ == "__main__":
    unittest.main()
