"""The client page's data: who may see the money, and that the figures are the ones the receivables report and the bills register already give. No database.

Run from the repo root:  python -m pytest backend/tests
"""

import sys
import unittest
from contextlib import contextmanager
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app import clients  # noqa: E402
from app.routers import clients_router  # noqa: E402


class Col:
    def __init__(self, name):
        self.name = name


class FakeCursor:
    """Answers each query with the rows scripted for the table it reads, in the order the code asks."""

    def __init__(self, script):
        self.script = script
        self.description = []
        self._rows = []

    def execute(self, sql, params=None):
        for needle, (columns, rows) in self.script.items():
            if needle in sql:
                self.description = [Col(name) for name in columns]
                self._rows = rows
                return
        raise AssertionError(f"unexpected query: {sql[:80]}")

    def fetchall(self):
        return self._rows


def fake_db(script):
    @contextmanager
    def cursor(commit=False):
        yield FakeCursor(script)

    return cursor


PROFILE_SCRIPT = {
    "c.client_group_code, g.client_name AS group_name": (
        ["client_code", "client_name", "client_status", "client_start_date", "client_group_code", "group_name"],
        [("CL-0001", "Civil Surgeon", "Active", date(2024, 4, 1), None, None)],
    ),
    "FROM orion_ods.case cs": (["case_code", "case_name", "case_status"], [("CS-0001", "Hospital", "Active")]),
    "FROM orion_ods.contact": (["contact_code", "contact_name"], [("CON-0001", "A. Verma")]),
    "WHERE client_group_code = %s": (["client_code", "client_name", "client_status"], []),
}

BILLS = [
    {"id": "BILL-2", "bill_number": "2026-27/2", "status": "Issued", "grand_total": 1000.0, "received_total": 400.0, "credited_amount": 100.0, "bill_date": date(2026, 9, 1), "service_month": date(2026, 8, 1), "case_name": "Hospital", "gst_paid": False},
    {"id": "BILL-1", "bill_number": "2026-27/1", "status": "Issued", "grand_total": 500.0, "received_total": 500.0, "credited_amount": 0, "bill_date": date(2026, 8, 1), "service_month": date(2026, 7, 1), "case_name": "Hospital", "gst_paid": True},
    {"id": "BILL-0", "bill_number": "2026-27/0", "status": "Cancelled", "grand_total": 9999.0, "received_total": 0, "credited_amount": 0, "bill_date": date(2026, 7, 1), "service_month": date(2026, 6, 1), "case_name": "Hospital", "gst_paid": False},
]
STATEMENT = {"total": Decimal("500.00"), "oldest_days": 34, "buckets": [Decimal("0"), Decimal("500.00"), Decimal("0"), Decimal("0")], "bucket_labels": ["0-30", "31-60", "61-90", "90+"], "last_reminder": None}


