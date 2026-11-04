"""Input tax credit: the supplier's GSTIN and invoice number on an expense that has GST, the GSTIN check, and the GST position by month.

Everything here needs no database except the last class, which only reads (set ORION_DB_TESTS=1).
"""

import os
import sys
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app import dw_sync, entities, gst_position, gstin  # noqa: E402
from app.payload import PayloadError  # noqa: E402

RUN = os.environ.get("ORION_DB_TESTS") == "1"
SQL = ROOT / ".cursor" / "db"
VALID = "27AAPFU0939F1ZV"
ANOTHER = "24AAACC1206D1ZM"


class GstinTests(unittest.TestCase):
    def test_a_real_number_passes_and_is_tidied(self):
        self.assertEqual(gstin.clean(VALID), VALID)
        self.assertEqual(gstin.clean(" 27aapfu0939f1zv "), VALID)
        self.assertEqual(gstin.clean("27-AAPFU-0939-F1ZV"), VALID)
        self.assertEqual(gstin.clean(ANOTHER), ANOTHER)

    def test_nothing_typed_is_nothing(self):
        for empty in (None, "", "   "):
            self.assertIsNone(gstin.clean(empty))

    def test_a_mistyped_character_fails_the_check_digit(self):
        for wrong in ("27AAPFU0939F1ZW", "27AAPFU0939F1Z0", "27AAPFU0838F1ZV", "28AAPFU0939F1ZV"):
            with self.subTest(wrong=wrong), self.assertRaises(gstin.GstinError):
                gstin.clean(wrong)

    def test_the_wrong_shape_is_refused(self):
        for shape in ("27AAPFU0939F1Z", "27AAPFU0939F1ZVV", "AAAAAAAAAAAAAAA", "27AAPFU0939F0ZV", "27AAPFU0939F1XV", "12345"):
            with self.subTest(shape=shape), self.assertRaises(gstin.GstinError):
                gstin.clean(shape)

    def test_the_check_digit_is_worked_out_from_the_first_fourteen(self):
        self.assertEqual(gstin.check_digit(VALID[:14]), VALID[14])
        self.assertEqual(gstin.check_digit(ANOTHER[:14]), ANOTHER[14])

    def test_the_field_rule_says_it_as_a_payload_error(self):
        rule = entities.ENTITIES["Expense Transaction"]["field_rules"]["vendor_gstin"]
        self.assertEqual(rule(" " + VALID.lower()), VALID)
        with self.assertRaises(PayloadError):
            rule("27AAPFU0939F1ZW")


class ExpenseNeedsSupplierDetailsTests(unittest.TestCase):
    def setUp(self):
        # changing a stored expense also asks the database what has been paid on it; there is no database here
        patch = mock.patch.object(entities, "_paid_on_expense", return_value=0)
        patch.start()
        self.addCleanup(patch.stop)

    def reason(self, cleaned, existing=None, record_id=None):
        return entities.invalid_reason("Expense Transaction", record_id, cleaned, existing)

    def test_an_expense_with_no_gst_needs_nothing(self):
        self.assertIsNone(self.reason({"transaction_amount": 1000, "gst": 0, "transaction_status": "Committed"}))
        self.assertIsNone(self.reason({"transaction_amount": 1000, "transaction_status": "Committed"}))

    def test_an_expense_with_gst_needs_the_gstin_and_the_invoice_number(self):
        base = {"transaction_amount": 1000, "gst": 180, "transaction_status": "Committed"}
        self.assertIn("GSTIN", self.reason(base))
        self.assertIn("invoice number", self.reason({**base, "vendor_gstin": VALID}))
        self.assertIn("GSTIN", self.reason({**base, "vendor_invoice_no": "INV-9"}))
        self.assertIsNone(self.reason({**base, "vendor_gstin": VALID, "vendor_invoice_no": "INV-9"}))

    def test_planned_and_cancelled_expenses_are_still_asked(self):
        base = {"transaction_amount": 1000, "gst": 180}
        self.assertIsNotNone(self.reason({**base, "transaction_status": "Prospective"}))
        self.assertIsNone(self.reason({**base, "transaction_status": "Cancelled"}))

    def test_an_old_expense_can_be_corrected_for_something_else_but_not_its_gst(self):
        old = {"transaction_amount": 1000, "gst": 180, "transaction_status": "Committed", "vendor_gstin": None, "vendor_invoice_no": None}
        # a change of the description or the due day: it keeps its place
        self.assertIsNone(self.reason({"transaction_description": "fixed a typo"}, old, "EXP-0001"))
        self.assertIsNone(self.reason({"gst": 180}, old, "EXP-0001"))
        # the GST itself is changed: now it meets the rule
        self.assertIsNotNone(self.reason({"gst": 200}, old, "EXP-0001"))
        # the person starts giving supplier details: both are needed
        self.assertIn("invoice number", self.reason({"vendor_gstin": VALID}, old, "EXP-0001"))
        self.assertIsNone(self.reason({"vendor_gstin": VALID, "vendor_invoice_no": "INV-1"}, old, "EXP-0001"))

    def test_a_new_expense_is_never_an_old_one(self):
        self.assertIsNotNone(self.reason({"transaction_amount": 1000, "gst": 180, "transaction_status": "Committed"}, None, None))


