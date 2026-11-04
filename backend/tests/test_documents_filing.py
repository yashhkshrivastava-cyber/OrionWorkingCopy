"""Documents that Orion files in the Document Center by itself: where bills, employee papers and EMD papers go, that a filed
document cannot be changed by hand, and that the hooks that file them are in place. No database is needed."""

import re
import sys
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app import documents, documents_filing as filing  # noqa: E402
from app.documents import DocumentCenterError  # noqa: E402
from app.entities import DOCUMENTS_FILING_MIGRATE, SQL_MIGRATIONS  # noqa: E402
from app.routers import documents_router  # noqa: E402

BILL = {
    "bill_code": "BILL-0001", "bill_number": "2026-27/1", "bill_date": date(2026, 8, 5), "version_no": 1, "status": "Issued",
    "case_code": "CS-0001", "case_name": "Main gate", "client_code": "CL-0001", "version_by": 1,
}
EMD = {"case_code": "CS-0001", "case_name": "Main gate", "client_code": "CL-0001", "emd_code": "EMD-0001"}
EMPLOYEE = {"employee_code": "EMP-0001", "employee_name": "Asha Rao", "case_code": "CS-0001"}


def every_place(*placed):
    for home, others in placed:
        yield home
        yield from others


class FinancialYears(unittest.TestCase):
    def test_a_day_is_in_the_year_that_starts_in_april(self):
        self.assertEqual(filing.fiscal_year(date(2026, 4, 1)), ("FY2026", "FY 2026-27"))
        self.assertEqual(filing.fiscal_year(date(2027, 3, 31)), ("FY2026", "FY 2026-27"))
        self.assertEqual(filing.fiscal_year(date(2027, 4, 1)), ("FY2027", "FY 2027-28"))
        self.assertEqual(filing.fiscal_year(date(2026, 1, 15)), ("FY2025", "FY 2025-26"))


class WhereThingsAreFiled(unittest.TestCase):
    def test_a_bill_is_at_home_in_its_case_and_also_in_its_clients_billing_folder(self):
        home, others = filing.bill_places(BILL)
        self.assertEqual((home.scope, home.case_code), ("case", "CS-0001"))
        self.assertEqual([name for _key, name in home.steps], ["Billing and payments", "Tax invoices", "FY 2026-27"])
        (client,) = others
        self.assertEqual((client.scope, client.client_code), ("client", "CL-0001"))
        self.assertEqual([name for _key, name in client.steps], ["Billing", "Tax invoices", "Main gate (CS-0001)", "FY 2026-27"])

    def test_an_old_bill_with_no_case_is_at_home_in_its_client(self):
        home, others = filing.bill_places({**BILL, "case_code": None, "case_name": None})
        self.assertEqual((home.scope, home.client_code, others), ("client", "CL-0001", ()))
        self.assertEqual([name for _key, name in home.steps], ["Billing", "Tax invoices", "FY 2026-27"])

    def test_a_case_with_no_client_is_filed_in_the_case_alone(self):
        home, others = filing.bill_places({**BILL, "client_code": None})
        self.assertEqual((home.scope, others), ("case", ()))

    def test_emd_papers_are_in_the_case_under_tender_and_bid_and_in_the_clients_tenders_folder(self):
        home, (client,) = filing.emd_places(EMD)
        self.assertEqual([name for _key, name in home.steps], ["Tender and bid", "EMD and guarantees"])
        self.assertEqual((client.scope, client.client_code), ("client", "CL-0001"))
        self.assertEqual([name for _key, name in client.steps], ["Tenders and EMD", "Main gate (CS-0001)"])

    def test_an_employees_papers_are_in_people_and_hr_and_under_the_site_they_work_at(self):
        home, (case,) = filing.employee_places(EMPLOYEE)
        self.assertEqual(home.scope, "company")
        self.assertEqual([name for _key, name in home.steps], ["People and HR", "Employees", "Asha Rao (EMP-0001)"])
        self.assertEqual((case.scope, case.case_code), ("case", "CS-0001"))
        self.assertEqual([name for _key, name in case.steps], ["Compliance", "Staff records", "Asha Rao (EMP-0001)"])

    def test_an_employee_with_no_site_is_only_in_people_and_hr(self):
        _home, others = filing.employee_places({**EMPLOYEE, "case_code": None})
        self.assertEqual(others, ())

    def test_every_path_fits_the_folder_rules_and_each_key_extends_its_parents(self):
        places = every_place(
            filing.bill_places(BILL), filing.bill_places({**BILL, "case_code": None}), filing.emd_places(EMD), filing.employee_places(EMPLOYEE),
        )
        for place in places:
            self.assertLessEqual(len(place.steps), documents.MAX_FOLDER_DEPTH, place)
            parent = ""
            for key, name in place.steps:
                self.assertTrue(key.startswith(parent), (place, key))
                self.assertEqual(documents.clean_folder_name(name), name)
                parent = key + "/"

    def test_a_long_site_name_still_makes_a_folder_name_that_is_allowed(self):
        name = filing._named("A very long site name " * 10, "CS-0001")
        self.assertLessEqual(len(name), 80)
        self.assertEqual(documents.clean_folder_name(name), name)
        self.assertEqual(filing._named(None, "CS-0001"), "CS-0001")
        self.assertEqual(filing._named("North / South gate", "CS-0002"), "North - South gate (CS-0002)")

    def test_the_category_of_each_kind_exists_where_it_is_at_home(self):
        for source_type, home in (
            (filing.BILL, filing.bill_places(BILL)[0]), (filing.BILL, filing.bill_places({**BILL, "case_code": None})[0]),
            (filing.EMD_DOCUMENT, filing.emd_places(EMD)[0]), (filing.EMPLOYEE_DOCUMENT, filing.employee_places(EMPLOYEE)[0]),
        ):
            self.assertIn(filing.CATEGORY[source_type], documents.CATEGORIES[home.scope], (source_type, home.scope))