class Profile(unittest.TestCase):
    def test_someone_without_billing_gets_no_money_at_all(self):
        with mock.patch.object(clients, "db_cursor", fake_db(PROFILE_SCRIPT)), mock.patch.object(clients.billing, "list_bills") as bills, mock.patch.object(clients.receivables, "client_statement") as owed:
            found = clients.profile("CL-0001", with_money=False)
        self.assertIsNone(found["money"])
        bills.assert_not_called()
        owed.assert_not_called()
        self.assertEqual(found["client"]["client_name"], "Civil Surgeon")
        self.assertEqual([c["case_code"] for c in found["cases"]], ["CS-0001"])

    def test_the_money_is_the_registers_and_the_receivables_reports(self):
        with mock.patch.object(clients, "db_cursor", fake_db(PROFILE_SCRIPT)), mock.patch.object(clients.billing, "list_bills", return_value=BILLS) as bills, mock.patch.object(clients.receivables, "client_statement", return_value=STATEMENT):
            found = clients.profile("CL-0001", with_money=True)
        bills.assert_called_once_with(client_code="CL-0001", limit=2000)
        money = found["money"]
        self.assertEqual(money["bills"], 2, "a cancelled bill is not counted")
        self.assertEqual(money["billed"], 1500.0)
        self.assertEqual(money["received"], 900.0)
        self.assertEqual(money["credited"], 100.0)
        self.assertEqual(money["owed"], 500.0, "what is owed is the receivables figure, not billed minus received")
        self.assertEqual(money["oldest_days"], 34)
        self.assertEqual(len(money["recent"]), 3)
        self.assertEqual(money["recent"][0]["bill_date"], "2026-09-01")

    def test_a_client_with_nothing_owed_has_a_zero_not_a_gap(self):
        with mock.patch.object(clients, "db_cursor", fake_db(PROFILE_SCRIPT)), mock.patch.object(clients.billing, "list_bills", return_value=[]), mock.patch.object(clients.receivables, "client_statement", return_value=None):
            money = clients.profile("CL-0001", with_money=True)["money"]
        self.assertEqual((money["owed"], money["bills"], money["buckets"]), (0.0, 0, []))

    def test_an_unknown_client_is_none(self):
        script = {**PROFILE_SCRIPT, "c.client_group_code, g.client_name AS group_name": (["client_code"], [])}
        with mock.patch.object(clients, "db_cursor", fake_db(script)):
            self.assertIsNone(clients.profile("CL-9999", with_money=True))


class Routes(unittest.TestCase):
    def test_every_client_route_needs_operational_data_access(self):
        for route in clients_router.router.routes:
            names = {dep.call.__name__ for dep in route.dependant.dependencies}
            self.assertEqual(names, {"require_ods"}, route.path)

    def test_the_directory_adds_what_each_owes_only_for_billing(self):
        rows = [("CL-0001", "Civil Surgeon", "Active", None, None, None, None, None, 1, 1)]
        columns = ["client_code", "client_name", "client_status", "client_type", "firm_priority", "client_location_city", "client_location_state", "group_name", "cases", "active_cases"]
        script = {"FROM orion_ods.client c": (columns, rows)}
        report = {"clients": [{"client_code": "CL-0001", "total": Decimal("250.50"), "oldest_days": 12}]}
        with mock.patch.object(clients, "db_cursor", fake_db(script)), mock.patch.object(clients.receivables, "list_receivables", return_value=report) as listed:
            plain = clients.directory(None, with_money=False)
            listed.assert_not_called()
            rich = clients.directory(None, with_money=True)
        self.assertNotIn("owed", plain[0])
        self.assertEqual((rich[0]["owed"], rich[0]["oldest_days"]), (250.5, 12))


if __name__ == "__main__":
    unittest.main()


class DueToBill(unittest.TestCase):
    """The monthly billing list says how far the month is along, from bills that already exist."""

    def test_the_answer_carries_what_is_already_billed_for_the_month(self):
        from app import billing

        due_columns = ["id", "bill_number", "bill_date", "service_month", "party_name", "grand_total", "location", "case_code", "case_name", "client_code", "client_name"]
        due_row = ("BILL-9", "2026-27/9", date(2026, 8, 31), date(2026, 8, 1), "Civil Surgeon", Decimal("300000"), None, "CS-1", "Hospital", "CL-1", "Civil Surgeon")

        class Cursor(FakeCursor):
            def fetchone(self):
                return (12, Decimal("4500000.50"))

        @contextmanager
        def cursor(commit=False):
            yield Cursor({"SELECT l.bill_code AS id": (due_columns, [due_row]), "COUNT(DISTINCT b.case_code)": (["n", "total"], [(12, Decimal("4500000.50"))])})

        with mock.patch.object(billing, "db_cursor", cursor):
            answer = billing.list_due_to_bill("2026-09")
        self.assertEqual(answer["month"], "2026-09")
        self.assertEqual(answer["billed"], {"cases": 12, "total": 4500000.5})
        self.assertEqual([case["case_code"] for case in answer["cases"]], ["CS-1"])
        self.assertEqual(answer["cases"][0]["months_behind"], 1)
