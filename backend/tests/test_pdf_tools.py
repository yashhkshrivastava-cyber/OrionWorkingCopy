"""The PDF tools: the page language, every tool on real PDFs made here, the limits, locked and damaged files, and the endpoints.

No database is needed: the files are made in memory with reportlab and Pillow, and the endpoints are called with a person's
permissions set in the user record (so a route that forgot its permission check would let the person without any in).
"""

import io
import json
import sys
import threading
import unittest
import zipfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image  # noqa: E402
from pypdf import PdfReader  # noqa: E402
from reportlab.pdfgen import canvas  # noqa: E402

from app import dependencies, pdf_tools  # noqa: E402
from app.routers import pdf_tools_router  # noqa: E402

A4 = (595.28, 841.89)


def make_pdf(pages: int = 3, label: str = "A", size: tuple[float, float] = A4) -> bytes:
    out = io.BytesIO()
    sheet = canvas.Canvas(out, pagesize=size)
    for number in range(1, pages + 1):
        sheet.drawString(72, size[1] - 72, f"{label} page {number}")
        sheet.showPage()
    sheet.save()
    return out.getvalue()


def texts(data: bytes) -> list[str]:
    return [page.extract_text().strip() for page in PdfReader(io.BytesIO(data)).pages]


def reader(data: bytes) -> PdfReader:
    return PdfReader(io.BytesIO(data))


def photo(width: int = 1600, height: int = 1200, *, orientation: int | None = None, kind: str = "JPEG") -> bytes:
    picture = Image.effect_noise((width, height), 70).convert("RGB")
    out = io.BytesIO()
    if kind == "JPEG":
        exif = Image.Exif()
        if orientation:
            exif[0x0112] = orientation
        picture.save(out, "JPEG", quality=92, exif=exif)
    else:
        picture.save(out, kind)
    return out.getvalue()


def image_pdf(width: int = 2400, height: int = 1800) -> bytes:
    from reportlab.lib.utils import ImageReader

    out = io.BytesIO()
    sheet = canvas.Canvas(out, pagesize=A4)
    sheet.drawImage(ImageReader(io.BytesIO(photo(width, height))), 20, 20, width=550, height=400)
    sheet.showPage()
    sheet.save()
    return out.getvalue()


def locked(data: bytes, password: str = "secret1") -> bytes:
    return pdf_tools.protect([("a.pdf", data)], {"new_password": password}).data


def run(tool: str, files, **options):
    return pdf_tools.run(tool, [(name, data) for name, data in files], options)


class ThePageLanguage(unittest.TestCase):
    def test_what_each_way_of_writing_pages_means(self):
        cases = [
            ("1-3", 10, [0, 1, 2]),
            ("1-3, 5", 10, [0, 1, 2, 4]),
            ("1-3;5", 10, [0, 1, 2, 4]),
            ("8-", 10, [7, 8, 9]),
            ("-3", 10, [0, 1, 2]),
            ("last", 10, [9]),
            ("5-last", 10, [4, 5, 6, 7, 8, 9]),
            ("5-1", 5, [4, 3, 2, 1, 0]),
            ("odd", 5, [0, 2, 4]),
            ("even", 5, [1, 3]),
            ("1 - 3   5", 10, [0, 1, 2, 4]),
            ("2,2", 3, [1, 1]),
            ("  7 ", 7, [6]),
            ("ALL", 3, [0, 1, 2]),
            ("", 4, [0, 1, 2, 3]),
            (None, 2, [0, 1]),
        ]
        for spec, total, expected in cases:
            with self.subTest(spec=spec):
                self.assertEqual(pdf_tools.parse_pages(spec, total), expected)

    def test_a_page_that_is_not_there_or_a_muddle_is_said_in_words(self):
        for spec in ("0", "11", "a", "1-2-3", "-", "3-99", "1..3", "9999999", "1,,x", "-0"):
            with self.subTest(spec=spec), self.assertRaises(pdf_tools.PdfToolError) as caught:
                pdf_tools.parse_pages(spec, 10)
            self.assertTrue(str(caught.exception))
        with self.assertRaises(pdf_tools.PdfToolError) as caught:
            pdf_tools.parse_pages("11", 10, label="Invoice.pdf")
        self.assertIn("Invoice.pdf has 10 pages", str(caught.exception))

    def test_nothing_written_is_every_page_unless_the_tool_needs_a_choice(self):
        with self.assertRaises(pdf_tools.PdfToolError):
            pdf_tools.parse_pages("", 5, empty_is_all=False)

    def test_an_enormous_list_is_refused(self):
        with self.assertRaises(pdf_tools.PdfToolError):
            pdf_tools.parse_pages(",".join(["1-1000"] * 5), 1000)

    def test_groups_are_the_comma_separated_parts(self):
        self.assertEqual(pdf_tools.parse_groups("1-3, 4, 7-", 9), [[0, 1, 2], [3], [6, 7, 8]])
        with self.assertRaises(pdf_tools.PdfToolError):
            pdf_tools.parse_groups("1 3", 9)
        with self.assertRaises(pdf_tools.PdfToolError):
            pdf_tools.parse_groups("", 9)