class WhenAFileIsNewOrOnlyMoved(unittest.TestCase):
    def test_a_new_bill_version_or_a_cancellation_is_new_content_and_a_rename_is_only_a_new_layout(self):
        base = filing._bill_content(BILL)
        self.assertNotEqual(base, filing._bill_content({**BILL, "version_no": 2}))
        self.assertNotEqual(base, filing._bill_content({**BILL, "status": "Cancelled"}))
        self.assertEqual(base, filing._bill_content({**BILL, "case_name": "Renamed"}))

    def test_a_typeface_or_text_size_is_not_a_change_to_the_filed_bill(self):
        base = filing._bill_content(BILL)
        self.assertEqual(base, filing._bill_content({**BILL, "font_family": "Times New Roman", "font_size": 12}))
        self.assertEqual(base, filing._bill_content({**BILL, "font_size": 10}))

    def test_the_look_of_a_bill_is_its_own_choice_else_the_companys_and_nothing_when_it_is_the_usual_one(self):
        usual = {"font_family": None, "font_size": None}
        self.assertEqual(filing._bill_look(usual, {}), "")
        self.assertEqual(filing._bill_look({"font_family": "arial", "font_size": 9}, {}), "")
        self.assertEqual(filing._bill_look({"font_family": "calibri", "font_size": 12}, {}), "calibri:12.0")
        self.assertEqual(filing._bill_look(usual, {"font_family": "calibri", "font_size": 11}), "calibri:11.0")
        self.assertEqual(filing._bill_look({"font_size": 14}, {"font_family": "calibri", "font_size": 11}), "calibri:14.0")

    def test_a_new_look_changes_the_stored_version_but_not_the_content_that_makes_a_version(self):
        plain = filing.stored_version("1:Issued", "layout")
        looked = filing.stored_version("1:Issued", "layout", "calibri:12.0")
        self.assertEqual(plain, "1:Issued|layout")
        self.assertNotEqual(plain, looked)
        self.assertEqual(plain.split("|", 1)[0], looked.split("|", 1)[0])
        self.assertEqual(looked.partition(filing.LOOK_MARK)[2], "calibri:12.0")
        self.assertEqual(plain.partition(filing.LOOK_MARK)[2], "")

    def test_a_bill_filed_when_the_typeface_counted_is_read_without_it(self):
        old = "3:Issued:Times New Roman:12|CS-0001/Main gate/CL-0001/2026-27/1/2026-08-05"
        self.assertEqual(filing._without_font(old), "3:Issued|CS-0001/Main gate/CL-0001/2026-27/1/2026-08-05")
        self.assertEqual(filing._without_font("3:Issued::10|x"), "3:Issued|x")
        self.assertEqual(filing._without_font("3:Issued|x"), "3:Issued|x")
        self.assertNotEqual(filing._bill_layout(BILL), filing._bill_layout({**BILL, "case_name": "Renamed"}))

    def test_a_source_is_refiled_only_when_it_is_missing_in_the_trash_or_out_of_date(self):
        stored = {"A": ("1|x", False), "B": ("1|x", True), "C": ("0|x", False)}
        self.assertFalse(filing._needs(stored, "A", "1|x"))
        self.assertTrue(filing._needs(stored, "B", "1|x"))
        self.assertTrue(filing._needs(stored, "C", "1|x"))
        self.assertTrue(filing._needs(stored, "D", "1|x"))

    def test_a_rename_brings_the_details_up_to_date_without_touching_the_file_already_filed(self):
        stored = {"BILL-0001": ("1:Issued|CS-0001/Main gate", False)}
        renamed = "1:Issued|CS-0001/Renamed"
        self.assertTrue(filing._needs(stored, "BILL-0001", renamed))
        self.assertTrue(filing._file_is_current(stored, "BILL-0001", renamed))
        # a new bill version, a cancellation, a source that was in the trash or one never filed need the file
        self.assertFalse(filing._file_is_current(stored, "BILL-0001", "2:Issued|CS-0001/Main gate"))
        self.assertFalse(filing._file_is_current(stored, "BILL-0002", renamed))
        self.assertFalse(filing._file_is_current({"BILL-0001": ("1:Issued|x", True)}, "BILL-0001", renamed))
        row = dict(BILL)
        self.assertIsNone(filing._bill_filing(row, with_file=False).data)

    def test_employee_and_emd_papers_are_refiled_when_the_name_or_the_case_changes(self):
        row = {"document_id": 3, "employee_code": "EMP-0001", "doc_type": "Aadhaar card", "title": None, "file_name": "a.pdf", "uploaded_by": 1,
               "uploaded_timestamp": __import__("datetime").datetime(2026, 8, 1, 10, 0), "employee_name": "Asha Rao", "case_code": "CS-0001"}
        first = filing._employee_filing(row, b"x").version
        self.assertNotEqual(first, filing._employee_filing({**row, "case_code": "CS-0002"}, b"x").version)
        self.assertNotEqual(first, filing._employee_filing({**row, "employee_name": "Asha K"}, b"x").version)
        self.assertEqual(first, filing._employee_filing(row, b"y").version)
        self.assertEqual(filing._employee_filing(row, b"x").confidentiality, "Confidential")
        self.assertEqual(filing._employee_filing(row, b"x").source_ref, "EMP-0001:3")


