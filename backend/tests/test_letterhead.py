"""The Letterhead utility: the letterhead's layout, the cleaning of a letter's text, PDFs on the letterhead, and
who may do what.

None of this needs a database. Run from the repo root:  python -m pytest backend/tests
"""

import io
import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from PIL import Image  # noqa: E402
from pypdf import PdfReader  # noqa: E402
from reportlab.lib.pagesizes import A4, landscape  # noqa: E402
from reportlab.lib.units import mm  # noqa: E402
from reportlab.pdfgen.canvas import Canvas  # noqa: E402

from app import auth, billing, dependencies, letterhead, letterhead_pdf  # noqa: E402
from app.billing_pdf import invoice_pdf, statement_pdf  # noqa: E402
from app.letterhead_page import Letterhead  # noqa: E402
from app.routers import letterhead_router  # noqa: E402

DESIGN = letterhead.builtin_design()


def image_bytes(width: int, height: int, kind: str = "JPEG", mode: str = "RGB") -> bytes:
    out = io.BytesIO()
    Image.new(mode, (width, height), (200, 30, 30, 128) if mode == "RGBA" else (200, 30, 30)).save(out, format=kind)
    return out.getvalue()


def text_pdf(words: str, pages: int = 1, size=A4) -> bytes:
    out = io.BytesIO()
    canvas = Canvas(out, pagesize=size)
    for number in range(1, pages + 1):
        canvas.setFont("Helvetica", 14)
        canvas.drawString(40, size[1] - 40, f"{words} {number}")
        canvas.showPage()
    canvas.save()
    return out.getvalue()


def sample_bill() -> dict:
    figures = billing.compute_bill([{"particulars": "Security Guard", "qty": 4, "rate": 15000}], None)
    plain = lambda value: float(value) if hasattr(value, "quantize") else value  # noqa: E731
    return {
        **{key: plain(value) for key, value in figures.items() if key not in ("lines", "rates", "extra_charges")},
        "lines": [{key: plain(value) for key, value in line.items()} for line in figures["lines"]],
        "rates": {key: plain(value) for key, value in figures["rates"].items()},
        "extra_charges": [], "hidden": [], "party_fields": [], "header_fields": [{"label": "Vendor code", "value": "V-77"}],
        "profile": billing.DEFAULT_PROFILE, "status": "Issued", "bill_number": "2026-27/1", "bill_date": "2026-10-07",
        "service_month": "2026-09-01", "party_name": "Test Client Ltd", "party_gstin": "23ABCDE1234F1Z5",
    }


def pdf_text(data: bytes) -> str:
    """Every word of a PDF on one line, so a phrase is found wherever it wrapped."""
    return " ".join(" ".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(data)).pages).split())


def images_per_page(data: bytes) -> list[int]:
    return [len(page.images) for page in PdfReader(io.BytesIO(data)).pages]


