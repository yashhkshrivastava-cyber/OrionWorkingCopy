"""The profit and loss statement, EPFO and ESIC paid as a cost independent of salary, and the Operating margin.

The first half needs no database. The second half makes a real bill, pays its EPFO and ESIC, and reads the statement, all inside one transaction that is rolled back
at the end (nothing is left behind); it runs only with ORION_DB_TESTS=1:

    $env:ORION_DB_TESTS = "1"; python -m pytest backend/tests/test_profit_and_loss.py
"""

import os
import sys
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app import billing  # noqa: E402

RUN = os.environ.get("ORION_DB_TESTS") == "1"
SQL = ROOT / ".cursor" / "db"


def view_sql() -> str:
    text = (SQL / "dw_schema.sql").read_text(encoding="utf-8")
    return text[text.index("CREATE VIEW orion_dw.expense_cost") :]


class EpfoAndEsicAreACostWhenPaidAndNotLinkedToSalary(unittest.TestCase):
    def test_the_cost_comes_from_the_payments_and_never_from_salary(self):
        sql = view_sql()
        self.assertIn("orion_ods.bill_statutory_payment p", sql)
        self.assertIn("p.reversed_timestamp IS NULL", sql)
        self.assertIn("p.paid_date", sql)  # the day it was paid
        self.assertNotIn("fact_employee_transaction", sql)  # payroll and attendance have nothing to do with it
        self.assertNotIn("salary", sql.lower())

    def test_the_cost_is_named_for_the_charts(self):
        from app.dashboard.filters import EXPENSE_TYPE_NAME

        self.assertIn("EPFO and ESIC paid", EXPENSE_TYPE_NAME)

    def test_the_statement_lines_are_not_called_accrued(self):
        text = (ROOT / "backend" / "app" / "dashboard" / "pnl.py").read_text(encoding="utf-8")
        self.assertIn('"EPFO and ESIC paid"', text)
        self.assertNotIn("accrued", text.split("def profit_and_loss")[1])


class TheHeadlineIsOperatingMargin(unittest.TestCase):
    def test_labels(self):
        from app.dashboard import engine

        text = Path(engine.__file__).read_text(encoding="utf-8")
        self.assertIn('"Operating margin"', text)
        self.assertNotIn('"Contribution margin"', text)