class Merging(unittest.TestCase):
    def test_pdfs_join_in_the_order_given(self):
        result = run("merge", [("one.pdf", make_pdf(3, "A")), ("two.pdf", make_pdf(2, "B"))])
        self.assertEqual(result.pages, 5)
        self.assertEqual(texts(result.data), ["A page 1", "A page 2", "A page 3", "B page 1", "B page 2"])
        self.assertEqual(result.filename, "Merged.pdf")

    def test_each_file_can_give_only_some_of_its_pages(self):
        result = run("merge", [("one.pdf", make_pdf(5, "A")), ("two.pdf", make_pdf(4, "B"))], ranges=["2-3", "last"])
        self.assertEqual(texts(result.data), ["A page 2", "A page 3", "B page 4"])

    def test_a_file_can_be_put_first_by_listing_it_first_and_a_page_repeated(self):
        result = run("merge", [("b.pdf", make_pdf(1, "B")), ("a.pdf", make_pdf(1, "A"))], ranges=["1,1", ""])
        self.assertEqual(texts(result.data), ["B page 1", "B page 1", "A page 1"])

    def test_each_file_becomes_a_bookmark_unless_that_is_switched_off(self):
        marked = reader(run("merge", [("Invoice March.pdf", make_pdf(2)), ("Receipt.pdf", make_pdf(1))]).data)
        self.assertEqual([item.title for item in marked.outline], ["Invoice March", "Receipt"])
        plain = reader(run("merge", [("a.pdf", make_pdf(1)), ("b.pdf", make_pdf(1))], bookmarks=False).data)
        self.assertEqual(list(plain.outline), [])

    def test_a_locked_file_is_merged_with_its_password(self):
        files = [("a.pdf", locked(make_pdf(2, "A"))), ("b.pdf", make_pdf(1, "B"))]
        with self.assertRaises(pdf_tools.PdfToolError) as caught:
            run("merge", files)
        self.assertIn("a.pdf", str(caught.exception))
        self.assertIn("password", str(caught.exception))
        with self.assertRaises(pdf_tools.PdfToolError) as caught:
            run("merge", files, passwords=["wrong", ""])
        self.assertIn("does not open", str(caught.exception))
        self.assertEqual(texts(run("merge", files, passwords=["secret1", ""]).data), ["A page 1", "A page 2", "B page 1"])

    def test_the_result_is_not_locked_and_opens(self):
        merged = reader(run("merge", [("a.pdf", make_pdf(1)), ("b.pdf", make_pdf(1))]).data)
        self.assertFalse(merged.is_encrypted)
        self.assertEqual(len(merged.pages), 2)

    def test_one_file_is_not_a_merge(self):
        with self.assertRaises(pdf_tools.PdfToolError):
            run("merge", [("a.pdf", make_pdf(1))])

    def test_a_merge_that_would_be_too_long_is_refused(self):
        with mock.patch.object(pdf_tools, "MAX_PAGES", 5), self.assertRaises(pdf_tools.PdfToolError) as caught:
            run("merge", [("a.pdf", make_pdf(3)), ("b.pdf", make_pdf(3))])
        self.assertIn("more than 5 pages", str(caught.exception))


class Splitting(unittest.TestCase):
    def archive(self, result):
        return zipfile.ZipFile(io.BytesIO(result.data))

    def test_by_ranges_each_part_is_one_file(self):
        result = run("split", [("Report.pdf", make_pdf(8))], mode="ranges", ranges="1-3, 4, 6-")
        self.assertEqual(result.files, 3)
        names = self.archive(result).namelist()
        self.assertEqual(names, ["Report - part 1 (pages 1-3).pdf", "Report - part 2 (pages 4).pdf", "Report - part 3 (pages 6-8).pdf"])
        self.assertEqual(len(reader(self.archive(result).read(names[2])).pages), 3)
        self.assertEqual(result.media_type, "application/zip")

    def test_every_n_pages_and_a_file_for_each_page(self):
        by_three = run("split", [("a.pdf", make_pdf(7))], mode="every", every=3)
        self.assertEqual([len(reader(self.archive(by_three).read(n)).pages) for n in self.archive(by_three).namelist()], [3, 3, 1])
        single = run("split", [("a.pdf", make_pdf(4))], mode="single")
        self.assertEqual(single.files, 4)

    def test_the_parts_hold_the_right_pages(self):
        result = run("split", [("a.pdf", make_pdf(6))], mode="ranges", ranges="5-6, 1-2")
        first, second = (self.archive(result).read(n) for n in self.archive(result).namelist())
        self.assertEqual(texts(first), ["A page 5", "A page 6"])
        self.assertEqual(texts(second), ["A page 1", "A page 2"])

    def test_a_pdf_that_cannot_be_split_says_so(self):
        with self.assertRaises(pdf_tools.PdfToolError):
            run("split", [("a.pdf", make_pdf(1))], mode="every", every=5)
        with self.assertRaises(pdf_tools.PdfToolError):
            run("split", [("a.pdf", make_pdf(3))], mode="ranges", ranges="")
        with self.assertRaises(pdf_tools.PdfToolError):
            run("split", [("a.pdf", make_pdf(3))], mode="sideways")

    def test_too_many_parts_are_refused(self):
        with mock.patch.object(pdf_tools, "MAX_PARTS", 3), self.assertRaises(pdf_tools.PdfToolError):
            run("split", [("a.pdf", make_pdf(5))], mode="single")

    def test_two_parts_with_the_same_name_do_not_overwrite_each_other(self):
        data = pdf_tools._zip([("a.pdf", b"1"), ("a.pdf", b"2"), ("A.PDF", b"3")])
        self.assertEqual(len(zipfile.ZipFile(io.BytesIO(data)).namelist()), 3)