class Layout(unittest.TestCase):
    def test_the_shipped_letterhead_loads_without_a_database(self):
        self.assertFalse(DESIGN["header"]["custom"])
        self.assertFalse(DESIGN["footer"]["custom"])
        self.assertGreater(DESIGN["header"]["width"], 1000)
        self.assertEqual(DESIGN["settings"], letterhead.DEFAULT_SETTINGS)

    def test_strips_span_the_page_and_keep_their_proportions(self):
        found = letterhead.layout(letterhead.DEFAULT_SETTINGS, (2000, 400), (2000, 200))
        self.assertEqual(found["strip_width_mm"], 207.0)
        self.assertAlmostEqual(found["header_height_mm"], 41.4)
        self.assertAlmostEqual(found["footer_height_mm"], 20.7)
        self.assertAlmostEqual(found["top_space_mm"], 2.5 + 41.4 + 6.0)
        self.assertAlmostEqual(found["bottom_space_mm"], 5.0 + 20.7 + 5.0)

    def test_the_pdf_and_the_browser_put_the_strips_in_the_same_place(self):
        """letterhead.layout feeds the screen and the print; Letterhead.boxes feeds the PDFs. They must agree."""
        boxes = Letterhead(DESIGN).boxes(*A4)
        shared, settings = DESIGN["layout"], DESIGN["settings"]
        self.assertAlmostEqual(boxes["header"][2] / mm, shared["strip_width_mm"], places=1)
        self.assertAlmostEqual(boxes["header"][3] / mm, shared["header_height_mm"], places=1)
        self.assertAlmostEqual(boxes["footer"][3] / mm, shared["footer_height_mm"], places=1)
        self.assertAlmostEqual((A4[1] - boxes["header"][1] - boxes["header"][3]) / mm, settings["header_top_mm"], places=1)
        self.assertAlmostEqual(boxes["footer"][1] / mm, settings["footer_bottom_mm"], places=1)
        top, bottom = Letterhead(DESIGN).text_space()
        self.assertAlmostEqual(top / mm, shared["top_space_mm"], places=1)
        self.assertAlmostEqual(bottom / mm, shared["bottom_space_mm"], places=1)

    def test_settings_are_held_within_their_limits(self):
        cleaned = letterhead.clean_settings({"side_mm": 500, "header_top_mm": -3, "body_left_mm": "abc", "body_right_mm": float("nan")})
        self.assertEqual(cleaned["side_mm"], letterhead.SETTING_LIMITS["side_mm"][2])
        self.assertEqual(cleaned["header_top_mm"], 0)
        self.assertEqual(cleaned["body_left_mm"], letterhead.DEFAULT_SETTINGS["body_left_mm"])
        self.assertEqual(cleaned["body_right_mm"], letterhead.DEFAULT_SETTINGS["body_right_mm"])
        self.assertEqual(set(cleaned), set(letterhead.SETTING_LIMITS))

    def test_an_unknown_setting_is_ignored(self):
        self.assertNotIn("made_up", letterhead.clean_settings({"made_up": 5}))


class StripImages(unittest.TestCase):
    def test_a_good_jpeg_is_stored_as_it_came(self):
        data = image_bytes(1600, 300)
        stored, mime = letterhead.prepare_image(data)
        self.assertEqual((stored, mime), (data, "image/jpeg"))

    def test_a_transparent_png_is_flattened_onto_white(self):
        stored, mime = letterhead.prepare_image(image_bytes(1600, 300, "PNG", "RGBA"))
        self.assertEqual(mime, "image/png")
        self.assertEqual(Image.open(io.BytesIO(stored)).mode, "RGB")

    def test_a_huge_image_is_made_smaller(self):
        stored, _ = letterhead.prepare_image(image_bytes(6000, 900))
        self.assertEqual(Image.open(io.BytesIO(stored)).size, (letterhead.MAX_IMAGE_WIDTH, 450))

    def test_what_is_not_a_wide_sharp_picture_is_refused(self):
        for bad in (b"", b"not an image", image_bytes(400, 80), image_bytes(1000, 900), image_bytes(1600, 300, "BMP")):
            with self.assertRaises(letterhead.LetterheadError):
                letterhead.prepare_image(bad)


