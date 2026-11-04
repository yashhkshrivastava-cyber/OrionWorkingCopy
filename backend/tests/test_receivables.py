"""Ageing, statements, recipients and message wording. None of it needs a database.

Run from the backend folder:  python -m unittest discover -s tests -v
"""

import sys
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.billing import DEFAULT_PROFILE, default_due_month, months_between  # noqa: E402
from app.billing_pdf import indian, invoice_pdf, rupees_in_words, statement_pdf  # noqa: E402
from app.receivables import (  # noqa: E402
    BUCKETS,
    ShareError,
    bucket_index,
    build_receivables,
    parse_emails,
    reminder_message,
    whatsapp_number,
    whatsapp_url,
)

D = Decimal
TODAY = date(2026, 10, 4)


def bill(number, bill_date, total, received=0, client="CL-1", name="Civil Surgeon"):
    return {
        "id": f"BILL-{number}", "bill_number": number, "bill_date": bill_date, "service_month": bill_date.replace(day=1),
        "grand_total": D(total), "received": D(received), "case_code": "CS-1", "case_name": "Hospital",
        "client_code": client, "client_name": name, "billing_name": None, "location": None,
    }


class AgeBuckets(unittest.TestCase):
    def test_edges_of_each_bucket(self):
        edges = [0, 30, 31, 60, 61, 90, 91, 400]
        self.assertEqual([bucket_index(days) for days in edges], [0, 0, 1, 1, 2, 2, 3, 3])

    def test_there_are_four_labelled_buckets(self):
        self.assertEqual([label for _low, _high, label in BUCKETS],
                         ["0–30 days", "31–60 days", "61–90 days", "Over 90 days"])


class Receivables(unittest.TestCase):
    def setUp(self):
        self.report = build_receivables(
            [
                bill("2026-27/180", date(2026, 6, 5), "100000", "25000"),  # 121 days, part paid
                bill("2026-27/202", date(2026, 8, 1), "919149"),  # 64 days
                bill("2026-27/210", date(2026, 9, 28), "50000", "50000", client="CL-2", name="Paid Up"),  # settled
                bill("2026-27/215", date(2026, 10, 1), "20000", client="CL-3", name="Alpha"),  # 3 days
            ],
            TODAY,
        )

    def test_a_bill_paid_in_full_is_left_out(self):
        self.assertEqual([c["client_code"] for c in self.report["clients"]], ["CL-1", "CL-3"])

    def test_balance_is_the_total_less_what_was_received(self):
        first = self.report["clients"][0]["bills"][0]
        self.assertEqual((first["grand_total"], first["received"], first["balance"]), (100000, 25000, 75000))

    def test_a_client_is_split_across_age_buckets(self):
        client = self.report["clients"][0]
        self.assertEqual(client["buckets"], [0, 0, 919149, 75000])
        self.assertEqual(client["total"], 994149)
        self.assertEqual(client["oldest_days"], 121)

    def test_bills_run_oldest_first_and_clients_largest_first(self):
        client = self.report["clients"][0]
        self.assertEqual([b["bill_number"] for b in client["bills"]], ["2026-27/180", "2026-27/202"])
        self.assertEqual([c["client_name"] for c in self.report["clients"]], ["Civil Surgeon", "Alpha"])

    def test_totals_add_up(self):
        totals = self.report["totals"]
        self.assertEqual(totals["buckets"], [20000, 0, 919149, 75000])
        self.assertEqual(totals["total"], sum(totals["buckets"]))
        self.assertEqual((totals["clients"], totals["bills"]), (2, 3))

    def test_a_bill_dated_after_the_report_date_is_zero_days_old(self):
        report = build_receivables([bill("X/1", date(2026, 10, 9), "1000")], TODAY)
        self.assertEqual(report["clients"][0]["bills"][0]["days"], 0)

    def test_the_latest_reminder_of_a_client_is_kept(self):
        older, newer = bill("A/1", date(2026, 8, 1), "100"), bill("A/2", date(2026, 9, 1), "100")
        from datetime import datetime
        older["last_reminder"], newer["last_reminder"] = datetime(2026, 9, 1, 10), datetime(2026, 9, 20, 10)
        entry = build_receivables([older, newer], TODAY)["clients"][0]
        self.assertTrue(entry["last_reminder"].startswith("2026-09-20"))


