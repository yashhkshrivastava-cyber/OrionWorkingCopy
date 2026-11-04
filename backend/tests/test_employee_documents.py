"""An employee's Aadhaar, PAN and salary, their documents, and who gets to see them. No database is needed."""

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import dw_sync, employee_documents as docs, employee_ids as ids  # noqa: E402
from app.entities import ENTITIES  # noqa: E402
from app.payload import PayloadError, clean_payload  # noqa: E402

AADHAAR = "234567890124"  # a number with a correct check digit; made up, not anyone's card
PDF = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj\n<<>>\nendobj\n"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20
JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 20


class Aadhaar(unittest.TestCase):
    def test_a_number_with_a_correct_check_digit_is_kept_as_digits(self):
        self.assertEqual(ids.clean_aadhaar(AADHAAR), AADHAAR)
        self.assertEqual(ids.clean_aadhaar("2345 6789 0124"), AADHAAR)
        self.assertEqual(ids.clean_aadhaar("2345-6789-0124"), AADHAAR)

    def test_a_mistyped_number_is_refused(self):
        for bad in ("23456789012", "2345678901245", "23456789012A", "234567890125", "034567890124", "134567890124", "abc"):
            with self.assertRaises(PayloadError, msg=bad):
                ids.clean_aadhaar(bad)

    def test_the_message_names_the_field(self):
        with self.assertRaises(PayloadError) as caught:
            ids.clean_aadhaar("1234")
        self.assertIn("Aadhaar Number", str(caught.exception))


class Pan(unittest.TestCase):
    def test_a_pan_is_kept_in_capitals(self):
        self.assertEqual(ids.clean_pan("abcde1234f"), "ABCDE1234F")
        self.assertEqual(ids.clean_pan(" ABCDE 1234 F "), "ABCDE1234F")

    def test_anything_else_is_refused(self):
        for bad in ("ABCDE12345", "ABCD1234F", "12345ABCDE", "ABCDE1234", "ABCDE1234FG"):
            with self.assertRaises(PayloadError, msg=bad):
                ids.clean_pan(bad)


class Salary(unittest.TestCase):
    def test_a_salary_is_a_non_negative_amount_in_rupees_and_paise(self):
        self.assertEqual(ids.clean_salary("18500.555"), 18500.56)
        self.assertEqual(ids.clean_salary(0), 0)
        for bad in (-1, 10_000_001, "nan", "inf", "-inf", float("nan")):
            with self.assertRaises(PayloadError):
                ids.clean_salary(bad)


class TheEmployeeForm(unittest.TestCase):
    entity = ENTITIES["Employee"]

    def test_the_form_tidies_what_is_entered(self):
        cleaned = clean_payload(self.entity, {
            "employee_name": "Asha", "aadhaar_no": "2345 6789 0124", "pan_no": "abcde1234f", "monthly_salary": "18,500",
        })
        self.assertEqual((cleaned["aadhaar_no"], cleaned["pan_no"], cleaned["monthly_salary"]), (AADHAAR, "ABCDE1234F", 18500.0))

    def test_they_are_optional_and_blank_means_none(self):
        cleaned = clean_payload(self.entity, {"employee_name": "Asha", "aadhaar_no": "", "pan_no": None})
        self.assertIsNone(cleaned["aadhaar_no"])
        self.assertIsNone(cleaned["pan_no"])

    def test_a_bad_number_stops_the_save(self):
        with self.assertRaises(PayloadError):
            clean_payload(self.entity, {"employee_name": "Asha", "aadhaar_no": "123"})

    def test_an_update_that_leaves_them_out_does_not_touch_them(self):
        self.assertEqual(clean_payload(self.entity, {"employee_name": "Asha"}, for_update=True), {"employee_name": "Asha"})