class FiledDocumentsAreNotChangedByHand(unittest.TestCase):
    doc = {"source_type": "bill", "source_ref": "BILL-0001"}

    def test_a_filed_document_says_where_it_came_from(self):
        self.assertEqual(documents.source_of("bill", "BILL-0001"), {"type": "bill", "label": "Bill BILL-0001", "path": "/utility/billing/BILL-0001"})
        self.assertEqual(documents.source_of("employee_document", "EMP-0001:3")["label"], "Employee EMP-0001")
        self.assertEqual(documents.source_of("emd_document", "EMD-0001:3")["label"], "EMD EMD-0001")
        self.assertIsNone(documents.source_of(None, None))
        self.assertIsNone(documents.source_of("something else", "x"))

    def test_changing_deleting_or_re_versioning_one_is_refused_with_the_reason(self):
        with self.assertRaises(DocumentCenterError) as caught:
            documents.refuse_filed(self.doc, "deleted")
        self.assertIn("Bill BILL-0001", str(caught.exception))
        self.assertIn("cannot be deleted here", str(caught.exception))

    def test_a_document_a_person_uploaded_is_not_affected(self):
        documents.refuse_filed({"source_type": None, "source_ref": None}, "deleted")

    def test_every_writer_in_the_document_center_checks(self):
        import inspect

        for function in (documents.update_document, documents.add_version, documents.restore_version, documents.set_deleted, documents.bulk_update):
            self.assertIn("refuse_filed", inspect.getsource(function), function.__name__)

    def test_a_folder_the_filing_keeps_cannot_be_renamed(self):
        import inspect

        self.assertIn("system_key", inspect.getsource(documents.rename_folder))