class CleanHtml(unittest.TestCase):
    def test_what_the_editor_makes_is_kept(self):
        source = ('<p style="text-align:right">Date</p><h2>Title</h2><p><b>bold</b> <i>it</i> <u>un</u><br>next</p>'
                  '<ul><li>one</li><li>two</li></ul><ol><li>a</li></ol><hr><p data-break="page"></p>'
                  '<table><tbody><tr><th>H</th><td style="text-align:right" colspan="2">1</td></tr></tbody></table>')
        self.assertEqual(letterhead.clean_html(source), source)

    def test_scripts_handlers_links_and_images_are_removed(self):
        cleaned = letterhead.clean_html(
            '<p onclick="steal()">Hello <script>alert(1)</script><a href="javascript:alert(1)">link</a>'
            '<img src=x onerror=alert(1)><iframe src="//evil"></iframe><style>p{}</style></p>'
        )
        self.assertEqual(cleaned, "<p>Hello link</p>")
        for danger in ("script", "onclick", "onerror", "javascript", "href", "<img", "iframe", "style"):
            self.assertNotIn(danger, cleaned)

    def test_only_alignment_survives_from_a_style(self):
        cleaned = letterhead.clean_html('<p style="color:red;text-align: CENTER;background:url(x)" class="x" id="y">a</p>')
        self.assertEqual(cleaned, '<p style="text-align:center">a</p>')

    def test_text_is_escaped(self):
        self.assertEqual(letterhead.clean_html("<p>1 &lt; 2 &amp; 3 > 2</p>"), "<p>1 &lt; 2 &amp; 3 &gt; 2</p>")

    def test_other_tags_are_renamed_or_dropped_but_their_words_stay(self):
        cleaned = letterhead.clean_html('<div><strong>a</strong><em>b</em><span style="font-size:40px">c</span><h1>d</h1></div>')
        self.assertEqual(cleaned, "<p><b>a</b><i>b</i>c</p><h2>d</h2>")

    def test_unclosed_and_stray_tags_come_out_balanced(self):
        self.assertEqual(letterhead.clean_html("<p><b>open</i></table>"), "<p><b>open</b></p>")
        self.assertEqual(letterhead.clean_html("<ul><li>one<li>two"), "<ul><li>one<li>two</li></li></ul>")

    def test_a_paragraph_ends_where_a_block_starts(self):
        self.assertEqual(letterhead.clean_html("<p>a<table><tr><td><p>b</p></td></tr></table>"),
                         "<p>a</p><table><tr><td><p>b</p></td></tr></table>")

    def test_a_letter_that_is_too_long_is_refused(self):
        with self.assertRaises(letterhead.LetterheadError):
            letterhead.clean_html("x" * (letterhead.MAX_BODY_CHARS + 1))

    def test_the_first_words_of_a_letter(self):
        self.assertEqual(letterhead.plain_text("<p>Dear <b>Sir</b>,</p><p>We &amp; you</p>"), "Dear Sir, We & you")
        self.assertTrue(letterhead.plain_text("<p>" + "word " * 100 + "</p>", limit=30).endswith("…"))


class Letters(unittest.TestCase):
    GOOD = {"title": "  Quotation   for XYZ ", "letter_date": "2026-10-07", "body_html": "<p onclick=x>Hi</p>", "ref_no": " PSS/1 "}

    def test_a_letter_is_tidied_before_it_is_stored(self):
        letter = letterhead.clean_letter(self.GOOD)
        self.assertEqual(letter["title"], "Quotation for XYZ")
        self.assertEqual(letter["ref_no"], "PSS/1")
        self.assertEqual(letter["letter_date"], date(2026, 10, 7))
        self.assertEqual(letter["body_html"], "<p>Hi</p>")
        self.assertEqual((letter["font"], letter["font_size"], letter["show_header"], letter["show_footer"]), ("sans", 11, True, True))

    def test_a_letter_needs_a_name_a_date_and_sane_type(self):
        for bad in ({"title": " "}, {"letter_date": "soon"}, {"font": "comic"}, {"font_size": 40}, {"font_size": "big"}):
            with self.assertRaises(letterhead.LetterheadError):
                letterhead.clean_letter({**self.GOOD, **bad})


