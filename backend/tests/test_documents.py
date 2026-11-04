"""The Document Center: what files and details are accepted, how search text and expiry are worked out, who may see
and change documents, and that every route is guarded.

None of this needs a database. Run from the repo root:  python -m pytest backend/tests
"""

import io
import sys
import unittest
import zipfile
from unittest import mock
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from reportlab.pdfgen.canvas import Canvas  # noqa: E402

from app import auth, documents, employee_documents  # noqa: E402
from app.documents import DocumentCenterError  # noqa: E402
from app.routers import documents_router  # noqa: E402

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 40
TODAY = date(2026, 10, 7)


def pdf(words: str) -> bytes:
    out = io.BytesIO()
    canvas = Canvas(out)
    canvas.drawString(72, 700, words)
    canvas.showPage()
    canvas.save()
    return out.getvalue()


def office(path: str, xml: str) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        archive.writestr(path, xml)
    return out.getvalue()


class Files(unittest.TestCase):
    def test_a_real_file_of_a_known_type_is_accepted(self):
        self.assertEqual(documents.check_file("Tender.PDF", pdf("x"))[1:], ("pdf", "application/pdf"))
        self.assertEqual(documents.check_file("site.png", PNG)[2], "image/png")
        self.assertEqual(documents.check_file("notes.txt", b"plain words")[1], "txt")
        self.assertEqual(documents.check_file("slides.pptx", b"PK\x03\x04rest")[1], "pptx")

    def test_the_type_comes_from_the_extension_and_the_first_bytes_must_agree(self):
        with self.assertRaises(DocumentCenterError):
            documents.check_file("evil.pdf", b"<html><script>alert(1)</script>")
        with self.assertRaises(DocumentCenterError):
            documents.check_file("renamed.png", pdf("x"))
        with self.assertRaises(DocumentCenterError):
            documents.check_file("fake.webp", b"RIFF" + b"\x00" * 8 + b"AVI ")

    def test_programs_scripts_and_archives_are_refused(self):
        for name in ("tool.exe", "page.html", "run.js", "bundle.zip", "noextension", "x.svg"):
            with self.assertRaises(DocumentCenterError, msg=name):
                documents.check_file(name, b"MZ0000")

    def test_empty_oversized_and_binary_text_files_are_refused(self):
        with self.assertRaises(DocumentCenterError):
            documents.check_file("a.pdf", b"")
        with mock.patch.object(documents, "MAX_BYTES", 1024), self.assertRaises(DocumentCenterError):
            documents.check_file("a.pdf", b"%PDF-" + b"0" * documents.MAX_BYTES)
        with self.assertRaises(DocumentCenterError):
            documents.check_file("a.txt", b"text\x00\x01\x02")

    def test_folders_in_a_file_name_are_dropped(self):
        self.assertEqual(documents.check_file("C:\\Users\\x\\..\\tender.pdf", pdf("x"))[0], "tender.pdf")

    def test_only_pdf_and_images_are_ever_shown_inline(self):
        self.assertTrue(documents.is_inline("application/pdf"))
        self.assertTrue(documents.is_inline("image/png"))
        for ext in ("txt", "csv", "docx", "xlsx", "pptx"):
            self.assertFalse(documents.is_inline(documents.FILE_TYPES[ext][0]), ext)

    def test_it_accepts_every_kind_of_file_an_employee_document_can_be(self):
        self.assertLessEqual(set(employee_documents.FILE_TYPES), set(documents.FILE_TYPES))

    def test_identical_files_have_the_same_hash(self):
        self.assertEqual(documents.sha256_of(b"abc"), documents.sha256_of(b"abc"))
        self.assertNotEqual(documents.sha256_of(b"abc"), documents.sha256_of(b"abd"))


