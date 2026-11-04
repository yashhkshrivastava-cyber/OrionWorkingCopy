"""A bill can be addressed to the client's group instead of the client.

The cases list carries, for a client that belongs to a group, the group's own billing details; the bill editor offers them
as a choice. The bill is still raised for the case's client: only the party printed on it changes.
"""

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app import billing  # noqa: E402

CASE_COLUMNS = [
    "case_code", "case_name", "case_status", "client_code", "client_name", "billing_name", "gstin", "billing_address", "state",
    "group_code", "group_name", "group_billing_name", "group_gstin", "group_billing_address", "group_state",
]


class Column:
    def __init__(self, name):
        self.name = name


class FakeCursor:
    """Answers the three queries list_cases makes, in order."""

    def __init__(self, cases, last_bills, last_parties):
        self.answers = [(CASE_COLUMNS, cases), (["case_code"], last_bills), (["client_code", "party_name", "party_gstin", "party_address", "party_state", "party_fields"], last_parties)]
        self.current = None
        self.sql = []

    def execute(self, sql, params=()):
        self.sql.append(sql)
        self.current = self.answers[len(self.sql) - 1]

    @property
    def description(self):
        return [Column(name) for name in self.current[0]]

    def fetchall(self):
        return self.current[1]


class Context:
    def __init__(self, cursor):
        self.cursor = cursor

    def __enter__(self):
        return self.cursor

    def __exit__(self, *exc):
        return False


def cases_with(rows, last_parties=()):
    cursor = FakeCursor(rows, [], list(last_parties))
    with mock.patch.object(billing, "db_cursor", return_value=Context(cursor)):
        return billing.list_cases(), cursor


class CasesCarryTheClientGroup(unittest.TestCase):
    PLANT = ("CS-1", "Plant 1 - Housekeeping", "Active", "CL-2", "Plant 1", None, None, None, "Madhya Pradesh",
             "CL-1", "Acme Group HQ", "Acme Group Pvt Ltd", "23ABCDE1234F1Z5", "1 Acme Tower, Gwalior", "Madhya Pradesh")
    ALONE = ("CS-2", "Mall - Security", "Active", "CL-3", "Mall", "Mall Pvt Ltd", "23AAAAC3003C1Z3", "AB Road", "Madhya Pradesh",
             None, None, None, None, None, None)

    def test_a_client_in_a_group_gets_the_groups_own_billing_details(self):
        cases, _ = cases_with([self.PLANT])
        group = cases[0]["group"]
        self.assertEqual(group["client_code"], "CL-1")
        self.assertEqual(group["billing_name"], "Acme Group Pvt Ltd")
        self.assertEqual(group["gstin"], "23ABCDE1234F1Z5")
        self.assertEqual(group["billing_address"], "1 Acme Tower, Gwalior")
        # the case still belongs to the client, and its own details are not replaced
        self.assertEqual(cases[0]["client_code"], "CL-2")
        self.assertIsNone(cases[0]["billing_name"])
        self.assertNotIn("group_code", cases[0])

    def test_a_client_that_stands_alone_has_no_group(self):
        cases, _ = cases_with([self.ALONE])
        self.assertIsNone(cases[0]["group"])
        for key in cases[0]:
            self.assertFalse(key.startswith("group_"), key)

    def test_the_groups_last_bill_is_there_for_a_group_with_no_details_of_its_own(self):
        last = [("CL-1", "Acme Group Pvt Ltd", "23ABCDE1234F1Z5", "Tower", "Madhya Pradesh", [])]
        cases, _ = cases_with([self.PLANT], last)
        self.assertEqual(cases[0]["group"]["last_party"]["party_name"], "Acme Group Pvt Ltd")
        self.assertIsNone(cases[0]["last_party"])  # the client itself has not been billed

    def test_the_query_follows_the_clients_group_one_step_not_further(self):
        _, cursor = cases_with([self.PLANT])
        sql = cursor.sql[0]
        self.assertIn("g.client_code = cl.client_group_code", sql)

    def test_the_editor_offers_the_choice_and_keeps_the_bill_on_the_cases_client(self):
        page = (ROOT / "frontend" / "src" / "pages" / "utility" / "BillEditorPage.tsx").read_text(encoding="utf-8")
        self.assertIn("billCase?.group", page)
        self.assertIn("fillParty(billCase, next)", page)


if __name__ == "__main__":
    unittest.main()