class WhoSeesThem(unittest.TestCase):
    entity = ENTITIES["Employee"]
    columns = ["employee_code", "employee_name", "aadhaar_no", "pan_no", "monthly_salary", "created_timestamp"]

    def test_the_private_columns_are_the_ones_on_the_form(self):
        self.assertEqual(self.entity["private_columns"], ["aadhaar_no", "pan_no", "monthly_salary"])
        for column in self.entity["private_columns"]:
            self.assertIn(column, self.entity["form_fields"])

    def test_aadhaar_and_pan_are_never_loaded_into_the_warehouse_but_salary_is(self):
        spec = dw_sync.TABLES["Employee"]
        self.assertEqual(sorted({"aadhaar_no", "pan_no"} & set(spec["ods_cols"])), [])
        self.assertIn("monthly_salary", spec["ods_cols"])
        self.assertIn("monthly_salary", spec["dw_cols"])

    def test_the_warehouse_pages_list_salary_only_for_someone_who_can_change_employees(self):
        meta = dw_sync.TABLES["Employee"]
        self.assertEqual(meta["private_columns"], ["monthly_salary"])
        self.assertIn("monthly_salary", dw_sync.dw_preview(meta, True))
        self.assertNotIn("monthly_salary", dw_sync.dw_preview(meta, False))
        for column in ("aadhaar_no", "pan_no"):  # never loaded, so never listed to anyone
            self.assertNotIn(column, dw_sync.dw_preview(meta, True))

    def test_a_table_with_nothing_private_has_one_preview(self):
        meta = dw_sync.TABLES["Client"]
        self.assertEqual(dw_sync.dw_preview(meta, False), dw_sync.dw_preview(meta, True))

    def test_the_warehouse_preview_routes_choose_by_who_is_asking(self):
        import inspect

        from app.routers import dw_router

        for route in (dw_router.preview_table, dw_router.export_table):
            self.assertIn("dw_preview(meta, can_write_ods(user))", inspect.getsource(route))

    def test_record_history_leaves_out_what_a_reader_may_not_see(self):
        from datetime import datetime, timezone
        from contextlib import contextmanager
        from app import record_history

        def at(day):
            return datetime(2026, 10, day, 10, 0, tzinfo=timezone.utc)

        versions = [
            {"employee_code": "EMP-1", "employee_name": "Asha", "monthly_salary": 15000, "effective_from": at(1),
             "source_created_timestamp": at(1), "source_last_updated_timestamp": at(1), "source_created_by": 1,
             "source_last_updated_by": 1, "is_expired": False},
            {"employee_code": "EMP-1", "employee_name": "Asha K", "monthly_salary": 18000, "effective_from": at(2),
             "source_created_timestamp": at(1), "source_last_updated_timestamp": at(2), "source_created_by": 1,
             "source_last_updated_by": 1, "is_expired": False},
        ]

        class Cursor:
            description = [type("C", (), {"name": name}) for name in versions[0]]
            last = ""

            def execute(self, sql, params=None):
                self.last = sql

            def fetchall(self):
                if "dim_employee" in self.last:
                    return [tuple(v[c.name] for c in self.description) for v in versions]
                return []

            def fetchone(self):
                return None

        @contextmanager
        def fake_cursor(*_a, **_k):
            yield Cursor()

        status = {"last_success": None}
        with mock.patch.object(record_history, "db_cursor", fake_cursor), mock.patch.object(dw_sync, "load_status", lambda: status):
            everything = record_history.record_history("Employee", "EMP-1")
            limited = record_history.record_history("Employee", "EMP-1", hide=set(self.entity["private_columns"]))
        fields = lambda found: {c["field"] for e in found["entries"] for c in e["changes"]}  # noqa: E731
        self.assertEqual(fields(everything), {"employee_name", "monthly_salary"})
        self.assertEqual(fields(limited), {"employee_name"})

    def test_someone_who_can_only_view_does_not_read_them_at_all(self):
        from app.routers.entities_router import _shown_source

        with mock.patch("app.db_utils._columns_for", return_value=self.columns):
            viewer = {"id": 1, "role": "viewer", "ods_access": True, "ods_write": False}
            source = _shown_source(self.entity, viewer)
            self.assertIsNotNone(source)
            for column in self.entity["private_columns"]:
                self.assertNotIn(column, source)
            self.assertIn("employee_name", source)
            editor = {"id": 2, "role": "editor", "ods_access": True, "ods_write": True}
            self.assertIsNone(_shown_source(self.entity, editor))

    def test_an_entity_with_nothing_private_is_untouched(self):
        from app.routers.entities_router import _shown_source

        self.assertIsNone(_shown_source(ENTITIES["Client"], {"id": 1, "role": "viewer", "ods_write": False}))

    def test_every_document_route_needs_permission_to_change_operational_data(self):
        from app.routers import employee_documents_router

        for route in employee_documents_router.router.routes:
            names = {dep.call.__name__ for dep in route.dependant.dependencies}
            self.assertIn("require_ods_write", names, route.path)


