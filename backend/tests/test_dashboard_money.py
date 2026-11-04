"""The Orion dashboards follow the money rules: cash is what reached the bank (not what a client held back as TDS), credit notes and input tax credit show,
and everything agrees with Billing, Utility > GST and the Bank. No database needed."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app import dw_sync  # noqa: E402
from app.dashboard import engine, explore, filters  # noqa: E402
from app.dashboard.kpi_help import KPI_HELP  # noqa: E402

SQL = ROOT / ".cursor" / "db"
REGISTRY = (ROOT / "frontend" / "src" / "dashboards" / "registry.ts").read_text(encoding="utf-8")
NEW_KPIS = ("credit_notes", "tds_held", "itc", "net_gst")


class CashIsWhatReachedTheBankTests(unittest.TestCase):
    def test_cash_collected_is_the_entry_less_what_the_client_held_back(self):
        self.assertIn("t.amount_after_tax_gst - COALESCE(t.deducted_amount, 0)", engine.COLLECTED)
        self.assertEqual(engine.SETTLED, "COALESCE(SUM(t.amount_after_tax_gst), 0)")
        self.assertIn("t.deducted_amount", engine.TDS_HELD)

    def test_a_collection_rate_counts_what_the_client_held_back_as_settled(self):
        source = (ROOT / "backend" / "app" / "dashboard" / "engine.py").read_text(encoding="utf-8")
        self.assertIn('pair_cash = scalars(cur, "collection", pair, {"v": SETTLED})', source)
        self.assertIn('point["settled"], point["billed"]', source)
        measure = explore.MEASURES["collection_rate"]
        self.assertIs(measure.parts["c"].expr, engine.SETTLED)

    def test_what_a_bill_still_owes_counts_the_whole_entry_and_the_credit(self):
        self.assertIn("b.credited_amount", filters.BILL_OPEN)
        self.assertIn("p.collected", filters.BILL_OPEN)  # collected is the whole entry here: cash and TDS both settle the bill
        self.assertIn("p.deducted", filters.BILL_TDS)
        self.assertIn("p.deducted", filters.BILL_CASH)
        self.assertIn("deducted_amount", filters._BILL_PAYMENTS)

    def test_a_bill_settled_by_a_credit_note_has_its_own_status(self):
        self.assertIn("'Settled'", filters.PAY_STATUS_SQL)
        self.assertEqual(filters.PAY_ORDER, ["Paid", "Settled", "Part paid", "Unpaid"])


class InputTaxCreditAgreesWithTheGstPageTests(unittest.TestCase):
    def test_the_dashboard_counts_the_same_costs_as_utility_gst(self):
        """Incurred, with GST, with both the supplier's GSTIN and invoice number: the rule of gst_position.py."""
        page = (ROOT / "backend" / "app" / "gst_position.py").read_text(encoding="utf-8")
        for condition in ("transaction_status = 'Committed'", "COALESCE(gst, 0) > 0", "vendor_gstin IS NOT NULL", "vendor_invoice_no IS NOT NULL"):
            self.assertIn(condition, page)
        for condition in ("e.transaction_status = 'Committed'", "COALESCE(e.gst, 0) > 0", "e.vendor_gstin IS NOT NULL", "e.vendor_invoice_no IS NOT NULL"):
            self.assertIn(condition, engine.ITC)
        self.assertIn("e.vendor_gstin IS NULL OR e.vendor_invoice_no IS NULL", engine.ITC_MISSING)

    def test_credit_notes_take_the_gst_on_bills_down_the_same_way(self):
        self.assertIn("b.credited_cgst", engine.GST)
        self.assertIn("b.credited_sgst", engine.GST)


class WarehouseCarriesIt(unittest.TestCase):
    def test_the_revenue_entry_carries_what_was_held_back(self):
        spec = dw_sync.FACTS["Case Transaction"]
        for key in ("ods_cols", "dw_cols", "compare"):
            self.assertIn("deducted_amount", spec[key], key)
        self.assertIn("fact_case_transaction ADD COLUMN IF NOT EXISTS deducted_amount", (SQL / "dw_schema.sql").read_text(encoding="utf-8"))

    def test_the_database_keeps_the_total_right_on_every_deduction(self):
        sql = (SQL / "migrate_deductions.sql").read_text(encoding="utf-8")
        self.assertIn("ADD COLUMN IF NOT EXISTS deducted_amount", sql)
        self.assertIn("AFTER INSERT OR UPDATE ON orion_ods.bill_payment_deduction", sql)
        self.assertIn("reversed_timestamp IS NULL", sql.split("bill_payment_deduction_totals() RETURNS", 1)[1].split("$$ LANGUAGE", 1)[0])


class NewFiguresAreShownAndExplainedTests(unittest.TestCase):
    def test_each_new_figure_has_help_and_a_tab(self):
        for key in NEW_KPIS:
            with self.subTest(key=key):
                self.assertIn(key, KPI_HELP)
                self.assertIn(f"'{key}'", REGISTRY)
                self.assertIn(f"{key}:", (ROOT / "frontend" / "src" / "dashboards" / "kpiIcons.tsx").read_text(encoding="utf-8"))

    def test_the_explorer_can_chart_them(self):
        for key in ("tds_held", "credit_notes", "itc"):
            self.assertIn(key, explore.MEASURES)

    def test_the_help_says_credit_notes_and_tds_change_the_old_figures(self):
        self.assertIn("credit notes", KPI_HELP["billed"]["calc"])
        self.assertIn("credit notes", KPI_HELP["revenue"]["calc"])
        self.assertIn("held back", KPI_HELP["collected"]["calc"])
        self.assertIn("held back", KPI_HELP["collection_rate"]["calc"])


if __name__ == "__main__":
    unittest.main()
