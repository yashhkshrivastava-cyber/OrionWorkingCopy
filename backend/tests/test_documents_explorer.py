"""The Document Center as a file explorer: what a place is called, which documents it holds, how a chosen folder changes where a filed
paper is kept, and the rules for moving. No database is needed (a cursor is stubbed where one is read)."""

import inspect
import re
import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from fastapi.routing import APIRoute  # noqa: E402

from app import documents, documents_explorer as explorer, documents_filing as filing  # noqa: E402
from app.documents import DocumentCenterError  # noqa: E402
from app.routers import documents_router  # noqa: E402

FRONTEND = ROOT / "frontend" / "src"
BILL = {
    "bill_code": "BILL-0001", "bill_number": "2026-27/1", "bill_date": date(2026, 8, 5), "version_no": 1, "status": "Issued",
    "case_code": "CS-0001", "case_name": "Main gate", "client_code": "CL-0001", "version_by": 1,
}


class Cursor:
    """Answers each query with the next prepared row."""

    def __init__(self, *rows):
        self.rows = list(rows)
        self.ran: list[str] = []

    def execute(self, sql, params=None):
        self.ran.append(" ".join(sql.split()))

    def fetchone(self):
        return self.rows.pop(0) if self.rows else None


class Nodes(unittest.TestCase):
    def test_only_known_places_are_accepted(self):
        cur = Cursor()
        for bad in ("folder:", "folder:x", "case:", "../etc", "client:CL 1", "folder:1;drop", "FOLDER:1"):
            with self.assertRaises(DocumentCenterError, msg=bad):
                explorer.resolve(cur, bad)

    def test_the_top_levels_need_no_lookup(self):
        for node, trail in (("root", ["Documents"]), ("company", ["Documents", "Company documents"]), ("clients", ["Documents", "Clients"]),
                            ("cases", ["Documents", "Cases"]), ("all", ["Documents", "All documents"]), ("trash", ["Documents", "Trash"])):
            ctx = explorer.resolve(Cursor(), node)
            self.assertEqual([step["label"] for step in ctx["trail"]], trail)

    def test_a_client_is_found_under_clients_and_a_missing_one_is_refused(self):
        ctx = explorer.resolve(Cursor(("Acme",)), "client:CL-0001")
        self.assertEqual([step["id"] for step in ctx["trail"]], ["root", "clients", "client:CL-0001"])
        self.assertEqual((ctx["scope"], ctx["client_code"]), ("client", "CL-0001"))
        with self.assertRaises(DocumentCenterError):
            explorer.resolve(Cursor(), "client:CL-0009")

    def test_a_missing_folder_is_refused_in_words(self):
        with self.assertRaises(DocumentCenterError) as caught:
            explorer.resolve(Cursor(), "folder:12")
        self.assertIn("deleted", str(caught.exception))


class WhatAPlaceHolds(unittest.TestCase):
    def ctx(self, kind, **extra):
        return {"kind": kind, "scope": None, "case_code": None, "client_code": None, "folder_id": None, **extra}

    def test_the_top_levels_hold_documents_only_when_searched(self):
        for kind in ("root", "clients", "cases"):
            self.assertIsNone(explorer._document_filters(self.ctx(kind), False))
            self.assertIsNotNone(explorer._document_filters(self.ctx(kind), True))

    def test_a_folder_shows_its_own_documents_and_a_search_looks_inside_it(self):
        ctx = self.ctx("folder", scope="case", case_code="CS-1", folder_id=7)
        self.assertTrue(explorer._document_filters(ctx, False)["exact"])
        self.assertFalse(explorer._document_filters(ctx, True)["exact"])

    def test_the_top_of_a_space_shows_what_is_not_in_a_folder(self):
        company = explorer._document_filters(self.ctx("company", scope="company"), False)
        self.assertEqual(company, {"scope": "company", "folder_id": "none"})
        case = explorer._document_filters(self.ctx("case", scope="case", case_code="CS-1"), False)
        self.assertEqual(case, {"case_code": "CS-1", "scope": "case", "folder_id": "none"})
        client = explorer._document_filters(self.ctx("client", scope="client", client_code="CL-1"), False)
        self.assertEqual(client, {"client_code": "CL-1", "scope": "client", "folder_id": "none"})

    def test_searching_a_client_includes_its_cases_papers(self):
        found = explorer._document_filters(self.ctx("client", scope="client", client_code="CL-1"), True)
        self.assertEqual(found, {"client_code": "CL-1"})  # no scope, so the client's cases count too (documents._in_space)

    def test_the_exact_filter_stops_at_the_folder(self):
        params: dict = {}
        sql = documents._in_space({"scope": "case", "case_code": "CS-1", "folder_id": "5", "exact": True}, params)
        self.assertNotIn("WITH RECURSIVE", sql)
        self.assertIn("d.folder_id = %(folder_id)s", sql)
        self.assertIn("p.folder_id = %(folder_id)s", documents._in_space({"folder_id": "5", "exact": True}, {}))
        self.assertIn("WITH RECURSIVE", documents._in_space({"scope": "case", "case_code": "CS-1", "folder_id": "5"}, {}))