@unittest.skipUnless(RUN, "needs the development database: set ORION_DB_TESTS=1")
class TheStatementAddsUp(unittest.TestCase):
    """A real bill, its EPFO and ESIC paid, a salary line and a few bank entries: each moves exactly the line it should. Read as differences from what is already there."""

    def setUp(self):
        import contextlib

        from app import database
        from test_deductions import FakeConnection

        self.raw = database.raw_connection()
        self.addCleanup(self.raw.close)
        self.addCleanup(self.raw.rollback)
        self.cur = self.raw.cursor()
        self.addCleanup(self.cur.close)

        @contextlib.contextmanager
        def cursor(commit=False):
            cur = self.raw.cursor()
            try:
                yield cur
            finally:
                cur.close()

        saved = (billing.get_connection, billing.db_cursor)
        billing.get_connection = lambda: FakeConnection(self.raw)
        billing.db_cursor = cursor
        self.addCleanup(lambda: (setattr(billing, "get_connection", saved[0]), setattr(billing, "db_cursor", saved[1])))

        cur = self.cur
        cur.execute(
            "SELECT c.case_code, d.case_sk FROM orion_ods.case c JOIN orion_dw.dim_case d ON d.case_code = c.case_code AND d.is_current AND NOT d.is_expired "
            "WHERE c.client_code IS NOT NULL ORDER BY c.case_code LIMIT 1"
        )
        found = cur.fetchone()
        if not found:
            self.skipTest("the development database has no case with a client in the warehouse")
        self.case_code, self.case_sk = found
        cur.execute("SELECT id FROM orion_ods.app_user ORDER BY id LIMIT 1")
        self.user = cur.fetchone()[0]
        today = date.today()
        self.today = today
        self.fy = str(today.year - (1 if today.month < 4 else 0))
        self.before_dash, self.before = self.statement()

    def statement(self, filters=None, bank=True):
        from app.dashboard.engine import Dash
        from app.dashboard.pnl import profit_and_loss

        d = Dash(self.cur, filters or {"fy": self.fy})
        block = profit_and_loss(d, bank)
        return d, {row["label"]: row for row in block["rows"]}

    def make_bill_and_pay_it(self):
        cur = self.cur
        bill = billing.create_bill(
            {"bill_date": self.today, "service_month": self.today.strftime("%Y-%m"), "case_code": self.case_code, "party_name": "P and L Test Ltd",
             "lines": [{"particulars": "Guard", "qty": 10, "rate": 10000}]},
            self.user,
        )
        self.code = bill["id"]
        self.epf, self.esic = Decimal(str(bill["epf_amount"])), Decimal(str(bill["esic_amount"]))
        self.taxable = Decimal(str(bill["taxable_total"]))
        cur.execute(
            "INSERT INTO orion_dw.fact_bill (bill_code, case_sk, case_code, bill_number, bill_date, service_month, status, taxable_total, grand_total, epf_amount, esic_amount) "
            "VALUES (%s, %s, %s, %s, %s, %s, 'Issued', %s, %s, %s, %s)",
            (self.code, self.case_sk, self.case_code, bill["bill_number"], self.today, self.today.replace(day=1), self.taxable, bill["grand_total"], self.epf, self.esic),
        )
        billing.record_statutory_payment(self.code, self.user, confirm=True, seen_paid="0", epfo=self.epf, esic=self.esic, paid_date=self.today, reference="TEST")

    def delta(self, lines, label):
        return round(lines[label]["amount"] - self.before[label]["amount"], 2)

    def test_epfo_and_esic_paid_move_the_cost_and_the_margin_and_nothing_else(self):
        self.make_bill_and_pay_it()
        d, lines = self.statement()
        paid = float(self.epf + self.esic)
        self.assertEqual(self.delta(lines, "Revenue"), float(self.taxable))  # charged to the client: revenue
        self.assertEqual(self.delta(lines, "EPFO and ESIC paid"), paid)  # paid to the authority: a cost, at the bill's case
        self.assertEqual(self.delta(lines, "Payroll at cases"), 0)  # no salary line exists, and none is needed
        self.assertEqual(self.delta(lines, "Head-office EPFO and ESIC paid"), 0)
        self.assertEqual(self.delta(lines, "Direct cost"), paid)
        self.assertEqual(self.delta(lines, "Operating profit"), round(float(self.taxable) - paid, 2))
        self.assertAlmostEqual(d.totals["margin"], lines["Operating profit"]["amount"], places=2)  # the statement and the headline are one number

    def test_salary_is_its_own_line_and_does_not_change_epfo_and_esic(self):
        self.make_bill_and_pay_it()
        _d, with_bill = self.statement()
        self.cur.execute(
            "INSERT INTO orion_dw.fact_employee_transaction (employee_transaction_code, case_sk, employee_code, transaction_date, month_year, salary_amount, salary_paid) "
            "VALUES ('ZZ-PL-E1', %s, 'ZZ', %s, %s, 12000, 'No')",
            (self.case_sk, self.today, self.today.strftime("%Y-%m")),
        )
        _d, with_salary = self.statement()
        self.assertEqual(round(with_salary["Payroll at cases"]["amount"] - with_bill["Payroll at cases"]["amount"], 2), 12000)
        self.assertEqual(with_salary["EPFO and ESIC paid"]["amount"], with_bill["EPFO and ESIC paid"]["amount"])  # unchanged by payroll

    def test_a_reversed_payment_is_not_a_cost(self):
        self.make_bill_and_pay_it()
        batch = billing.get_bill(self.code)["statutory"]["payments"][0]["batch_id"]
        billing.reverse_statutory_payment(self.code, batch, self.user, confirm=True, reason="Test: paid from the wrong account")
        _d, lines = self.statement()
        self.assertEqual(self.delta(lines, "EPFO and ESIC paid"), 0)

    def test_the_bank_lines_come_with_bank_access_only(self):
        self.cur.execute("SELECT MIN(account_id) FROM orion_ods.bank_account")
        account = self.cur.fetchone()[0]
        if account is None:
            self.skipTest("no bank account")
        for category, direction, amount in (("bank_charges", "out", 100), ("interest", "in", 400), ("tax", "out", 900)):
            self.cur.execute(
                "INSERT INTO orion_ods.bank_entry (account_id, entry_date, direction, amount, category) VALUES (%s, %s, %s, %s, %s)",
                (account, self.today, direction, amount, category),
            )
        _d, lines = self.statement(bank=True)
        base = self.before
        self.assertEqual(round(lines["Bank charges"]["amount"] - base["Bank charges"]["amount"], 2), 100)
        self.assertEqual(round(lines["Interest and other income"]["amount"] - base["Interest and other income"]["amount"], 2), 400)
        self.assertEqual(round(lines["Income tax or TDS paid (memo)"]["amount"] - base["Income tax or TDS paid (memo)"]["amount"], 2), 900)  # shown, never deducted
        self.assertEqual(round(lines["Profit before tax"]["amount"] - base["Profit before tax"]["amount"], 2), 300)  # 400 - 100
        _d, hidden = self.statement(bank=False)
        for label in ("Bank charges", "Interest and other income", "Profit before tax", "Income tax or TDS paid (memo)"):
            self.assertNotIn(label, hidden)

    def test_a_client_selection_has_no_bank_lines(self):
        _d, lines = self.statement({"fy": self.fy, "case": "NO-SUCH-CASE"}, bank=True)
        self.assertNotIn("Bank charges", lines)


if __name__ == "__main__":
    unittest.main()