class Pdfs(unittest.TestCase):
    def test_blank_letterhead_paper_is_a4_with_both_strips_on_every_page(self):
        data = letterhead_pdf.blank_pdf(DESIGN, pages=3)
        reader = PdfReader(io.BytesIO(data))
        self.assertEqual(len(reader.pages), 3)
        self.assertEqual(images_per_page(data), [2, 2, 2])
        self.assertAlmostEqual(float(reader.pages[0].mediabox.width), A4[0], places=0)
        # The strips are stored once however many pages show them.
        self.assertLess(len(data), 2.5 * (len(DESIGN["header"]["bytes"]) + len(DESIGN["footer"]["bytes"])))

    def test_a_stamped_pdf_keeps_its_pages_their_size_and_its_words(self):
        data, pages = letterhead_pdf.stamp_pdf(text_pdf("Landscape sheet", pages=3, size=landscape(A4)), DESIGN)
        reader = PdfReader(io.BytesIO(data))
        self.assertEqual((pages, len(reader.pages)), (3, 3))
        self.assertAlmostEqual(float(reader.pages[2].mediabox.width), landscape(A4)[0], places=0)
        self.assertIn("Landscape sheet 3", pdf_text(data))
        self.assertEqual(images_per_page(data), [2, 2, 2])

    def test_the_choices_when_stamping(self):
        upload = text_pdf("Page", pages=2)
        self.assertEqual(images_per_page(letterhead_pdf.stamp_pdf(upload, DESIGN, first_page_only=True)[0]), [2, 0])
        self.assertEqual(images_per_page(letterhead_pdf.stamp_pdf(upload, DESIGN, footer=False)[0]), [1, 1])
        self.assertEqual(images_per_page(letterhead_pdf.stamp_pdf(upload, DESIGN, fit=False)[0]), [2, 2])

    def test_what_cannot_be_stamped_says_why(self):
        for bad, kwargs in ((b"", {}), (b"this is not a pdf", {}), (text_pdf("x"), {"header": False, "footer": False})):
            with self.assertRaises(letterhead.LetterheadError):
                letterhead_pdf.stamp_pdf(bad, DESIGN, **kwargs)
        with self.assertRaises(letterhead.LetterheadError):
            letterhead_pdf.stamp_pdf(b"%PDF-1.4" + b"x" * letterhead_pdf.MAX_PDF_BYTES, DESIGN)

    def test_a_bill_on_the_letterhead_leaves_off_what_the_letterhead_carries(self):
        bill = sample_bill()
        plain, stamped = invoice_pdf(bill), invoice_pdf(bill, Letterhead(DESIGN))
        self.assertEqual(images_per_page(plain), [0])
        self.assertEqual(images_per_page(stamped)[0], 2)
        typed_name = billing.DEFAULT_PROFILE["company_name"].upper()
        self.assertIn(typed_name, pdf_text(plain))
        self.assertIn(billing.DEFAULT_PROFILE["gstin"], pdf_text(plain))
        for gone in (typed_name, billing.DEFAULT_PROFILE["gstin"], billing.DEFAULT_PROFILE["pf_no"]):
            self.assertNotIn(gone, pdf_text(stamped))
        # Everything that is the bill's own is still there.
        for kept in ("TAX INVOICE", "2026-27/1", "Test Client Ltd", "23ABCDE1234F1Z5", "V-77", "Security Guard", "GRAND TOTAL"):
            self.assertIn(kept, pdf_text(stamped))

    def test_a_statement_on_the_letterhead(self):
        statement = {"client_name": "Test Client", "as_of": "2026-10-07", "total": 100.0, "bills": [], "bucket_labels": [], "buckets": []}
        plain = statement_pdf(statement, billing.DEFAULT_PROFILE)
        stamped = statement_pdf(statement, billing.DEFAULT_PROFILE, Letterhead(DESIGN))
        self.assertIn(billing.DEFAULT_PROFILE["company_name"].upper(), pdf_text(plain))
        self.assertNotIn(billing.DEFAULT_PROFILE["company_name"].upper(), pdf_text(stamped))
        self.assertIn("STATEMENT OF OUTSTANDING BILLS", pdf_text(stamped))
        self.assertEqual(images_per_page(stamped), [2])


def guards(router):
    found = {}
    for route in router.routes:
        names = {dep.call.__name__ for dep in route.dependant.dependencies}
        found[f"{sorted(route.methods)[0]} {route.path}"] = names
    return found


