"""What a client holds back when it pays a bill (TDS, a penalty, rounding): the rules, the bank seeing only the cash, and the TDS ledger.

The first half needs no database. The second half rehearses real payments on a bill it makes inside one transaction that is rolled back (nothing
is left behind); it runs only with ORION_DB_TESTS=1:

    $env:ORION_DB_TESTS = "1"; python -m pytest backend/tests/test_deductions.py
"""

import contextlib
import os
import sys
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app import billing, entities, tds  # noqa: E402

RUN = os.environ.get("ORION_DB_TESTS") == "1"
SQL = ROOT / ".cursor" / "db"


class CleanDeductionsTests(unittest.TestCase):
    def test_nothing_held_back_is_an_empty_list(self):
        self.assertEqual(billing.clean_deductions(None), [])
        self.assertEqual(billing.clean_deductions([]), [])
        self.assertEqual(billing.clean_deductions(""), [])

    def test_tds_needs_a_section_and_is_tidied(self):
        got = billing.clean_deductions([{"kind": "tds", "amount": "1,729.5".replace(",", ""), "section": " 194-c ", "rate": "2"}])
        self.assertEqual(got[0]["kind"], "TDS")
        self.assertEqual(got[0]["amount"], Decimal("1729.50"))
        self.assertEqual(got[0]["section"], "194C")
        self.assertEqual(got[0]["rate"], Decimal("2.000"))
        for section in (None, "", "19", "194C!!", "TOO-LONG-SECTION"):
            with self.subTest(section=section), self.assertRaises(billing.BillError):
                billing.clean_deductions([{"kind": "TDS", "amount": "10", "section": section}])

    def test_a_penalty_and_other_need_a_reason_and_rounding_is_small(self):
        for kind in ("Penalty", "Other"):
            with self.subTest(kind=kind), self.assertRaises(billing.BillError):
                billing.clean_deductions([{"kind": kind, "amount": "10"}])
            self.assertEqual(billing.clean_deductions([{"kind": kind, "amount": "10", "reason": "late delivery"}])[0]["reason"], "late delivery")
        self.assertEqual(billing.clean_deductions([{"kind": "Rounding", "amount": "10"}])[0]["amount"], Decimal("10.00"))
        with self.assertRaises(billing.BillError):
            billing.clean_deductions([{"kind": "Rounding", "amount": "10.01"}])

    def test_the_amount_must_be_over_nothing_and_the_kind_known(self):
        for bad in ({"kind": "TDS", "amount": "0", "section": "194C"}, {"kind": "Other", "amount": "-5", "reason": "x"}, {"kind": "Gift", "amount": "5"}, {"kind": "", "amount": "5"}):
            with self.subTest(bad=bad), self.assertRaises(billing.BillError):
                billing.clean_deductions([bad])

    def test_the_rate_is_a_percentage(self):
        for rate in ("0", "-1", "101", "abc"):
            with self.subTest(rate=rate), self.assertRaises(billing.BillError):
                billing.clean_deductions([{"kind": "TDS", "amount": "10", "section": "194C", "rate": rate}])

    def test_too_many_or_not_a_list(self):
        with self.assertRaises(billing.BillError):
            billing.clean_deductions([{"kind": "Rounding", "amount": "1"}] * (billing.MAX_DEDUCTIONS + 1))
        with self.assertRaises(billing.BillError):
            billing.clean_deductions({"kind": "TDS"})
        with self.assertRaises(billing.BillError):
            billing.clean_deductions(["TDS"])

    def test_the_suggested_sections_start_with_the_usual_one(self):
        self.assertEqual(billing.DEFAULT_TDS_SECTION[0], "194C")
        self.assertEqual([s["code"] for s in tds.sections()][:1], ["194C"])
        self.assertTrue(all(s["rate"] > 0 for s in tds.sections()))


class QuarterTests(unittest.TestCase):
    def test_the_income_tax_quarters(self):
        self.assertEqual([tds.quarter(date(2026, m, 15)) for m in range(1, 13)], ["Q4", "Q4", "Q4", "Q1", "Q1", "Q1", "Q2", "Q2", "Q2", "Q3", "Q3", "Q3"])

    def test_a_financial_year_runs_april_to_march(self):
        self.assertEqual(billing.fy_start_year(date(2027, 3, 31)), 2026)
        self.assertEqual(billing.fy_start_year(date(2027, 4, 1)), 2027)


