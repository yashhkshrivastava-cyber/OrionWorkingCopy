"""The case, employee and account pages' data: who may see the money and the pay, that nothing private is read, and that the figures are the ones the receivables report already gives. No database.

Run from the repo root:  python -m pytest backend/tests
"""

import inspect
import sys
import unittest
from contextlib import contextmanager
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app import cases, employees, user_overview  # noqa: E402
from app.routers import cases_router, employees_router, users_router  # noqa: E402


class Col:
    def __init__(self, name):
        self.name = name


class FakeCursor:
    """Answers each query with the rows scripted for the table it reads."""

    def __init__(self, script):
        self.script = script
        self.description = []
        self._rows = []
        self.asked = []

    def execute(self, sql, params=None):
        self.asked.append(sql)
        for needle, (columns, rows) in self.script.items():
            if needle in sql:
                self.description = [Col(name) for name in columns]
                self._rows = rows
                return
        raise AssertionError(f"unexpected query: {sql[:90]}")

    def fetchall(self):
        return self._rows


def fake_db(script, record=None):
    @contextmanager
    def cursor(commit=False):
        cur = FakeCursor(script)
        if record is not None:
            record.append(cur)
        yield cur

    return cursor


CASE_SCRIPT = {
    "LEFT JOIN orion_ods.capability cap": (["case_code", "case_name", "client_code", "client_name"], [("CS-1", "Hospital", "CL-1", "Civil Surgeon")]),
    "WHERE employee_case_code = %s": (["employee_code", "employee_name"], [("EMP-1", "A. Rathore")]),
    "FROM orion_ods.contact": (["contact_code", "contact_name"], [("CON-1", "A. Verma")]),
    "FROM orion_ods.emd": (["emd_code", "emd_amount"], [("EMD-1", Decimal("5000"))]),
    "COALESCE(SUM(amount_after_tax_gst), 0)": (["total", "count"], [(Decimal("1200.50"), 3)]),
    "FROM orion_ods.expense_transaction x": (["expense_code", "amount"], [("EXT-1", Decimal("400"))]),
}
BILLS = [
    {"id": "B2", "bill_number": "2026-27/2", "status": "Issued", "grand_total": 1000.0, "received_total": 400.0, "credited_amount": 100.0, "bill_date": date(2026, 9, 1), "service_month": date(2026, 8, 1), "case_name": "Hospital", "gst_paid": False},
    {"id": "B0", "bill_number": "2026-27/0", "status": "Cancelled", "grand_total": 9999.0, "received_total": 0, "credited_amount": 0, "bill_date": date(2026, 7, 1), "service_month": date(2026, 6, 1), "case_name": "Hospital", "gst_paid": False},
]
REPORT = {"clients": [{"client_code": "CL-1", "bills": [
    {"case_code": "CS-1", "balance": Decimal("500"), "days": 34},
    {"case_code": "CS-1", "balance": Decimal("250.50"), "days": 61},
    {"case_code": "CS-2", "balance": Decimal("9999"), "days": 300},
]}]}