class Access(unittest.TestCase):
    def test_letterhead_is_a_segment_with_a_view_and_a_change_flag(self):
        for flag in ("letterhead_access", "letterhead_write"):
            self.assertIn(flag, auth.ACCESS_FLAGS)
        self.assertIn(("letterhead_write", "letterhead_access"), auth.WRITE_IMPLIES_ACCESS)
        self.assertTrue(auth._resolved_access("viewer", letterhead_write=True)["letterhead_access"])

    def test_admins_and_editors_get_it_by_default_and_viewers_do_not(self):
        self.assertTrue(auth._resolved_access("admin")["letterhead_write"])
        self.assertTrue(auth._resolved_access("editor")["letterhead_write"])
        self.assertFalse(auth._resolved_access("viewer")["letterhead_access"])

    def test_letterhead_follows_its_own_flags(self):
        user = {"role": "editor", "billing_access": True, "billing_write": True, "letterhead_access": False, "letterhead_write": False}
        self.assertFalse(auth.can_access_letterhead(user))
        self.assertFalse(auth.can_access_page(user, "letterhead"))
        user = {"role": "viewer", "billing_access": False, "letterhead_access": True, "letterhead_write": False}
        self.assertTrue(auth.can_access_page(user, "letterhead"))
        self.assertFalse(auth.can_write_letterhead(user))
        self.assertFalse(auth.can_access_page(user, "utility"))

    def test_every_letterhead_route_has_exactly_one_guard(self):
        allowed = {"require_letterhead", "require_letterhead_write", "require_letterhead_design", "require_admin"}
        for route, names in guards(letterhead_router.router).items():
            self.assertEqual(len(names), 1, f"{route} is guarded by {names}")
            self.assertLessEqual(names, allowed, route)

    def test_changing_a_letter_needs_the_change_flag_and_the_letterhead_itself_an_admin(self):
        found = guards(letterhead_router.router)
        for route in ("POST /letterhead/letters", "PUT /letterhead/letters/{letter_id}", "DELETE /letterhead/letters/{letter_id}"):
            self.assertEqual(found[route], {"require_letterhead_write"}, route)
        for route in ("PUT /letterhead/design", "POST /letterhead/design/{part}", "DELETE /letterhead/design/{part}"):
            self.assertEqual(found[route], {"require_admin"}, route)
        for route in ("GET /letterhead/letters", "GET /letterhead/letters/{letter_id}", "POST /letterhead/stamp", "GET /letterhead/blank.pdf"):
            self.assertEqual(found[route], {"require_letterhead"}, route)

    def test_someone_with_only_billing_can_see_the_letterhead_to_print_a_bill_on_it(self):
        found = guards(letterhead_router.router)
        self.assertEqual(found["GET /letterhead/design"], {"require_letterhead_design"})
        self.assertEqual(found["GET /letterhead/design/{part}"], {"require_letterhead_design"})
        for name in ("require_letterhead", "require_letterhead_write", "require_letterhead_design"):
            self.assertTrue(callable(getattr(dependencies, name)))


class EditorAndServerAgree(unittest.TestCase):
    """The editor tidies pasted text with the same list of tags the server keeps."""

    def test_the_same_tags_are_kept_on_both_sides(self):
        import re

        source = (ROOT / "frontend" / "src" / "components" / "letterhead" / "richText.ts").read_text(encoding="utf-8")
        kept = set(re.findall(r"'([a-z0-9]+)'", re.search(r"const KEEP = new Set\(\[(.*?)\]\)", source, re.S).group(1)))
        server = letterhead._INLINE | letterhead._BLOCK | letterhead._VOID
        self.assertEqual(kept, server)
        renamed = dict(re.findall(r"(\w+): '(\w+)'", re.search(r"const RENAME: Record<string, string> = \{(.*?)\}", source, re.S).group(1)))
        self.assertEqual(renamed, letterhead._RENAME)


if __name__ == "__main__":
    unittest.main()