class ChoosingAndOrderingPages(unittest.TestCase):
    def test_extract_keeps_the_pages_asked_for_in_the_order_asked(self):
        result = run("extract", [("a.pdf", make_pdf(6))], pages="5, 1-2")
        self.assertEqual(texts(result.data), ["A page 5", "A page 1", "A page 2"])
        with self.assertRaises(pdf_tools.PdfToolError):
            run("extract", [("a.pdf", make_pdf(6))], pages="")

    def test_remove_drops_the_pages_and_keeps_the_rest_in_order(self):
        result = run("remove", [("a.pdf", make_pdf(5))], pages="2, 4")
        self.assertEqual(texts(result.data), ["A page 1", "A page 3", "A page 5"])
        self.assertEqual(result.pages, 3)

    def test_removing_every_page_is_refused(self):
        with self.assertRaises(pdf_tools.PdfToolError):
            run("remove", [("a.pdf", make_pdf(2))], pages="1-2")

    def test_reorder_with_a_page_twice_and_a_blank_one(self):
        result = run("organize", [("a.pdf", make_pdf(3))], order="3, 1, blank, 1, 2")
        self.assertEqual(texts(result.data), ["A page 3", "A page 1", "", "A page 1", "A page 2"])
        blank = reader(result.data).pages[2]
        self.assertAlmostEqual(float(blank.mediabox.width), A4[0], places=0)

    def test_reverse_turns_the_whole_pdf_round(self):
        result = run("organize", [("a.pdf", make_pdf(3))], reverse=True)
        self.assertEqual(texts(result.data), ["A page 3", "A page 2", "A page 1"])

    def test_reorder_needs_an_order_or_reverse_and_a_real_page(self):
        with self.assertRaises(pdf_tools.PdfToolError):
            run("organize", [("a.pdf", make_pdf(3))])
        with self.assertRaises(pdf_tools.PdfToolError):
            run("organize", [("a.pdf", make_pdf(3))], order="blank, blank")

    def test_rotate_turns_only_the_chosen_pages(self):
        result = run("rotate", [("a.pdf", make_pdf(3))], angle=90, pages="2")
        self.assertEqual([page.rotation for page in reader(result.data).pages], [0, 90, 0])
        again = run("rotate", [("a.pdf", result.data)], angle=270, pages="1-2")
        self.assertEqual([page.rotation for page in reader(again.data).pages], [270, 0, 0])
        with self.assertRaises(pdf_tools.PdfToolError):
            run("rotate", [("a.pdf", make_pdf(1))], angle=45)

    def test_resize_puts_every_page_on_the_sheet_and_keeps_landscape_landscape(self):
        mixed = pdf_tools.merge([("a.pdf", make_pdf(1, "P", (400, 600))), ("b.pdf", make_pdf(1, "L", (900, 500)))], {}).data
        result = run("resize", [("mixed.pdf", mixed)], size="a4")
        first, second = reader(result.data).pages
        self.assertEqual((round(float(first.mediabox.width)), round(float(first.mediabox.height))), (595, 842))
        self.assertEqual((round(float(second.mediabox.width)), round(float(second.mediabox.height))), (842, 595))
        self.assertEqual(texts(result.data), ["P page 1", "L page 1"])
        self.assertEqual(round(float(reader(run("resize", [("m.pdf", mixed)], size="letter").data).pages[0].mediabox.width)), 612)

    def test_resize_puts_the_content_on_the_sheet_and_not_beside_it(self):
        source = make_pdf(1, "P", (300, 300))
        page = reader(run("resize", [("s.pdf", source)], size="a4").data).pages[0]
        positions = []
        page.extract_text(visitor_text=lambda text, cm, tm, font, size: positions.append((tm[4] * cm[0] + cm[4], tm[5] * cm[3] + cm[5])) if text.strip() else None)
        self.assertTrue(positions)
        x, y = positions[0]
        self.assertTrue(0 <= x <= 595 and 0 <= y <= 842, positions)


class PicturesAndPdfs(unittest.TestCase):
    def test_pictures_become_one_page_each_on_the_chosen_sheet(self):
        pictures = [("a.jpg", photo(1600, 1200)), ("b.png", photo(800, 800, kind="PNG")), ("c.jpg", photo(600, 900))]
        result = run("images-to-pdf", pictures, size="a4", orientation="auto", margin_mm=10)
        pages = reader(result.data).pages
        self.assertEqual(len(pages), 3)
        self.assertEqual([round(float(p.mediabox.width)) for p in pages], [842, 595, 595])  # the wide photo gets a landscape sheet
        self.assertEqual(result.pages, 3)

    def test_a_photo_is_kept_as_it_was_and_the_file_stays_light(self):
        data = photo(1600, 1200)
        result = run("images-to-pdf", [("a.jpg", data)], size="a4")
        self.assertLess(len(result.data), len(data) * 1.2)

    def test_a_photo_taken_sideways_is_turned_upright(self):
        sideways = photo(1200, 800, orientation=6)  # the camera's note: turn it a quarter
        page = reader(run("images-to-pdf", [("a.jpg", sideways)], size="a4", orientation="auto").data).pages[0]
        self.assertGreater(float(page.mediabox.height), float(page.mediabox.width))  # upright means taller than wide

    def test_a_picture_with_see_through_parts_goes_on_white(self):
        flat = Image.new("RGBA", (200, 200), (255, 0, 0, 0))
        out = io.BytesIO()
        flat.save(out, "PNG")
        result = run("images-to-pdf", [("a.png", out.getvalue())], size="fit")
        self.assertEqual(result.pages, 1)

    def test_fit_makes_the_sheet_the_size_of_the_picture(self):
        page = reader(run("images-to-pdf", [("a.jpg", photo(1500, 750))], size="fit").data).pages[0]
        self.assertAlmostEqual(float(page.mediabox.width) / float(page.mediabox.height), 2.0, places=1)

    def test_something_that_is_not_a_picture_is_refused_by_name(self):
        with self.assertRaises(pdf_tools.PdfToolError) as caught:
            run("images-to-pdf", [("notes.jpg", b"this is not a picture")])
        self.assertIn("notes.jpg", str(caught.exception))

    def test_a_picture_with_too_many_pixels_is_refused(self):
        with mock.patch.object(pdf_tools, "MAX_IMAGE_PIXELS", 1000), self.assertRaises(pdf_tools.PdfToolError):
            run("images-to-pdf", [("a.jpg", photo(200, 200))])

    def test_pictures_come_back_out_of_a_pdf(self):
        made = run("images-to-pdf", [("a.jpg", photo(800, 600)), ("b.png", photo(640, 480, kind="PNG"))], size="a4")
        result = run("extract-images", [("scan.pdf", made.data)])
        archive = zipfile.ZipFile(io.BytesIO(result.data))
        self.assertEqual(result.files, 2)
        self.assertEqual(len(archive.namelist()), 2)
        for name in archive.namelist():
            self.assertIsNotNone(Image.open(io.BytesIO(archive.read(name))).size)

    def test_a_pdf_with_no_pictures_says_so_and_small_ones_can_be_left_out(self):
        with self.assertRaises(pdf_tools.PdfToolError):
            run("extract-images", [("a.pdf", make_pdf(2))])
        made = run("images-to-pdf", [("a.jpg", photo(80, 80))], size="a4")
        with self.assertRaises(pdf_tools.PdfToolError):
            run("extract-images", [("a.pdf", made.data)], min_px=200)