class FindingDocumentsInAPlace(unittest.TestCase):
    def test_a_case_a_client_and_a_folder_each_match_the_home_or_a_placement(self):
        params: dict = {}
        sql = documents._in_space({"scope": "client", "client_code": "CL-0001", "folder_id": "14"}, params)
        self.assertIn("document_placement", sql)
        self.assertIn("p.client_code = %(client_code)s", sql)
        self.assertEqual(sql.count("WITH RECURSIVE"), 2)  # the folder and what is inside it, for the home and for the placement
        self.assertEqual((params["scope"], params["client_code"], params["folder_id"]), ("client", "CL-0001", 14))

    def test_no_place_is_no_condition_and_a_wrong_place_is_refused(self):
        self.assertIsNone(documents._in_space({}, {}))
        with self.assertRaises(DocumentCenterError):
            documents._in_space({"scope": "elsewhere"}, {})

    def test_documents_outside_any_folder_are_matched_exactly(self):
        sql = documents._in_space({"scope": "case", "case_code": "CS-0001", "folder_id": "none"}, {})
        self.assertIn("d.folder_id IS NULL", sql)

    def test_a_folders_count_includes_the_folders_inside_it(self):
        folders = [
            {"id": 1, "parent_id": None, "name": "Billing", "documents": 0},
            {"id": 2, "parent_id": 1, "name": "Tax invoices", "documents": 0},
            {"id": 3, "parent_id": 2, "name": "FY", "documents": 4},
            {"id": 4, "parent_id": 1, "name": "Other", "documents": 1},
        ]
        counts = {f["id"]: f["documents"] for f in documents._rolled_up(folders)}
        self.assertEqual(counts, {1: 5, 2: 4, 3: 4, 4: 1})


class TheFilingIsHookedIn(unittest.TestCase):
    def test_a_case_a_client_an_employee_and_an_emd_refile_what_depends_on_them(self):
        for name, key in (("Case", "case_code"), ("Client", "client_code"), ("Employee", "employee_code"), ("EMD", "emd_code")):
            with mock.patch.object(filing, "reconcile_quietly") as reconcile:
                filing.entity_saved(name, "X-1")
            reconcile.assert_called_once_with(**{key: "X-1"})
        with mock.patch.object(filing, "reconcile_quietly") as reconcile:
            filing.entity_saved("Transaction", "TRA-1")
            filing.entity_saved("Case", None)
        reconcile.assert_not_called()

    def test_a_failure_while_filing_never_reaches_the_person_who_saved(self):
        with mock.patch.object(filing, "reconcile", side_effect=RuntimeError("database is down")), self.assertLogs(filing.logger, "ERROR"):
            filing.reconcile_quietly(bill_code="BILL-0001")

    def test_bills_employee_papers_and_emd_papers_are_filed_after_they_are_saved(self):
        import inspect

        from app import entity_service
        from app.routers import billing_router, emd_documents_router, employee_documents_router

        for function in (billing_router.create, billing_router.update, billing_router.cancel):
            self.assertIn("documents_filing.reconcile_quietly(", inspect.getsource(function), function.__name__)
        for function in (employee_documents_router.upload_document, employee_documents_router.delete_document,
                         emd_documents_router.upload_document, emd_documents_router.delete_document):
            self.assertIn("documents_filing.reconcile_quietly(", inspect.getsource(function), function.__name__)
        for function in (entity_service.change, entity_service.remove):
            self.assertIn("documents_filing.entity_saved(", inspect.getsource(function), function.__name__)

    def test_the_route_that_updates_the_filing_needs_permission_to_change_documents(self):
        found = [r for r in documents_router.router.routes if r.path.endswith("/filing/update")]
        self.assertEqual(len(found), 1)
        self.assertIn("require_documents_write", {dep.call.__name__ for dep in found[0].dependant.dependencies})

    def test_the_schema_is_applied_with_the_others_and_holds_what_the_code_relies_on(self):
        self.assertIn(DOCUMENTS_FILING_MIGRATE, SQL_MIGRATIONS)
        sql = DOCUMENTS_FILING_MIGRATE.read_text(encoding="utf-8")
        for needed in ("source_type", "source_ref", "source_version", "ux_document_source", "system_key", "document_placement", "ux_document_placement"):
            self.assertIn(needed, sql)
        # The placement's conflict target in documents_filing must be the unique index above, written the same way.
        self.assertIn("COALESCE(case_code, ''), COALESCE(client_code, '')", sql)
        self.assertIsNotNone(re.search(r"ON CONFLICT \(document_id, scope, COALESCE\(case_code, ''\), COALESCE\(client_code, ''\)\)", open(filing.__file__, encoding="utf-8").read()))


if __name__ == "__main__":
    unittest.main()