class Uploads(unittest.TestCase):
    def ok(self, name="aadhaar.pdf", data=PDF, kind="Aadhaar card", title=None):
        return docs.check_upload(name, data, kind, title)

    def test_a_scan_is_kept_with_its_type_worked_out_here(self):
        kept = self.ok()
        self.assertEqual((kept["content_type"], kept["doc_type"], kept["size_bytes"]), ("application/pdf", "Aadhaar card", len(PDF)))
        self.assertEqual(self.ok("Front.JPG", JPG)["content_type"], "image/jpeg")
        self.assertEqual(self.ok("pan.png", PNG, "PAN card")["content_type"], "image/png")

    def test_a_file_must_be_what_its_name_says(self):
        for name, data in (("scan.pdf", b"MZ\x90\x00 an exe"), ("scan.png", PDF), ("scan.jpg", PNG), ("a.docx", b"%PDF-"), ("a.webp", b"RIFF1234AVI ")):
            with self.assertRaises(docs.DocumentError, msg=name):
                self.ok(name, data)

    def test_only_the_listed_kinds_of_file_are_kept(self):
        for name in ("page.html", "run.exe", "vector.svg", "script.js", "noextension", "archive.zip"):
            with self.assertRaises(docs.DocumentError, msg=name):
                self.ok(name, PDF)

    def test_webp_needs_the_webp_marker(self):
        self.assertEqual(self.ok("a.webp", b"RIFF\x00\x00\x00\x00WEBPVP8 ")["content_type"], "image/webp")

    def test_size_and_emptiness(self):
        with self.assertRaises(docs.DocumentError):
            self.ok(data=b"")
        with self.assertRaises(docs.DocumentError) as caught:
            self.ok(data=PDF + b"\x00" * docs.MAX_BYTES)
        self.assertIn("MB", str(caught.exception))

    def test_the_kind_of_document_must_be_one_of_the_list_and_other_needs_a_title(self):
        with self.assertRaises(docs.DocumentError):
            self.ok(kind="Secret")
        with self.assertRaises(docs.DocumentError):
            self.ok(kind="Other", title="  ")
        self.assertEqual(self.ok(kind="Other", title=" Experience  letter ")["title"], "Experience letter")

    def test_a_file_name_loses_its_folders(self):
        self.assertEqual(docs.clean_file_name("C:\\Users\\x\\scan.pdf"), "scan.pdf")
        self.assertEqual(docs.clean_file_name("../../etc/passwd.pdf"), "passwd.pdf")
        self.assertEqual(len(docs.clean_file_name("a" * 400 + ".pdf")), 150)
        self.assertTrue(docs.clean_file_name("a" * 400 + ".pdf").endswith(".pdf"))

    def test_only_pdf_and_images_are_shown_in_the_browser(self):
        for kind in ("application/pdf", "image/png", "image/jpeg", "image/webp"):
            self.assertTrue(docs.is_inline(kind), kind)
        for kind in ("application/msword", "text/html", "image/svg+xml"):
            self.assertFalse(docs.is_inline(kind), kind)

    def test_other_is_a_choice_and_so_are_the_ones_the_office_asked_for(self):
        for kind in ("Aadhaar card", "PAN card", "Other"):
            self.assertIn(kind, docs.DOC_TYPES)


if __name__ == "__main__":
    unittest.main()