class AChosenFolder(unittest.TestCase):
    def test_nothing_chosen_changes_nothing(self):
        home, others = filing.bill_places(BILL)
        self.assertEqual(filing._choose(home, others, None), (home, others))
        self.assertEqual(filing._choice_key(None), "")

    def test_a_folder_in_the_cases_space_replaces_the_usual_home_and_the_client_keeps_it(self):
        home, others = filing.bill_places(BILL)
        chosen, kept = filing._choose(home, others, ("case", "CS-0001", None, 42))
        self.assertEqual((chosen.scope, chosen.case_code, chosen.folder_id), ("case", "CS-0001", 42))
        self.assertEqual([place.scope for place in kept], ["client"])

    def test_a_folder_in_the_clients_space_leaves_the_case_as_a_placement(self):
        home, others = filing.bill_places(BILL)
        chosen, kept = filing._choose(home, others, ("client", None, "CL-0001", 9))
        self.assertEqual((chosen.scope, chosen.client_code, chosen.folder_id), ("client", "CL-0001", 9))
        self.assertEqual([place.scope for place in kept], ["case"])  # the usual client place goes, the usual case place stays

    def test_a_company_folder_keeps_both_usual_places(self):
        home, others = filing.bill_places(BILL)
        chosen, kept = filing._choose(home, others, ("company", None, None, 3))
        self.assertEqual(chosen.scope, "company")
        self.assertEqual([place.scope for place in kept], ["case", "client"])

    def test_a_chosen_place_is_not_made_from_steps(self):
        place = filing.Place("case", case_code="CS-1", folder_id=42, steps=(("a", "A"),))
        self.assertEqual(filing._ensure_folders(None, place), 42)  # no cursor is touched

    def test_the_choice_is_part_of_the_layout_so_changing_it_files_the_bill_again(self):
        base = filing._bill_layout({**BILL})
        chosen = filing._bill_layout({**BILL, "choice": ("case", "CS-0001", None, 42)})
        self.assertNotEqual(base, chosen)
        self.assertTrue(chosen.startswith(base))
        stored_version = f"{filing._bill_content(BILL)}|{base}"
        self.assertTrue(filing._file_is_current({"BILL-0001": (stored_version, False)}, "BILL-0001", f"{filing._bill_content(BILL)}|{chosen}"))

    def test_other_filed_papers_follow_a_choice_too(self):
        row = {"employee_code": "EMP-1", "employee_name": "Asha", "case_code": "CS-1", "title": "", "doc_type": "PAN", "document_id": 1,
               "file_name": "a.pdf", "uploaded_timestamp": __import__("datetime").datetime(2026, 1, 1), "uploaded_by": 1}
        plain = filing._employee_filing(row, None)
        chosen = filing._employee_filing({**row, "choice": ("company", None, None, 5)}, None)
        self.assertNotEqual(plain.layout, chosen.layout)
        self.assertEqual(chosen.home.folder_id, 5)