class SearchText(unittest.TestCase):
    def test_the_words_of_a_pdf_are_found_in_lower_case(self):
        self.assertIn("hospital wing alpha", documents.extract_text("pdf", pdf("Hospital Wing Alpha")))

    def test_the_words_of_office_files_are_found(self):
        word = office("word/document.xml", '<w:document xmlns:w="x"><w:p><w:r><w:t>Master Services</w:t></w:r></w:p></w:document>')
        self.assertIn("master services", documents.extract_text("docx", word))
        sheet = office("xl/sharedStrings.xml", '<sst xmlns="x"><si><t>Guard roster</t></si></sst>')
        self.assertIn("guard roster", documents.extract_text("xlsx", sheet))
        slide = office("ppt/slides/slide1.xml", '<p:sld xmlns:p="x" xmlns:a="y"><a:t>Quarterly review</a:t></p:sld>')
        self.assertIn("quarterly review", documents.extract_text("pptx", slide))
        self.assertIn("a line", documents.extract_text("txt", b"A  line\nof text"))

    def test_a_file_that_cannot_be_read_has_no_words_and_is_still_kept(self):
        self.assertEqual(documents.extract_text("pdf", b"%PDF-1.4 not really"), "")
        self.assertEqual(documents.extract_text("docx", b"PK\x03\x04broken"), "")
        self.assertEqual(documents.extract_text("png", PNG), "")

    def test_a_document_that_declares_entities_is_not_expanded(self):
        bomb = office("word/document.xml", '<!DOCTYPE x [<!ENTITY a "aaaa">]><w:document xmlns:w="x"><w:t>&a;</w:t></w:document>')
        self.assertEqual(documents.extract_text("docx", bomb), "")

    def test_what_is_kept_is_bounded(self):
        self.assertLessEqual(len(documents.extract_text("txt", b"word " * 200_000)), documents.CONTENT_TEXT_LIMIT)


class Details(unittest.TestCase):
    def test_a_title_and_a_category_of_its_space_are_needed(self):
        ok = documents.clean_meta({"title": "  Hospital   tender ", "category": "Tender / RFP"}, "case")
        self.assertEqual(ok["title"], "Hospital tender")
        with self.assertRaises(DocumentCenterError):
            documents.clean_meta({"title": " ", "category": "Tender / RFP"}, "case")
        with self.assertRaises(DocumentCenterError):
            documents.clean_meta({"title": "x", "category": "Tender / RFP"}, "company")
        with self.assertRaises(DocumentCenterError):
            documents.clean_meta({"title": "x" * 151, "category": "Other"}, "company")

    def test_a_partial_change_checks_only_what_is_sent(self):
        self.assertEqual(documents.clean_meta({"status": "Archived"}, "case", partial=True), {"status": "Archived"})
        with self.assertRaises(DocumentCenterError):
            documents.clean_meta({"status": "Bogus"}, "case", partial=True)
        with self.assertRaises(DocumentCenterError):
            documents.clean_meta({"confidentiality": "Secret"}, "case", partial=True)

    def test_tags_are_lower_case_trimmed_and_without_repeats(self):
        self.assertEqual(documents.clean_tags("Hospital, urgent ,  hospital,,"), ["hospital", "urgent"])
        self.assertEqual(documents.clean_tags(["A b", "a  B"]), ["a b"])
        self.assertEqual(documents.clean_tags(None), [])
        with self.assertRaises(DocumentCenterError):
            documents.clean_tags([f"t{n}" for n in range(documents.MAX_TAGS + 1)])
        with self.assertRaises(DocumentCenterError):
            documents.clean_tags(["x" * 31])

    def test_dates_and_the_reminder_are_checked(self):
        meta = documents.clean_meta({"title": "x", "category": "Other", "expiry_date": "2027-03-31", "reminder_days": "45"}, "company")
        self.assertEqual((meta["expiry_date"], meta["reminder_days"]), (date(2027, 3, 31), 45))
        for bad in ({"expiry_date": "31/03/2027"}, {"document_date": "1800-01-01"}, {"reminder_days": "366"},
                    {"reminder_days": "-1"}, {"reminder_days": "soon"}):
            with self.assertRaises(DocumentCenterError, msg=str(bad)):
                documents.clean_meta({"title": "x", "category": "Other", **bad}, "company")
        with self.assertRaises(DocumentCenterError):
            documents.check_dates(date(2026, 5, 1), date(2026, 4, 1))
        documents.check_dates(None, date(2026, 4, 1))

    def test_every_space_has_categories_and_standard_folders(self):
        for scope in documents.SCOPES:
            self.assertIn("Other", documents.CATEGORIES[scope])
            self.assertTrue(documents.STANDARD_FOLDERS[scope])
        self.assertTrue(set(documents.CASE_CHECKLIST) <= set(documents.CATEGORIES["case"]))

    def test_folder_names(self):
        self.assertEqual(documents.clean_folder_name("  Tender   and bid "), "Tender and bid")
        for bad in ("", "a/b", "a\\b", "x" * 81, None):
            with self.assertRaises(DocumentCenterError, msg=str(bad)):
                documents.clean_folder_name(bad)