class MakingAFileSmaller(unittest.TestCase):
    def test_pictures_are_made_lighter_and_the_text_is_still_there(self):
        source = image_pdf()
        result = run("compress", [("a.pdf", source)], level="recommended")
        self.assertLess(len(result.data), len(source) * 0.7)
        self.assertIn("smaller", result.note)
        self.assertEqual(len(reader(result.data).pages), 1)

    def test_stronger_is_smaller_than_light(self):
        source = image_pdf()
        light = len(run("compress", [("a.pdf", source)], level="light").data)
        strong = len(run("compress", [("a.pdf", source)], level="strong").data)
        self.assertLess(strong, light)

    def test_a_file_that_cannot_get_smaller_comes_back_as_it_was(self):
        source = make_pdf(2)
        result = run("compress", [("a.pdf", source)], level="strong")
        self.assertLessEqual(len(result.data), len(source))
        self.assertEqual(texts(result.data), ["A page 1", "A page 2"])

    def test_an_unknown_level_is_refused(self):
        with self.assertRaises(pdf_tools.PdfToolError):
            run("compress", [("a.pdf", make_pdf(1))], level="crush")


class MarksOnThePages(unittest.TestCase):
    def test_a_watermark_is_on_every_page_or_only_the_chosen_ones(self):
        everywhere = run("watermark", [("a.pdf", make_pdf(3))], text="CONFIDENTIAL", angle=0)
        self.assertTrue(all("CONFIDENTIAL" in page for page in texts(everywhere.data)))
        some = run("watermark", [("a.pdf", make_pdf(3))], text="DRAFT", angle=0, pages="2")
        self.assertEqual(["DRAFT" in page for page in texts(some.data)], [False, True, False])
        self.assertTrue(texts(some.data)[0].startswith("A page 1"))  # the page itself is not lost

    def test_a_long_watermark_is_shrunk_to_fit_and_tiled_ones_work(self):
        result = run("watermark", [("a.pdf", make_pdf(1))], text="A VERY LONG WATERMARK THAT WOULD NOT FIT AT THIS SIZE", size=200, angle=0)
        self.assertEqual(result.pages, 1)
        tiled = run("watermark", [("a.pdf", make_pdf(1))], text="COPY", layout="tiled", angle=30)
        self.assertEqual(tiled.pages, 1)

    def test_watermark_needs_words_and_sensible_numbers(self):
        for options in ({"text": ""}, {"text": "x" * 61}, {"text": "x", "opacity": 0}, {"text": "x", "colour": "ultraviolet"}, {"text": "x", "angle": 120}):
            with self.subTest(options=options), self.assertRaises(pdf_tools.PdfToolError):
                run("watermark", [("a.pdf", make_pdf(1))], **options)

    def test_a_watermark_in_hindi_does_not_fail(self):
        result = run("watermark", [("a.pdf", make_pdf(1))], text="गोपनीय", angle=0)
        self.assertEqual(result.pages, 1)

    def test_a_page_that_was_turned_still_gets_its_mark(self):
        turned = run("rotate", [("a.pdf", make_pdf(1))], angle=90).data
        result = run("watermark", [("a.pdf", turned)], text="SEEN", angle=0)
        self.assertIn("SEEN", texts(result.data)[0])

    def test_page_numbers(self):
        result = run("page-numbers", [("a.pdf", make_pdf(3))], format="page_n_of_total", position="bottom-right")
        self.assertEqual([page.splitlines()[-1] for page in texts(result.data)], ["Page 1 of 3", "Page 2 of 3", "Page 3 of 3"])

    def test_numbering_can_start_later_skip_the_cover_and_use_a_plainer_form(self):
        result = run("page-numbers", [("a.pdf", make_pdf(3))], format="n", start=10, skip_first=True, position="top-center")
        pages = texts(result.data)
        self.assertNotIn("10", pages[0])
        self.assertIn("11", pages[1])
        self.assertIn("12", pages[2])

    def test_numbers_can_go_on_chosen_pages_only(self):
        result = run("page-numbers", [("a.pdf", make_pdf(4))], format="n_of_total", pages="2-3")
        pages = texts(result.data)
        self.assertEqual(["/" in page for page in pages], [False, True, True, False])

    def test_a_position_or_format_that_does_not_exist_is_refused(self):
        with self.assertRaises(pdf_tools.PdfToolError):
            run("page-numbers", [("a.pdf", make_pdf(1))], position="middle")
        with self.assertRaises(pdf_tools.PdfToolError):
            run("page-numbers", [("a.pdf", make_pdf(1))], format="{n.__class__}")


