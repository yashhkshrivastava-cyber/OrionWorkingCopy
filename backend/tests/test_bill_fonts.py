"""The typeface and size of a printed bill: the choices on offer, how a bill's own choice and the company's are
combined, that the browser's list is the server's, and that the PDF is drawn in the size asked for."""

import io
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pypdf import PdfReader  # noqa: E402

from app import bill_fonts, billing, billing_pdf  # noqa: E402

FRONTEND = Path(__file__).resolve().parents[2] / "frontend" / "src"


def sample_bill(**extra):
    return {
        "bill_number": "2026-27/1", "bill_date": "2026-08-05", "service_month": "2026-07-01", "party_name": "Client",
        "party_address": "Road", "status": "Issued", "profile": {**billing.DEFAULT_PROFILE},
        "lines": [{"particulars": "Vehicle", "qty": 1, "rate": 1000, "amount": 1000}],
        "rates": {"cgst_pct": 9, "sgst_pct": 9}, "lines_total": 1000, "taxable_total": 1000,
        "cgst_amount": 90, "sgst_amount": 90, "grand_total": 1180, **extra,
    }


def sizes_in(pdf: bytes) -> set[float]:
    """Every font size the PDF's text is set in."""
    found: set[float] = set()
    for page in PdfReader(io.BytesIO(pdf)).pages:
        found |= {round(float(size), 1) for size in re.findall(rb"([0-9.]+) Tf", page.get_contents().get_data())}
    return found


class Choices(unittest.TestCase):
    def test_a_known_typeface_and_size_are_accepted(self):
        self.assertEqual(bill_fonts.clean_family("Calibri"), "calibri")
        self.assertEqual(bill_fonts.clean_size("12"), 12.0)
        self.assertEqual(bill_fonts.clean_size(10.0), 10.0)

    def test_anything_else_is_refused(self):
        for bad in ("comic sans", "arial; x", "<b>"):
            with self.assertRaises(bill_fonts.FontError):
                bill_fonts.clean_family(bad)
        for bad in ("7", 15, "big", "9.5"):
            with self.assertRaises(bill_fonts.FontError):
                bill_fonts.clean_size(bad)

    def test_empty_means_follow_the_company_only_where_asked(self):
        self.assertIsNone(bill_fonts.clean_family("", allow_empty=True))
        self.assertIsNone(bill_fonts.clean_size(None, allow_empty=True))
        self.assertEqual(bill_fonts.clean_family(""), "arial")
        self.assertEqual(bill_fonts.clean_size(""), 9.0)

    def test_the_usual_size_is_on_offer(self):
        self.assertIn(bill_fonts.BASE_SIZE, bill_fonts.SIZES)
        self.assertIn(bill_fonts.DEFAULT_FAMILY, bill_fonts.FAMILIES)


class Effective(unittest.TestCase):
    def test_a_bill_with_no_choice_follows_the_company(self):
        company = {"font_family": "georgia", "font_size": 12}
        self.assertEqual(bill_fonts.effective({}, company), {"family": "georgia", "size": 12.0, "own": False})

    def test_a_bills_own_choice_wins_part_by_part(self):
        company = {"font_family": "georgia", "font_size": 12}
        self.assertEqual(bill_fonts.effective({"font_size": 14}, company), {"family": "georgia", "size": 14.0, "own": True})
        self.assertEqual(bill_fonts.effective({"font_family": "times"}, company), {"family": "times", "size": 12.0, "own": True})

    def test_nothing_set_anywhere_is_arial_nine(self):
        self.assertEqual(bill_fonts.effective({}, None), {"family": "arial", "size": 9.0, "own": False})

    def test_a_stored_value_that_no_longer_means_anything_is_ignored(self):
        self.assertEqual(bill_fonts.effective({"font_family": "gone", "font_size": 99}, {"font_family": "x"})["family"], "arial")

    def test_the_company_setting_is_not_frozen_into_a_bill(self):
        snapshot = billing.profile_snapshot({"company_name": "X", "font_family": "times", "font_size": 14})
        self.assertNotIn("font_family", snapshot)
        self.assertNotIn("font_size", snapshot)
        self.assertEqual(snapshot["company_name"], "X")

    def test_a_bill_is_given_only_choices_that_exist(self):
        self.assertEqual(billing._own_font({"font_family": "verdana", "font_size": "11"}), {"font_family": "verdana", "font_size": 11.0})
        self.assertEqual(billing._own_font({}), {"font_family": None, "font_size": None})
        with self.assertRaises(billing.BillError):
            billing._own_font({"font_family": "nope"})


class Browser(unittest.TestCase):
    """frontend/src/billing/billFonts.ts is the screen's copy of the catalogue."""

    def test_the_browsers_list_is_the_servers(self):
        text = (FRONTEND / "billing" / "billFonts.ts").read_text(encoding="utf-8")
        browser = re.findall(r"\{ key: '([a-z]+)', label: '([^']+)', css: '([^']+)' \}", text)
        server = [(key, item["label"], item["css"]) for key, item in bill_fonts.FAMILIES.items()]
        self.assertEqual(browser, server)
        sizes = re.search(r"FONT_SIZES = \[([0-9, ]+)\]", text).group(1)
        self.assertEqual([float(n) for n in sizes.split(",")], list(bill_fonts.SIZES))
        self.assertEqual(float(re.search(r"BASE_SIZE = ([0-9.]+)", text).group(1)), bill_fonts.BASE_SIZE)

    def test_the_printed_bill_uses_only_relative_sizes(self):
        """A pixel size in BillDocument.tsx would not follow the size chosen (the cancelled watermark is the one exception)."""
        text = (FRONTEND / "components" / "billing" / "BillDocument.tsx").read_text(encoding="utf-8")
        self.assertEqual(sorted(set(re.findall(r"text-\[([0-9.]+)px\]", text))), ["110"])


class Pdf(unittest.TestCase):
    def test_every_typeface_draws_at_every_size(self):
        for family in bill_fonts.FAMILIES:
            for size in (8.0, 14.0):
                pdf = billing_pdf.invoice_pdf(sample_bill(font={"family": family, "size": size}))
                self.assertTrue(pdf.startswith(b"%PDF"), f"{family} {size}")

    def test_the_size_scales_the_whole_bill(self):
        usual = sizes_in(billing_pdf.invoice_pdf(sample_bill()))
        large = sizes_in(billing_pdf.invoice_pdf(sample_bill(font={"family": "arial", "size": 13.0})))
        self.assertIn(9.0, usual)  # the body, as it has always been
        self.assertIn(13.0, large)
        self.assertGreater(max(large), max(usual))
        self.assertGreater(min(large), min(usual))

    def test_a_bill_with_no_choice_prints_as_it_always_did(self):
        plain = billing_pdf.invoice_pdf(sample_bill())
        stated = billing_pdf.invoice_pdf(sample_bill(font={"family": "arial", "size": 9.0}))
        self.assertEqual(sizes_in(plain), sizes_in(stated))

    def test_a_stored_bill_with_its_own_choice_is_drawn_in_it(self):
        """A stored version has font_family / font_size but no computed ``font``."""
        self.assertIn(12.0, sizes_in(billing_pdf.invoice_pdf(sample_bill(font_size=12))))

    def test_a_typeface_the_computer_lacks_falls_back_to_arial(self):
        self.assertEqual(billing_pdf.fonts("no-such-face"), billing_pdf.fonts("arial"))

    def test_only_known_typefaces_are_offered(self):
        for key in billing_pdf.available_families():
            self.assertIn(key, bill_fonts.FAMILIES)


if __name__ == "__main__":
    unittest.main()