class Moving(unittest.TestCase):
    def test_a_folder_kept_by_orion_cannot_be_moved(self):
        cur = Cursor(("case", "CS-1", None, None, "Tax invoices", "billing/invoices"))
        with self.assertRaises(DocumentCenterError) as caught:
            documents.move_folder(cur, 3, ("case", "CS-1", None, None), "Case")
        self.assertIn("kept by Orion", str(caught.exception))

    def test_a_folder_cannot_leave_its_own_case_client_or_company(self):
        cur = Cursor(("case", "CS-1", None, None, "Mine", None))
        with self.assertRaises(DocumentCenterError) as caught:
            documents.move_folder(cur, 3, ("company", None, None, None), "Company documents")
        self.assertIn("different case, client or the company", str(caught.exception))

    def test_moving_where_it_already_is_does_nothing(self):
        cur = Cursor(("company", None, None, 4, "Mine", None))
        documents.move_folder(cur, 3, ("company", None, None, 4), "Policies")
        self.assertEqual(len(cur.ran), 1)  # only the lookup

    def test_a_folder_cannot_be_moved_into_itself(self):
        cur = Cursor(("company", None, None, None, "Mine", None), (3, None, "Mine"))
        with self.assertRaises(DocumentCenterError) as caught:
            documents.move_folder(cur, 3, ("company", None, None, 3), "Mine")
        self.assertIn("into itself", str(caught.exception))

    def test_only_a_destination_can_be_moved_to(self):
        for node in ("root", "clients", "cases", "all", "trash"):
            with self.assertRaises(DocumentCenterError):
                explorer.destination_of(Cursor(), node)

    def test_nothing_chosen_is_refused(self):
        with self.assertRaises(DocumentCenterError):
            documents.move_items(1, [], [], ("company", None, None, None), "Company", True)
        with self.assertRaises(DocumentCenterError):
            documents.move_items(1, list(range(201)), [], ("company", None, None, None), "Company", True)


class TheRoutes(unittest.TestCase):
    def test_every_explorer_route_has_a_permission_dependency(self):
        wanted = {"/documents/browse", "/documents/move", "/documents/source/{source_type}/{source_ref:path}", "/documents/filing/preview"}
        found = {route.path: route for route in documents_router.router.routes if isinstance(route, APIRoute)}
        for path in wanted:
            self.assertIn(path, found)
            self.assertTrue(found[path].dependant.dependencies, path)

    def test_changing_things_needs_permission_to_change_documents(self):
        source = inspect.getsource(documents_router)
        for name in ("def move", "def choose_source_home"):
            block = source[source.index(name):].split("\n\n\n")[0]
            self.assertIn("require_documents_write", block, name)

    def test_the_bill_form_names_a_filing_node_and_checks_the_permission_first(self):
        from app.routers import billing_router

        self.assertIn("filing_node", billing_router.BillIn.model_fields)
        source = inspect.getsource(billing_router.create)
        self.assertLess(source.index("can_write_documents"), source.index("billing.create_bill"))


class TheScreens(unittest.TestCase):
    def test_the_choice_table_is_in_the_schema_and_granted(self):
        sql = (ROOT / ".cursor" / "db" / "migrate_documents_filing.sql").read_text(encoding="utf-8")
        self.assertIn("document_filing_choice", sql)
        self.assertRegex(sql, r"GRANT ALL ON orion_ods\.document_filing_choice TO orion_user")
        self.assertIn("ON DELETE CASCADE", sql[sql.index("document_filing_choice"):])

    def test_the_page_reads_the_nodes_the_server_names(self):
        page = (FRONTEND / "pages" / "documents" / "DocumentCenterPage.tsx").read_text(encoding="utf-8")
        for node in ("'home'", "'all'", "'trash'", "'root'", "'clients'", "'cases'", "'company'"):
            self.assertIn(node, page)
        types = (FRONTEND / "types.ts").read_text(encoding="utf-8")
        kinds = re.search(r"export type ExplorerKind = ([^\n]+)", types).group(1)
        for kind in ("root", "company", "clients", "cases", "client", "case", "folder", "all", "trash"):
            self.assertIn(f"'{kind}'", kinds)


if __name__ == "__main__":
    unittest.main()