class SchemaContractTests(unittest.TestCase):
    def test_the_file_runs_before_the_bank_one_everywhere(self):
        order = [p.name for p in entities.SQL_MIGRATIONS]
        self.assertLess(order.index("migrate_deductions.sql"), order.index("migrate_bank.sql"))
        mac = (ROOT / "scripts" / "init_db_mac.sh").read_text(encoding="utf-8")
        self.assertLess(mac.index("migrate_deductions.sql"), mac.index("migrate_bank.sql"))
        windows = (ROOT / "scripts" / "init_db_windows.ps1").read_text(encoding="utf-8")
        self.assertLess(windows.index("migrate_deductions.sql"), windows.index("migrate_bank.sql"))

    def test_the_bank_sees_the_cash_only(self):
        bank = (SQL / "migrate_bank.sql").read_text(encoding="utf-8")
        view = bank[bank.index("CREATE OR REPLACE VIEW orion_ods.bank_movement"):bank.index("CREATE OR REPLACE VIEW orion_ods.bank_expected")]
        self.assertIn("bill_payment_deduction", view)
        self.assertIn("- held.amount AS amount", view)
        self.assertIn("reversed_timestamp IS NULL", view.split("bill_payment_deduction", 1)[1].split("UNION ALL", 1)[0])

    def test_a_deduction_is_kept_for_ever(self):
        sql = (SQL / "migrate_deductions.sql").read_text(encoding="utf-8")
        self.assertIn("BEFORE UPDATE OR DELETE ON orion_ods.bill_payment_deduction", sql)
        self.assertIn("kept for ever", sql)
        self.assertNotIn("DROP TABLE", sql)
        for guard in ("kind <> 'TDS' OR section IS NOT NULL", "(reversed_timestamp IS NULL) = (reversal_reason IS NULL)"):
            self.assertIn(guard, sql)


class FakeConnection:
    def __init__(self, raw):
        self.raw = raw

    def cursor(self, *args, **kwargs):
        return self.raw.cursor(*args, **kwargs)

    def commit(self):
        pass

    def rollback(self):
        raise RuntimeError("rolled back inside the test")

    def close(self):
        pass