class UploadedFolders(unittest.TestCase):
    def test_a_path_becomes_clean_names_from_the_top(self):
        plan = documents.plan_folder_paths(["Contracts/ 2025 /Signed  copies", "Contracts"], 4)
        self.assertEqual(plan["Contracts/ 2025 /Signed  copies"], ["Contracts", "2025", "Signed copies"])
        self.assertEqual(plan["Contracts"], ["Contracts"])

    def test_names_deeper_than_there_is_room_for_are_left_out(self):
        self.assertEqual(documents.plan_folder_paths(["a/b/c/d/e/f"], 4)["a/b/c/d/e/f"], ["a", "b", "c", "d"])
        self.assertEqual(documents.plan_folder_paths(["a/b"], 1)["a/b"], ["a"])
        self.assertEqual(documents.plan_folder_paths(["a/b"], 0)["a/b"], [])

    def test_nothing_to_make_or_too_many_or_a_bad_name_is_refused(self):
        for bad in ([], None, "a", [""], ["/"], ["x" * 81], [f"f{n}" for n in range(documents.MAX_FOLDER_PATHS + 1)]):
            with self.assertRaises(DocumentCenterError, msg=str(bad)[:40]):
                documents.plan_folder_paths(bad, 4)


class Expiry(unittest.TestCase):
    def state(self, days, reminder=30, status="Active"):
        return documents.expiry_state(None if days is None else TODAY + timedelta(days=days), reminder, status, TODAY)

    def test_the_four_states(self):
        self.assertEqual(self.state(None), "none")
        self.assertEqual(self.state(-1), "expired")
        self.assertEqual(self.state(0), "expiring")
        self.assertEqual(self.state(30), "expiring")
        self.assertEqual(self.state(31), "valid")

    def test_the_reminder_window_is_the_documents_own(self):
        self.assertEqual(self.state(10, reminder=0), "valid")
        self.assertEqual(self.state(90, reminder=120), "expiring")

    def test_a_document_that_no_longer_matters_raises_no_alert(self):
        self.assertEqual(self.state(-100, status="Superseded"), "none")
        self.assertEqual(self.state(5, status="Archived"), "none")
        self.assertEqual(self.state(-5, status="Draft"), "expired")


class Access(unittest.TestCase):
    def test_documents_is_a_segment_with_a_view_and_a_change_flag(self):
        for flag in ("documents_access", "documents_write"):
            self.assertIn(flag, auth.ACCESS_FLAGS)
        self.assertIn(("documents_write", "documents_access"), auth.WRITE_IMPLIES_ACCESS)
        self.assertTrue(auth._resolved_access("viewer", documents_write=True)["documents_access"])

    def test_admins_and_editors_get_it_by_default_and_viewers_do_not(self):
        self.assertTrue(auth._resolved_access("admin")["documents_write"])
        self.assertTrue(auth._resolved_access("editor")["documents_write"])
        self.assertFalse(auth._resolved_access("viewer")["documents_access"])

    def test_documents_follows_its_own_flags(self):
        reader = {"role": "viewer", "documents_access": True, "documents_write": False}
        self.assertTrue(auth.can_access_page(reader, "documents"))
        self.assertFalse(auth.can_write_documents(reader))
        self.assertFalse(auth.can_access_page(reader, "letterhead"))
        blocked = {"role": "editor", "ods_access": True, "ods_write": True, "documents_access": False, "documents_write": False}
        self.assertFalse(auth.can_access_page(blocked, "documents"))

    def test_confidential_documents_are_for_those_who_may_change_documents_and_admins(self):
        self.assertTrue(documents.can_see_confidential({"role": "admin", "documents_access": True, "documents_write": False}))
        self.assertTrue(documents.can_see_confidential({"role": "editor", "documents_access": True, "documents_write": True}))
        self.assertFalse(documents.can_see_confidential({"role": "viewer", "documents_access": True, "documents_write": False}))
        self.assertFalse(documents.can_see_confidential({"role": "editor", "documents_access": True, "documents_write": False}))

    def test_every_route_has_exactly_one_guard_and_reading_never_needs_the_change_flag(self):
        for route in documents_router.router.routes:
            names = {dep.call.__name__ for dep in route.dependant.dependencies}
            label = f"{sorted(route.methods)[0]} {route.path}"
            self.assertEqual(len(names), 1, f"{label} is guarded by {names}")
            if "GET" in route.methods:
                self.assertEqual(names, {"require_documents"}, label)
            else:
                self.assertEqual(names, {"require_documents_write"}, label)


if __name__ == "__main__":
    unittest.main()