class Recipients(unittest.TestCase):
    def test_one_or_several_addresses(self):
        self.assertEqual(parse_emails(" a@x.com "), "a@x.com")
        self.assertEqual(parse_emails("a@x.com; b@y.in, c@z.org"), "a@x.com, b@y.in, c@z.org")

    def test_a_bad_or_missing_address_is_refused(self):
        for value in ("", "   ", "not-an-address", "a@x.com, oops"):
            with self.assertRaises(ShareError):
                parse_emails(value)

    def test_too_many_addresses_are_refused(self):
        with self.assertRaises(ShareError):
            parse_emails(", ".join(f"u{i}@x.com" for i in range(6)))

    def test_indian_mobile_numbers_get_the_country_code(self):
        self.assertEqual(whatsapp_number("98765 43210"), "919876543210")
        self.assertEqual(whatsapp_number("09876543210"), "919876543210")
        self.assertEqual(whatsapp_number("+91 98765-43210"), "919876543210")
        self.assertEqual(whatsapp_number("+44 7911 123456"), "447911123456")

    def test_a_short_number_is_refused(self):
        with self.assertRaises(ShareError):
            whatsapp_number("12345")

    def test_the_whatsapp_link_carries_the_encoded_text(self):
        self.assertEqual(whatsapp_url("919876543210", "Hi & bye"), "https://wa.me/919876543210?text=Hi%20%26%20bye")


class Wording(unittest.TestCase):
    def test_reminder_lists_every_bill_and_the_total(self):
        statement = {
            **build_receivables([bill("2026-27/202", date(2026, 8, 1), "919149")], TODAY)["clients"][0],
            "as_of": TODAY.isoformat(),
        }
        text = reminder_message(statement, DEFAULT_PROFILE)
        self.assertIn("Dear Civil Surgeon", text)
        self.assertIn("1. Bill 2026-27/202 dated 01 Aug 2026 (August 2026): ₹9,19,149.00, 64 days old", text)
        self.assertIn("Total outstanding: ₹9,19,149.00", text)
        self.assertIn("ICICI Bank", text)


class Formatting(unittest.TestCase):
    def test_indian_grouping(self):
        self.assertEqual(indian(919149), "9,19,149.00")
        self.assertEqual(indian("1234567.5"), "12,34,567.50")
        self.assertEqual(indian(999), "999.00")
        self.assertEqual(indian(-1500.25), "-1,500.25")
        self.assertEqual(indian(0), "0.00")

    def test_amount_in_words_matches_the_screen(self):
        self.assertEqual(rupees_in_words(919149), "Nine Lakh Nineteen Thousand One Hundred Forty Nine Rupees Only")
        self.assertEqual(rupees_in_words(0), "Zero Rupees Only")
        self.assertEqual(rupees_in_words(1), "One Rupee Only")
        self.assertEqual(rupees_in_words(12_50_00_000), "Twelve Crore Fifty Lakh Rupees Only")
        self.assertEqual(rupees_in_words(100_00_00_000), "One Hundred Crore Rupees Only")

    def test_pdfs_are_produced(self):
        sample = {
            "bill_number": "2026-27/202", "bill_date": "2026-08-01", "service_month": "2026-07-01", "party_name": "Civil Surgeon",
            "status": "Issued", "lines": [{"particulars": "Skilled", "qty": 3, "rate": 100, "amount": 300}],
            "rates": {"epf_pct": 13, "esic_pct": 3.25, "service_pct": 10, "cgst_pct": 9, "sgst_pct": 9},
            "lines_total": 300, "epf_amount": 39, "esic_amount": 9.75, "sub_total": 348.75, "service_amount": 30,
            "taxable_total": 378.75, "cgst_amount": 34.09, "sgst_amount": 34.09, "round_off": 0.07, "grand_total": 447,
            "profile": DEFAULT_PROFILE,
        }
        self.assertTrue(invoice_pdf(sample).startswith(b"%PDF"))
        entry = build_receivables([bill("A/1", date(2026, 8, 1), "1000")], TODAY)
        statement = {**entry["clients"][0], "as_of": entry["as_of"], "bucket_labels": entry["bucket_labels"]}
        self.assertTrue(statement_pdf(statement, DEFAULT_PROFILE).startswith(b"%PDF"))


class DueMonth(unittest.TestCase):
    def test_the_month_to_bill_is_last_month(self):
        self.assertEqual(default_due_month(date(2026, 10, 4)), date(2026, 9, 1))
        self.assertEqual(default_due_month(date(2026, 1, 15)), date(2025, 12, 1))

    def test_months_between(self):
        self.assertEqual(months_between(date(2026, 8, 1), date(2026, 9, 1)), 1)
        self.assertEqual(months_between(date(2025, 11, 1), date(2026, 2, 1)), 3)


if __name__ == "__main__":
    unittest.main()