class PositionTests(unittest.TestCase):
    def test_a_financial_year_runs_april_to_march(self):
        months = gst_position.fy_months(2026)
        self.assertEqual((months[0], months[-1], len(months)), (date(2026, 4, 1), date(2027, 3, 1), 12))

    def test_net_is_the_tax_less_the_credit_and_a_surplus_carries_forward(self):
        out = {date(2026, 4, 1): Decimal("1000"), date(2026, 5, 1): Decimal("500")}
        credit = {date(2026, 4, 1): Decimal("300"), date(2026, 5, 1): Decimal("900"), date(2026, 6, 1): Decimal("50")}
        paid = {date(2026, 5, 1): Decimal("400")}
        got = gst_position.build_position(2026, out, credit, paid, today=date(2026, 6, 15))
        months = {m["month"]: m for m in got["months"]}
        self.assertEqual(months["2026-04-01"]["net"], 700)
        self.assertEqual(months["2026-05-01"]["net"], -400)  # more credit than tax: a credit carried forward
        self.assertEqual(months["2026-05-01"]["running_net"], 300)
        self.assertEqual(months["2026-06-01"]["running_net"], 250)
        self.assertEqual(got["totals"], {"output": 1500.0, "notes": 0.0, "credit": 1250.0, "net": 250.0, "paid": 400.0})
        self.assertEqual([m["future"] for m in got["months"]][:4], [False, False, False, True])
        self.assertEqual(got["fy_label"], "2026-27")


class SchemaContractTests(unittest.TestCase):
    def test_the_file_is_registered_everywhere(self):
        self.assertIn("migrate_input_tax_credit.sql", [p.name for p in entities.SQL_MIGRATIONS])
        self.assertIn("migrate_input_tax_credit.sql", (ROOT / "scripts" / "init_db_mac.sh").read_text(encoding="utf-8"))
        self.assertIn("migrate_input_tax_credit.sql", (ROOT / "scripts" / "init_db_windows.ps1").read_text(encoding="utf-8"))
        sql = (SQL / "migrate_input_tax_credit.sql").read_text(encoding="utf-8")
        for column in ("vendor_gstin", "vendor_invoice_no"):
            self.assertIn(f"ADD COLUMN IF NOT EXISTS {column}", sql)
            self.assertIn(f"ADD COLUMN IF NOT EXISTS {column}", (SQL / "dw_schema.sql").read_text(encoding="utf-8"))

    def test_the_form_and_the_warehouse_carry_the_same_columns(self):
        fields = entities.ENTITIES["Expense Transaction"]["form_fields"]
        spec = dw_sync.FACTS["Expense Transaction"]
        for column in ("vendor_gstin", "vendor_invoice_no"):
            self.assertIn(column, fields)
            self.assertTrue(fields[column]["optional"])  # the rule is in invalid_reason, so an old row and an upload without them are not stopped here
            self.assertIn(column, spec["ods_cols"])
            self.assertIn(column, spec["dw_cols"])
            self.assertIn(column, spec["compare"])


@unittest.skipUnless(RUN, "needs the development database: set ORION_DB_TESTS=1")
class PositionReadsTheDatabaseTests(unittest.TestCase):
    def test_the_position_of_a_year_reads_without_error(self):
        got = gst_position.position(2026)
        self.assertEqual(len(got["months"]), 12)
        self.assertEqual(set(got["totals"]), {"output", "notes", "credit", "net", "paid"})
        self.assertIn("without_gstin", got)


if __name__ == "__main__":
    unittest.main()