@unittest.skipUnless(RUN, "needs the development database: set ORION_DB_TESTS=1")
class PaymentWithDeductionsTests(unittest.TestCase):
    """Real payments on a bill made inside one transaction that is rolled back at the end."""

    def setUp(self):
        from app import database

        self.raw = database.raw_connection()
        self.addCleanup(self.raw.close)
        self.addCleanup(self.raw.rollback)

        @contextlib.contextmanager
        def cursor(commit=False):
            cur = self.raw.cursor()
            try:
                yield cur
            finally:
                cur.close()

        saved = (billing.get_connection, billing.db_cursor, tds.db_cursor)
        billing.get_connection = lambda: FakeConnection(self.raw)
        billing.db_cursor = tds.db_cursor = cursor
        self.addCleanup(lambda: (setattr(billing, "get_connection", saved[0]), setattr(billing, "db_cursor", saved[1]), setattr(tds, "db_cursor", saved[2])))
        with cursor() as cur:
            cur.execute("SELECT case_code FROM orion_ods.case WHERE client_code IS NOT NULL ORDER BY case_code LIMIT 1")
            row = cur.fetchone()
            if not row:
                self.skipTest("the development database has no case with a client to bill")
            cur.execute("SELECT id FROM orion_ods.app_user ORDER BY id LIMIT 1")
            self.user = cur.fetchone()[0]
        self.bill = billing.create_bill(
            {"bill_date": date(2099, 4, 15), "service_month": "2099-04", "case_code": row[0], "party_name": "Deduction Test Ltd",
             "lines": [{"particulars": "Guard", "qty": 10, "rate": 10000}]},
            self.user,
        )
        self.code = self.bill["id"]
        self.total = Decimal(str(self.bill["grand_total"]))

    def movements(self):
        with billing.db_cursor() as cur:
            cur.execute(
                "SELECT amount FROM orion_ods.bank_movement WHERE source = 'revenue' AND bill_code = %s ORDER BY source_ref", (self.code,)
            )
            return [row[0] for row in cur.fetchall()]

    def test_a_bill_paid_net_of_tds_closes_and_the_bank_sees_only_the_cash(self):
        held = (self.total * Decimal("0.02")).quantize(Decimal("0.01"))
        cash = self.total - held
        saved = billing.record_payment(self.code, cash, date(2099, 5, 10), self.user, None, None, [{"kind": "TDS", "amount": held, "section": "194C", "rate": 2}])
        revenue = saved["revenue"]
        self.assertEqual(Decimal(str(revenue["received"])), self.total)
        self.assertEqual(Decimal(str(revenue["deducted"])), held)
        self.assertEqual(revenue["remaining"], 0)
        self.assertEqual(billing.payment_status(saved["status"], float(self.total), revenue["received"]), "Paid")
        self.assertEqual([e["status"] for e in revenue["entries"]], ["Committed"])  # no open entry is left to show as outstanding
        self.assertEqual(self.movements(), [cash])
        # the entries still add up to the bill
        self.assertEqual(sum(Decimal(str(e["amount"])) for e in revenue["entries"]), self.total)

    def test_a_part_payment_with_deductions_leaves_the_rest_open(self):
        saved = billing.record_payment(
            self.code, "10000", date(2099, 5, 10), self.user, None, None,
            [{"kind": "TDS", "amount": "200", "section": "194C"}, {"kind": "Rounding", "amount": "0.50"}],
        )
        revenue = saved["revenue"]
        self.assertEqual(Decimal(str(revenue["received"])), Decimal("10200.50"))
        self.assertEqual(Decimal(str(revenue["remaining"])), self.total - Decimal("10200.50"))
        open_entry = next(e for e in revenue["entries"] if e["status"] == "Prospective")
        self.assertEqual(Decimal(str(open_entry["amount"])), self.total - Decimal("10200.50"))
        self.assertEqual(self.movements(), [Decimal("10000.00")])
        ledger = tds.ledger(2099)
        self.assertEqual(ledger["totals"]["total"], 200.0)  # only TDS is in the TDS ledger

    def test_cash_and_deductions_together_cannot_pass_what_is_open(self):
        with self.assertRaises((billing.BillError, RuntimeError)):
            billing.record_payment(self.code, self.total, date(2099, 5, 10), self.user, None, None, [{"kind": "Other", "amount": "5", "reason": "test"}])

    def test_reversing_the_payment_takes_the_deduction_with_it_but_keeps_the_row(self):
        saved = billing.record_payment(self.code, "10000", date(2099, 5, 10), self.user, None, None, [{"kind": "TDS", "amount": "200", "section": "194C"}])
        entry = next(e for e in saved["revenue"]["entries"] if e["status"] == "Committed")
        after = billing.reverse_payment(self.code, entry["id"], self.user)
        self.assertEqual(after["revenue"]["received"], 0)
        self.assertEqual(after["revenue"]["deducted"], 0)
        self.assertEqual(self.movements(), [])
        self.assertEqual(tds.ledger(2099)["totals"]["count"], 0)
        with billing.db_cursor() as cur:
            cur.execute("SELECT amount, reversal_reason FROM orion_ods.bill_payment_deduction WHERE bill_code = %s", (self.code,))
            rows = cur.fetchall()
        self.assertEqual(len(rows), 1)  # kept
        self.assertIsNotNone(rows[0][1])

    def test_a_tds_deduction_is_ticked_against_26as_and_the_tick_taken_off(self):
        billing.record_payment(self.code, "10000", date(2099, 5, 10), self.user, None, None, [{"kind": "TDS", "amount": "200", "section": "194C"}])
        row = tds.ledger(2099)["rows"][0]
        self.assertFalse(row["matched"])
        self.assertEqual(row["quarter"], "Q1")
        tds.set_matched(row["deduction_id"], True, "CERT-1", self.user)
        done = tds.ledger(2099, match="matched")
        self.assertEqual((done["totals"]["matched"], done["totals"]["unmatched"]), (200.0, 0.0))
        self.assertEqual(done["rows"][0]["certificate_ref"], "CERT-1")
        tds.set_matched(row["deduction_id"], False, None, self.user)
        self.assertEqual(tds.ledger(2099, match="unmatched")["totals"]["unmatched"], 200.0)

    def test_only_tds_is_matched_and_a_deduction_cannot_be_deleted_or_changed(self):
        billing.record_payment(self.code, "10000", date(2099, 5, 10), self.user, None, None, [{"kind": "Rounding", "amount": "1"}, {"kind": "TDS", "amount": "200", "section": "194C"}])
        with billing.db_cursor() as cur:
            cur.execute("SELECT deduction_id FROM orion_ods.bill_payment_deduction WHERE kind = 'Rounding' AND bill_code = %s", (self.code,))
            rounding = cur.fetchone()[0]
        with self.assertRaises(tds.TdsError):
            tds.set_matched(rounding, True, None, self.user)
        import psycopg2

        for sql in ("DELETE FROM orion_ods.bill_payment_deduction WHERE bill_code = %s", "UPDATE orion_ods.bill_payment_deduction SET amount = 1 WHERE bill_code = %s"):
            with self.subTest(sql=sql[:20]), self.assertRaises(psycopg2.Error):
                cur = self.raw.cursor()
                cur.execute("SAVEPOINT s")
                try:
                    cur.execute(sql, (self.code,))
                finally:
                    cur.execute("ROLLBACK TO SAVEPOINT s")
                    cur.close()

    def test_the_suggestion_follows_the_last_deduction_for_the_client(self):
        self.assertEqual(tds.suggestion(bill_code=self.code)["source"], "default")
        billing.record_payment(self.code, "10000", date(2099, 5, 10), self.user, None, None, [{"kind": "TDS", "amount": "900", "section": "194J", "rate": 10}])
        got = tds.suggestion(bill_code=self.code)
        self.assertEqual((got["section"], got["rate"], got["source"]), ("194J", 10.0, "last"))


    def cost_figures(self):
        """Expense and margin for the bill's year as the dashboards work them out, with the bill standing in the warehouse as the load would put it."""
        from app.dashboard import engine

        with billing.db_cursor() as cur:
            cur.execute("SELECT 1 FROM orion_dw.fact_bill WHERE bill_code = %s", (self.code,))
            if not cur.fetchone():
                cur.execute(
                    "INSERT INTO orion_dw.fact_bill (bill_code, case_code, bill_number, bill_date, service_month, status, taxable_total, grand_total) "
                    "VALUES (%s, %s, %s, %s, %s, 'Issued', %s, %s)",
                    (self.code, self.bill["case_code"], self.bill["bill_number"], date(2099, 4, 15), date(2099, 4, 1), self.bill["taxable_total"], self.bill["grand_total"]),
                )
            return engine.period_totals(cur, {"fy": "2099"})

    def test_a_penalty_a_short_payment_and_rounding_are_a_cost_but_tds_is_not(self):
        before = self.cost_figures()
        deductions = [
            {"kind": "TDS", "amount": "200", "section": "194C"},
            {"kind": "Penalty", "amount": "300", "reason": "late delivery"},
            {"kind": "Other", "amount": "100", "reason": "short payment"},
            {"kind": "Rounding", "amount": "0.50"},
        ]
        saved = billing.record_payment(self.code, "10000", date(2099, 5, 10), self.user, None, None, deductions)
        after = self.cost_figures()
        self.assertAlmostEqual(after["expenses"] - before["expenses"], 400.50, places=2)  # 300 + 100 + 0.50, never the 200 of TDS
        self.assertAlmostEqual(before["margin"] - after["margin"], 400.50, places=2)
        self.assertAlmostEqual(after["revenue"], before["revenue"], places=2)  # revenue is still the whole bill
        entry = next(e for e in saved["revenue"]["entries"] if e["status"] == "Committed")
        billing.reverse_payment(self.code, entry["id"], self.user)  # reversing the payment takes the cost away
        self.assertAlmostEqual(self.cost_figures()["margin"], before["margin"], places=2)

    def test_tds_alone_never_reduces_the_margin(self):
        before = self.cost_figures()
        billing.record_payment(self.code, "10000", date(2099, 5, 10), self.user, None, None, [{"kind": "TDS", "amount": "200", "section": "194C"}])
        after = self.cost_figures()
        self.assertAlmostEqual(after["margin"], before["margin"], places=2)
        self.assertAlmostEqual(after["expenses"], before["expenses"], places=2)


class ShortfallIsACostEverywhereTheCostIsRead(unittest.TestCase):
    """What a client holds back that is not TDS reaches Expense and Margin through the view the dashboards read, and nothing else."""

    def view(self):
        sql = (SQL / "dw_schema.sql").read_text(encoding="utf-8")
        return sql[sql.index("CREATE VIEW orion_dw.expense_cost") :]

    def test_the_view_takes_every_kind_but_tds_that_has_not_been_reversed(self):
        branch = self.view().split("FROM orion_ods.bill_payment_deduction d")[1]
        self.assertIn("d.kind <> 'TDS'", branch)
        self.assertIn("d.reversed_timestamp IS NULL", branch)

    def test_the_cost_is_dated_the_day_of_the_payment_and_named_for_the_charts(self):
        from app.dashboard.filters import EXPENSE_TYPE_NAME

        self.assertIn("d.received_date", self.view())
        self.assertIn("SHORTFALL", self.view())
        self.assertIn("Penalties and short payments", EXPENSE_TYPE_NAME)


if __name__ == "__main__":
    unittest.main()