class Passwords(unittest.TestCase):
    def test_a_locked_pdf_needs_its_password_and_unlocking_removes_it(self):
        source = make_pdf(2)
        protected = run("protect", [("a.pdf", source)], new_password="secret1")
        locked_file = reader(protected.data)
        self.assertTrue(locked_file.is_encrypted)
        self.assertFalse(PdfReader(io.BytesIO(protected.data)).decrypt("nope"))
        self.assertTrue(reader(protected.data).decrypt("secret1"))
        with self.assertRaises(pdf_tools.PdfToolError):
            run("rotate", [("a.pdf", protected.data)], angle=90)  # no password given
        self.assertEqual(texts(run("unlock", [("a.pdf", protected.data)], password="secret1").data), ["A page 1", "A page 2"])
        opened = reader(run("unlock", [("a.pdf", protected.data)], password="secret1").data)
        self.assertFalse(opened.is_encrypted)

    def test_a_wrong_or_missing_password_is_told_apart(self):
        protected = locked(make_pdf(1))
        with self.assertRaises(pdf_tools.PdfToolError) as caught:
            run("unlock", [("a.pdf", protected)], password="wrong")
        self.assertIn("does not open", str(caught.exception))
        with self.assertRaises(pdf_tools.PdfToolError) as caught:
            run("unlock", [("a.pdf", protected)])
        self.assertIn("Enter the password", str(caught.exception))

    def test_another_tool_can_work_on_a_locked_file_when_given_the_password(self):
        result = run("rotate", [("a.pdf", locked(make_pdf(2)))], angle=90, password="secret1")
        self.assertFalse(reader(result.data).is_encrypted)
        self.assertEqual([page.rotation for page in reader(result.data).pages], [90, 90])

    def test_unlocking_a_file_that_was_not_locked_gives_a_copy(self):
        result = run("unlock", [("a.pdf", make_pdf(2))])
        self.assertIn("not locked", result.note)
        self.assertEqual(len(reader(result.data).pages), 2)

    def test_printing_and_copying_can_be_switched_off(self):
        from pypdf.constants import UserAccessPermissions as Allow

        protected = run("protect", [("a.pdf", make_pdf(1))], new_password="secret1", allow_print=False, allow_copy=False)
        opened = reader(protected.data)
        opened.decrypt("secret1")
        rights = opened.user_access_permissions
        self.assertFalse(rights & Allow.PRINT)
        self.assertFalse(rights & Allow.EXTRACT)
        default = reader(run("protect", [("a.pdf", make_pdf(1))], new_password="secret1").data)
        default.decrypt("secret1")
        self.assertTrue(default.user_access_permissions & Allow.PRINT)

    def test_the_password_must_be_long_enough(self):
        for password in ("", "abc"):
            with self.subTest(password=password), self.assertRaises(pdf_tools.PdfToolError):
                run("protect", [("a.pdf", make_pdf(1))], new_password=password)
        with self.assertRaises(pdf_tools.PdfToolError):
            run("protect", [("a.pdf", make_pdf(1))], new_password="x" * 200)

    def test_a_pdf_that_only_restricts_printing_opens_without_a_password(self):
        """Many bank statements are locked only against editing: they open for anyone, and unlocking removes the restriction."""
        restricted = run("protect", [("a.pdf", make_pdf(1))], new_password="secret1", owner_password="owner-secret")
        self.assertTrue(reader(restricted.data).decrypt("owner-secret"))


class DetailsAndText(unittest.TestCase):
    def test_details_are_saved_and_cleared(self):
        saved = run("metadata", [("a.pdf", make_pdf(2))], title="Contract", author="Prakash Securities", subject="Renewal", keywords="a, b")
        info = reader(saved.data).metadata
        self.assertEqual((info.title, info.author, info.subject, info.keywords), ("Contract", "Prakash Securities", "Renewal", "a, b"))
        cleared = run("metadata", [("a.pdf", saved.data)], clear=True)
        info = reader(cleared.data).metadata
        self.assertFalse(info and (info.title or info.author or info.subject))

    def test_new_details_replace_the_old_ones(self):
        first = run("metadata", [("a.pdf", make_pdf(1))], title="Old", author="Someone").data
        second = run("metadata", [("a.pdf", first)], title="New").data
        info = reader(second).metadata
        self.assertEqual(info.title, "New")
        self.assertFalse(info.author)

    def test_details_keep_the_pages_and_the_bookmarks(self):
        merged = run("merge", [("a.pdf", make_pdf(1)), ("b.pdf", make_pdf(1))]).data
        result = run("metadata", [("a.pdf", merged)], title="Both")
        self.assertEqual(len(reader(result.data).pages), 2)
        self.assertEqual(len(list(reader(result.data).outline)), 2)

    def test_the_text_is_read_page_by_page(self):
        result = run("text", [("a.pdf", make_pdf(3))], pages="1,3")
        body = result.data.decode("utf-8-sig")
        self.assertIn("--- Page 1 ---\nA page 1", body)
        self.assertIn("--- Page 3 ---\nA page 3", body)
        self.assertNotIn("A page 2", body)
        self.assertEqual(result.media_type, "text/plain; charset=utf-8")

    def test_a_scan_has_no_text_and_that_is_said(self):
        with self.assertRaises(pdf_tools.PdfToolError) as caught:
            run("text", [("scan.pdf", image_pdf(400, 300))])
        self.assertIn("no text", str(caught.exception))