class CaseProfile(unittest.TestCase):
    def test_no_billing_means_no_money_is_read(self):
        with mock.patch.object(cases, "db_cursor", fake_db(CASE_SCRIPT)), mock.patch.object(cases.billing, "list_bills") as bills, mock.patch.object(cases.receivables, "list_receivables") as owed:
            found = cases.profile("CS-1", with_money=False)
        self.assertIsNone(found["money"])
        bills.assert_not_called()
        owed.assert_not_called()
        self.assertEqual(found["expenses"], {"total": 1200.5, "count": 3, "recent": [{"expense_code": "EXT-1", "amount": 400.0}]})

    def test_what_a_case_owes_is_the_receivables_balances_of_its_own_bills_only(self):
        with mock.patch.object(cases, "db_cursor", fake_db(CASE_SCRIPT)), mock.patch.object(cases.billing, "list_bills", return_value=BILLS) as bills, mock.patch.object(cases.receivables, "list_receivables", return_value=REPORT):
            money = cases.profile("CS-1", with_money=True)["money"]
        bills.assert_called_once_with(case_code="CS-1", limit=2000)
        self.assertEqual((money["bills"], money["billed"], money["received"], money["credited"]), (1, 1000.0, 400.0, 100.0), "a cancelled bill is not counted")
        self.assertEqual((money["owed"], money["oldest_days"]), (750.5, 61), "only the case's own bills, from the receivables report")

    def test_a_case_that_owes_nothing_has_a_zero(self):
        with mock.patch.object(cases, "db_cursor", fake_db(CASE_SCRIPT)), mock.patch.object(cases.billing, "list_bills", return_value=[]), mock.patch.object(cases.receivables, "list_receivables", return_value={"clients": []}):
            money = cases.profile("CS-1", with_money=True)["money"]
        self.assertEqual((money["owed"], money["oldest_days"]), (0.0, None))

    def test_an_unknown_case_is_none(self):
        script = {**CASE_SCRIPT, "LEFT JOIN orion_ods.capability cap": (["case_code"], [])}
        with mock.patch.object(cases, "db_cursor", fake_db(script)):
            self.assertIsNone(cases.profile("CS-9", with_money=True))


EMPLOYEE_SCRIPT = {
    "LEFT JOIN orion_ods.employee m ON m.employee_code = e.manager_code\n              LEFT JOIN orion_ods.case cs": (["employee_code", "employee_name"], [("EMP-1", "A. Rathore")]),
    "WHERE manager_code = %s": (["employee_code", "employee_name"], []),
    "relationship_owner_code": (["contact_code", "contact_name", "client_code"], []),
    "FROM orion_ods.employee_transaction": (["month_year", "days_worked", "salary_amount", "salary_paid"], [("2026-09", Decimal("30"), Decimal("15000"), "Yes")]),
}


class EmployeeProfile(unittest.TestCase):
    def test_pay_is_read_only_when_asked_for(self):
        seen = []
        with mock.patch.object(employees, "db_cursor", fake_db(EMPLOYEE_SCRIPT, seen)):
            plain = employees.profile("EMP-1", with_pay=False)
            paid = employees.profile("EMP-1", with_pay=True)
        self.assertIsNone(plain["pay"])
        self.assertFalse(any("employee_transaction" in sql for sql in seen[0].asked), "no salary line is read without the right")
        self.assertEqual(paid["pay"], [{"month_year": "2026-09", "days_worked": 30.0, "salary_amount": 15000.0, "salary_paid": "Yes"}])

    def test_the_private_columns_are_never_selected(self):
        source = inspect.getsource(employees)
        for column in ("aadhaar_no", "pan_no", "monthly_salary"):
            self.assertNotIn(column, source)

    def test_an_unknown_employee_is_none(self):
        script = {**EMPLOYEE_SCRIPT, "LEFT JOIN orion_ods.employee m ON m.employee_code = e.manager_code\n              LEFT JOIN orion_ods.case cs": (["employee_code"], [])}
        with mock.patch.object(employees, "db_cursor", fake_db(script)):
            self.assertIsNone(employees.profile("EMP-9", with_pay=False))


class Account(unittest.TestCase):
    def test_the_overview_never_selects_the_cookie_token(self):
        self.assertNotIn("token_id", inspect.getsource(user_overview))

    def test_the_overview_is_for_administrators_only(self):
        for route in users_router.router.routes:
            if route.path.endswith("/overview"):
                self.assertEqual({dep.call.__name__ for dep in route.dependant.dependencies}, {"require_admin"})
                return
        self.fail("there is no overview route")


class Routes(unittest.TestCase):
    def test_case_and_employee_routes_need_operational_data_access(self):
        for router in (cases_router.router, employees_router.router):
            for route in router.routes:
                self.assertEqual({dep.call.__name__ for dep in route.dependant.dependencies}, {"require_ods"}, route.path)


if __name__ == "__main__":
    unittest.main()