class DamagedAndWrongFiles(unittest.TestCase):
    def test_a_file_that_is_not_a_pdf_is_refused_by_name(self):
        for name, data in (("letter.docx", b"PK\x03\x04 not a pdf"), ("empty.pdf", b""), ("text.pdf", b"hello, I am text")):
            with self.subTest(name=name), self.assertRaises(pdf_tools.PdfToolError) as caught:
                run("rotate", [(name, data)], angle=90)
            self.assertIn(name, str(caught.exception))

    def test_a_file_with_a_pdf_header_and_nothing_else_is_a_plain_error_not_a_crash(self):
        for data in (b"%PDF-1.7\n", b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n" * 3, b"%PDF-" + bytes(range(256)) * 20):
            with self.subTest(size=len(data)), self.assertRaises(pdf_tools.PdfToolError):
                run("extract", [("a.pdf", data)], pages="1")

    def test_a_damaged_index_is_mended_by_repair(self):
        source = make_pdf(3)
        marker = source.rindex(b"startxref")
        damaged = source[:marker] + b"startxref\n99999999\n%%EOF\n"
        result = run("repair", [("a.pdf", damaged)])
        self.assertEqual(texts(result.data), ["A page 1", "A page 2", "A page 3"])
        self.assertIn("Every page was recovered", result.note)

    def test_a_cut_off_file_is_recovered_as_far_as_it_goes_or_refused_in_words(self):
        source = make_pdf(4)
        try:
            result = run("repair", [("a.pdf", source[: len(source) * 3 // 4])])
        except pdf_tools.PdfToolError as exc:
            self.assertTrue(str(exc))
        else:
            self.assertGreaterEqual(len(reader(result.data).pages), 1)

    def test_a_pdf_with_too_many_pages_is_refused(self):
        with mock.patch.object(pdf_tools, "MAX_PAGES", 2), self.assertRaises(pdf_tools.PdfToolError) as caught:
            run("rotate", [("big.pdf", make_pdf(3))], angle=90)
        self.assertIn("3 pages", str(caught.exception))


class Limits(unittest.TestCase):
    def test_too_many_files_or_too_much_data_or_the_wrong_number_for_the_tool(self):
        with mock.patch.object(pdf_tools, "MAX_FILES", 2), self.assertRaises(pdf_tools.PdfToolError):
            run("merge", [("a.pdf", make_pdf(1)), ("b.pdf", make_pdf(1)), ("c.pdf", make_pdf(1))])
        with mock.patch.object(pdf_tools, "MAX_TOTAL_BYTES", 1000), self.assertRaises(pdf_tools.PdfToolError):
            run("merge", [("a.pdf", make_pdf(2)), ("b.pdf", make_pdf(2))])
        with mock.patch.object(pdf_tools, "MAX_FILE_BYTES", 1000), self.assertRaises(pdf_tools.PdfToolError):
            run("rotate", [("a.pdf", make_pdf(2))], angle=90)
        with self.assertRaises(pdf_tools.PdfToolError):
            run("rotate", [("a.pdf", make_pdf(1)), ("b.pdf", make_pdf(1))], angle=90)
        with self.assertRaises(pdf_tools.PdfToolError):
            pdf_tools.run("rotate", [], {"angle": 90})

    def test_an_unknown_tool_and_odd_options_are_refused_not_crashed(self):
        with self.assertRaises(pdf_tools.PdfToolError):
            pdf_tools.run("shred", [("a.pdf", make_pdf(1))], {})
        for options in (None, [], "text", 5):
            with self.subTest(options=options):
                self.assertEqual(pdf_tools.run("rotate", [("a.pdf", make_pdf(1))], options).pages, 1)

    def test_every_option_that_is_a_number_refuses_a_number_that_is_not_one(self):
        for key, tool in (("start", "page-numbers"), ("size", "page-numbers"), ("margin_mm", "page-numbers"), ("every", "split")):
            with self.subTest(key=key), self.assertRaises(pdf_tools.PdfToolError):
                run(tool, [("a.pdf", make_pdf(3))], **{key: "abc", "mode": "every"})

    def test_a_character_a_database_could_not_hold_is_refused_in_words(self):
        with self.assertRaises(pdf_tools.PdfToolError):
            run("metadata", [("a.pdf", make_pdf(1))], title="a\x00b")

    def test_every_tool_is_listed_with_a_label_and_a_kind(self):
        for tool_id, tool in pdf_tools.TOOLS.items():
            with self.subTest(tool=tool_id):
                self.assertTrue(tool.label)
                self.assertIn(tool.kind, ("pdf", "pdfs", "images"))
        self.assertGreaterEqual(len(pdf_tools.TOOLS), 15)


class LookingAtFiles(unittest.TestCase):
    def test_each_file_is_described_and_a_bad_one_does_not_hide_the_others(self):
        rows = pdf_tools.inspect([("good.pdf", make_pdf(3)), ("bad.pdf", b"nonsense"), ("locked.pdf", locked(make_pdf(2)))], {})
        good, bad, protected = rows
        self.assertEqual((good["pages"], good["error"], good["locked"]), (3, "", False))
        self.assertEqual((round(good["width"]), round(good["height"])), (595, 842))
        self.assertIsNone(bad["pages"])
        self.assertIn("not a PDF", bad["error"])
        self.assertTrue(protected["locked"])
        self.assertIsNone(protected["pages"])

    def test_a_password_opens_a_locked_file_for_the_look(self):
        rows = pdf_tools.inspect([("locked.pdf", locked(make_pdf(2)))], {"passwords": ["secret1"]})
        self.assertEqual((rows[0]["pages"], rows[0]["locked"], rows[0]["was_locked"]), (2, False, True))

    def test_the_details_are_there_to_fill_the_form(self):
        rows = pdf_tools.inspect([("a.pdf", run("metadata", [("a.pdf", make_pdf(1))], title="Hello").data)], {})
        self.assertEqual(rows[0]["details"]["title"], "Hello")


NOTHING = {"id": 7, "username": "t", "role": "viewer", "letterhead_access": False, "letterhead_write": False}


class TheEndpoints(unittest.TestCase):
    def client(self, **flags):
        app = FastAPI()
        app.include_router(pdf_tools_router.router)
        user = {**NOTHING, **flags}
        app.dependency_overrides[dependencies.get_current_user] = lambda: user
        return TestClient(app)

    def post(self, client, tool, files, **options):
        uploads = [("files", (name, data, "application/pdf")) for name, data in files]
        return client.post(f"/pdf-tools/{tool}", files=uploads, data={"options": json.dumps(options)})

    def test_every_route_has_exactly_the_letterhead_guard(self):
        for route in pdf_tools_router.router.routes:
            names = {dep.call.__name__ for dep in route.dependant.dependencies}
            self.assertEqual(names, {"require_letterhead"}, route.path)

    def test_someone_without_letterhead_access_gets_nothing(self):
        client = self.client()
        calls = [
            lambda: client.get("/pdf-tools/limits"),
            lambda: self.post(client, "merge", [("a.pdf", make_pdf(1)), ("b.pdf", make_pdf(1))]),
            lambda: client.post("/pdf-tools/inspect", files=[("files", ("a.pdf", make_pdf(1), "application/pdf"))]),
            lambda: self.post(client, "shred", [("a.pdf", make_pdf(1))]),
        ]
        for call in calls:
            self.assertEqual(call().status_code, 403)

    def test_someone_not_signed_in_gets_a_401(self):
        app = FastAPI()
        app.include_router(pdf_tools_router.router)
        self.assertEqual(TestClient(app).get("/pdf-tools/limits").status_code, 401)

    def test_a_merge_comes_back_as_a_download_with_its_summary(self):
        response = self.post(self.client(letterhead_access=True), "merge", [("a.pdf", make_pdf(2)), ("b.pdf", make_pdf(1))])
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.headers["content-type"], "application/pdf")
        self.assertIn("attachment", response.headers["content-disposition"])
        self.assertEqual(response.headers["x-content-type-options"], "nosniff")
        self.assertEqual(response.headers["cache-control"], "no-store")
        summary = json.loads(response.headers["x-orion-result"])
        self.assertEqual((summary["pages"], summary["name"]), (3, "Merged.pdf"))
        self.assertGreater(summary["bytes_out"], 0)
        self.assertEqual(len(reader(response.content).pages), 3)

    def test_a_zip_comes_back_as_a_zip(self):
        response = self.post(self.client(letterhead_access=True), "split", [("a.pdf", make_pdf(4))], mode="single")
        self.assertEqual(response.headers["content-type"], "application/zip")
        self.assertEqual(len(zipfile.ZipFile(io.BytesIO(response.content)).namelist()), 4)

    def test_a_file_name_with_odd_characters_makes_a_safe_download_name(self):
        response = self.post(self.client(letterhead_access=True), "rotate", [('bad"name\r\nअ.pdf', make_pdf(1))], angle=90)
        header = response.headers["content-disposition"]
        self.assertNotIn("\r", header)
        self.assertNotIn("\n", header)
        self.assertIn("filename*=UTF-8''", header)

    def test_a_refusal_is_a_plain_400_with_words(self):
        client = self.client(letterhead_access=True)
        response = self.post(client, "extract", [("a.pdf", make_pdf(2))], pages="9")
        self.assertEqual(response.status_code, 400)
        self.assertIn("Page 9 does not exist", response.json()["detail"])
        self.assertEqual(self.post(client, "merge", [("a.pdf", make_pdf(1))]).status_code, 400)
        self.assertEqual(client.post("/pdf-tools/rotate", files=[("files", ("a.pdf", b"nonsense", "application/pdf"))]).status_code, 400)

    def test_an_unknown_tool_is_a_404_and_bad_options_are_a_400(self):
        client = self.client(letterhead_access=True)
        self.assertEqual(self.post(client, "shred", [("a.pdf", make_pdf(1))]).status_code, 404)
        bad = client.post("/pdf-tools/rotate", files=[("files", ("a.pdf", make_pdf(1), "application/pdf"))], data={"options": "{not json"})
        self.assertEqual(bad.status_code, 400)
        listy = client.post("/pdf-tools/rotate", files=[("files", ("a.pdf", make_pdf(1), "application/pdf"))], data={"options": "[1, 2]"})
        self.assertEqual(listy.status_code, 400)

    def test_a_file_that_is_too_large_is_refused_while_it_is_read(self):
        client = self.client(letterhead_access=True)
        with mock.patch.object(pdf_tools, "MAX_FILE_BYTES", 500):
            response = self.post(client, "rotate", [("big.pdf", make_pdf(5))], angle=90)
        self.assertEqual(response.status_code, 400)
        self.assertIn("big.pdf is larger than", response.json()["detail"])

    def test_too_many_files_are_refused_before_any_is_opened(self):
        client = self.client(letterhead_access=True)
        with mock.patch.object(pdf_tools, "MAX_FILES", 2):
            response = self.post(client, "merge", [("a.pdf", make_pdf(1))] * 3)
        self.assertEqual(response.status_code, 400)

    def test_when_every_place_is_taken_the_answer_is_busy_not_a_wait(self):
        client = self.client(letterhead_access=True)
        held = [pdf_tools_router._JOBS.acquire() for _ in range(3)]
        try:
            with mock.patch.object(pdf_tools_router, "_WAIT_SECONDS", 0):
                response = self.post(client, "rotate", [("a.pdf", make_pdf(1))], angle=90)
        finally:
            for _ in held:
                pdf_tools_router._JOBS.release()
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.headers["retry-after"], "20")
        self.assertEqual(self.post(client, "rotate", [("a.pdf", make_pdf(1))], angle=90).status_code, 200)  # and it is free again

    def test_a_failed_job_gives_its_place_back(self):
        client = self.client(letterhead_access=True)
        for _ in range(6):  # more failures than there are places
            self.assertEqual(self.post(client, "extract", [("a.pdf", make_pdf(1))], pages="5").status_code, 400)
        self.assertEqual(self.post(client, "rotate", [("a.pdf", make_pdf(1))], angle=90).status_code, 200)

    def test_jobs_at_the_same_time_all_finish(self):
        client = self.client(letterhead_access=True)
        outcomes = []

        def job():
            outcomes.append(self.post(client, "merge", [("a.pdf", make_pdf(2)), ("b.pdf", make_pdf(2))]).status_code)

        threads = [threading.Thread(target=job) for _ in range(6)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(outcomes, [200] * 6)

    def test_what_is_logged_is_who_and_how_big_never_a_name_or_a_password(self):
        client = self.client(letterhead_access=True)
        with self.assertLogs("app.routers.pdf_tools_router", level="INFO") as logged:
            response = self.post(client, "protect", [("private-salary-sheet.pdf", make_pdf(1))], new_password="Sup3r-Secret-Word")
        self.assertEqual(response.status_code, 200)
        text = "\n".join(logged.output)
        self.assertIn("PDF tool protect for user 7", text)
        self.assertNotIn("private-salary-sheet", text)
        self.assertNotIn("Sup3r-Secret-Word", text)

    def test_the_limits_answer_matches_the_tools(self):
        body = self.client(letterhead_access=True).get("/pdf-tools/limits").json()
        self.assertEqual(set(body["tools"]), set(pdf_tools.TOOLS))
        self.assertEqual(body["max_file_mb"], pdf_tools.MAX_FILE_BYTES // (1024 * 1024))
        self.assertEqual(body["min_password"], pdf_tools.MIN_PASSWORD)

    def test_inspect_reports_each_file(self):
        client = self.client(letterhead_access=True)
        files = [("files", ("a.pdf", make_pdf(3), "application/pdf")), ("files", ("b.pdf", b"junk", "application/pdf"))]
        body = client.post("/pdf-tools/inspect", files=files).json()["files"]
        self.assertEqual([row["pages"] for row in body], [3, None])
        self.assertTrue(body[1]["error"])


if __name__ == "__main__":
    unittest.main()


class TheSizeLimit(unittest.TestCase):
    """The upload is refused as soon as it is known to be too big, before the framework has put it all on disk."""

    def app(self, limit: int):
        from fastapi import Request

        from app.request_limits import RequestSizeLimitMiddleware

        app = FastAPI()
        app.add_middleware(RequestSizeLimitMiddleware, limits={"/up": limit})

        @app.post("/up")
        async def up(request: Request):
            return {"bytes": len(await request.body())}

        @app.post("/up2")
        async def other(request: Request):
            return {"bytes": len(await request.body())}

        return TestClient(app)

    def test_a_request_that_says_it_is_too_big_is_refused_at_once(self):
        response = self.app(1000).post("/up", content=b"x" * 5000)
        self.assertEqual(response.status_code, 413)
        self.assertIn("too much", response.json()["detail"])

    def test_one_that_does_not_say_how_big_is_stopped_as_it_arrives(self):
        def chunks():
            for _ in range(10):
                yield b"x" * 500

        response = self.app(1000).post("/up", content=chunks())
        self.assertEqual(response.status_code, 413)

    def test_a_request_within_the_limit_and_other_addresses_are_untouched(self):
        client = self.app(1000)
        self.assertEqual(client.post("/up", content=b"x" * 900).json(), {"bytes": 900})
        self.assertEqual(client.post("/up2", content=b"x" * 5000).json(), {"bytes": 5000})  # /up2 is not under /up

    def test_the_pdf_tools_are_limited_and_the_limit_is_innermost(self):
        from app import main
        from app.request_limits import RequestSizeLimitMiddleware

        ours = [item for item in main.app.user_middleware if item.cls is RequestSizeLimitMiddleware]
        self.assertEqual(len(ours), 1)
        self.assertGreater(ours[0].kwargs["limits"]["/api/pdf-tools"], pdf_tools.MAX_TOTAL_BYTES)
        self.assertIs(main.app.user_middleware[-1].cls, RequestSizeLimitMiddleware)  # directly around the app


class TheScreenAndTheServerAgree(unittest.TestCase):
    """frontend/src/pages/pdftools/tools.ts describes the tools the screen offers; this keeps it in step with the server."""

    SOURCE = (ROOT / "frontend" / "src" / "pages" / "pdftools" / "tools.ts").read_text(encoding="utf-8")

    def test_the_same_tools_with_the_same_kind_of_input(self):
        import re

        screen = dict(re.findall(r"^    id: '([a-z-]+)',(?:.|\n)*?^    accept: '([a-z]+)',", self.SOURCE, re.M))
        self.assertEqual(set(screen), set(pdf_tools.TOOLS))
        for tool_id, accept in screen.items():
            with self.subTest(tool=tool_id):
                self.assertEqual(accept, pdf_tools.TOOLS[tool_id].kind)

    def test_every_option_the_screen_sends_is_one_the_server_reads(self):
        import re

        server = (ROOT / "backend" / "app" / "pdf_tools.py").read_text(encoding="utf-8")
        keys = set(re.findall(r"^\s+(?:\.\.\.)?\{? ?kind: '[a-z]+',\s*key: '([a-z_]+)'", self.SOURCE, re.M)) | set(re.findall(r"key: '([a-z_]+)'", self.SOURCE))
        self.assertGreater(len(keys), 25)
        for key in keys:
            with self.subTest(option=key):
                self.assertIn(f'"{key}"', server)

    def test_every_tool_has_a_title_and_a_blurb_on_the_screen(self):
        import re

        self.assertEqual(len(re.findall(r"^    title: '", self.SOURCE, re.M)), len(pdf_tools.TOOLS))
        self.assertEqual(len(re.findall(r"^    blurb: '", self.SOURCE, re.M)), len(pdf_tools.TOOLS))
