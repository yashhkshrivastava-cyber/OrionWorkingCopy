"""Reading bank statements: any bank's layout, dates and amounts as banks write them, and the running-balance check that says whether the
file was read right. No database."""

import sys
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import bank_statement as bs  # noqa: E402
from app.xlsx_io import write_xlsx  # noqa: E402

D = Decimal


def csv_bytes(text: str) -> bytes:
    return text.strip("\n").encode("utf-8")


# A statement the way one big bank exports it: account details above, a Withdrawal and a Deposit column, a wrapped narration, a closing line.
HDFC = """
Account Statement
Account No : 50100123456789
Statement From : 01/04/2026 To : 30/04/2026

Date,Narration,Chq./Ref.No.,Value Dt,Withdrawal Amt.,Deposit Amt.,Closing Balance
01/04/26,NEFT CR-ACME PLANT 1-INV 2026-27/185,UTIB0000123456,01/04/26,,"1,57,000.00","11,57,000.00"
03/04/26,CHQ PAID-000123-SECURITY SERVICES,000123,03/04/26,"25,000.00",,"11,32,000.00"
03/04/26,SMS CHARGES,,03/04/26,23.60,,"11,31,976.40"
15/04/26,NEFT DR-SALARY APRIL,,15/04/26,"2,00,000.00",,"9,31,976.40"
30/04/26,INT.PD:01-01-2026 TO 31-03-2026,,30/04/26,,1250.75,"9,33,227.15"
"""

# Another layout: signed Debit/Credit in separate columns with names, newest line first, month names in dates, a total row.
ICICI = """
Transaction Date,Value Date,S No.,Cheque Number,Transaction Remarks,Withdrawal Amount (INR),Deposit Amount (INR),Balance (INR)
30-Apr-2026,30-Apr-2026,3,,INTEREST CREDIT,,"1,250.75","9,33,227.15"
15-Apr-2026,15-Apr-2026,2,,SALARY APRIL,"2,00,000.00",,"9,31,976.40"
01-Apr-2026,01-Apr-2026,1,,NEFT FROM ACME,,"1,57,000.00","11,31,976.40"
Total,,,,,"2,00,000.00","1,58,250.75",
"""

# One signed amount column with Dr/Cr beside it, a 2-digit year, amounts that carry their own Dr/Cr.
AMOUNT_TYPE = """
Txn Date,Description,Amount,Dr/Cr,Balance
01-04-26,Client receipt,"10,000.00",CR,"60,000.00"
02-04-26,Rent,"4,000.00",DR,"56,000.00"
03-04-26,Bank charges,"100.00",DR,"55,900.00"
"""


class Dates(unittest.TestCase):
    def test_the_ways_banks_write_a_date(self):
        for text, expected in (
            ("31/03/26", date(2026, 3, 31)), ("31/03/2026", date(2026, 3, 31)), ("31-03-26", date(2026, 3, 31)), ("31.03.2026", date(2026, 3, 31)),
            ("31-Mar-2026", date(2026, 3, 31)), ("31 Mar 26", date(2026, 3, 31)), ("1 April 2026", date(2026, 4, 1)), ("2026-03-31", date(2026, 3, 31)),
            ("2026/03/31", date(2026, 3, 31)), ("31/03/2026 14:05:09", date(2026, 3, 31)), ("5/1/26", date(2026, 1, 5)),
        ):
            self.assertEqual(bs.parse_date(text), expected, text)

    def test_dates_are_day_first(self):
        self.assertEqual(bs.parse_date("04/05/2026"), date(2026, 5, 4))

    def test_an_excel_date(self):
        self.assertEqual(bs.parse_date(46113), date(2026, 4, 1))
        self.assertEqual(bs.parse_date(46113.0), date(2026, 4, 1))
        self.assertEqual(bs.parse_date(datetime_(2026, 4, 1)), date(2026, 4, 1))

    def test_what_is_not_a_date(self):
        for text in ("", None, "Opening Balance", "31/13/2026", "32/01/2026", "abc", "1234", 12, "TOTAL"):
            self.assertIsNone(bs.parse_date(text), repr(text))


def datetime_(y, m, d):
    from datetime import datetime

    return datetime(y, m, d, 10, 30)


class Money(unittest.TestCase):
    def test_amounts_as_banks_write_them(self):
        for text, expected in (
            ("1,57,000.00", D("157000.00")), ("1,234.5", D("1234.50")), ("₹ 2,000", D("2000.00")), ("500", D("500.00")), ("0.50", D("0.50")),
            ("(500.00)", D("-500.00")), ("-500", D("-500.00")), ("500-", D("-500.00")), ("Rs. 1,000.00", D("1000.00")),
        ):
            self.assertEqual(bs.parse_money(text)[0], expected, text)

    def test_a_number_cell(self):
        self.assertEqual(bs.parse_money(1250.75)[0], D("1250.75"))
        self.assertEqual(bs.parse_money(25000)[0], D("25000.00"))

    def test_dr_and_cr_on_the_amount(self):
        self.assertEqual(bs.parse_money("1,000.00 Cr"), (D("1000.00"), "cr"))
        self.assertEqual(bs.parse_money("1,000.00 DR"), (D("1000.00"), "dr"))

    def test_what_is_not_an_amount(self):
        for text in ("", None, "-", "--", "NA", "abc", "1.2.3", "Dr"):
            self.assertEqual(bs.parse_money(text), (None, None), repr(text))


class OneBanksLayout(unittest.TestCase):
    def setUp(self):
        self.parsed = bs.parse_statement("hdfc.csv", csv_bytes(HDFC))

    def test_the_table_is_found_below_the_account_details(self):
        self.assertEqual(self.parsed.header_row, 5)
        self.assertEqual(len(self.parsed.lines), 5)

    def test_the_columns_are_recognised(self):
        self.assertEqual(self.parsed.mapping, {"date": 0, "description": 1, "reference": 2, "debit": 4, "credit": 5, "balance": 6})

    def test_each_line_is_read(self):
        first, second, third = self.parsed.lines[:3]
        self.assertEqual((first.date, first.direction, first.amount), (date(2026, 4, 1), "in", D("157000.00")))
        self.assertIn("2026-27/185", first.description)
        self.assertEqual((second.direction, second.amount, second.reference), ("out", D("25000.00"), "000123"))
        self.assertEqual((third.amount, third.direction), (D("23.60"), "out"))

    def test_the_running_balance_checks_out(self):
        self.assertTrue(self.parsed.balanced)
        self.assertEqual((self.parsed.balance_checked, self.parsed.balance_breaks), (4, 0))
        self.assertEqual(self.parsed.opening_balance, D("1000000.00"))
        self.assertEqual(self.parsed.closing_balance, D("933227.15"))

    def test_the_period(self):
        self.assertEqual((self.parsed.period_from, self.parsed.period_to), (date(2026, 4, 1), date(2026, 4, 30)))


class AnotherLayoutNewestFirst(unittest.TestCase):
    def test_it_is_put_in_date_order_and_the_total_row_is_not_a_transaction(self):
        parsed = bs.parse_statement("icici.csv", csv_bytes(ICICI))
        self.assertTrue(parsed.newest_first)
        self.assertEqual([line.date for line in parsed.lines], [date(2026, 4, 1), date(2026, 4, 15), date(2026, 4, 30)])
        self.assertEqual(len(parsed.lines), 3)
        self.assertEqual(parsed.skipped_rows, 1)
        self.assertTrue(parsed.balanced)
        self.assertEqual(parsed.opening_balance, D("974976.40"))
        self.assertEqual(parsed.lines[0].direction, "in")

    def test_the_headers_with_units_in_brackets_are_recognised(self):
        parsed = bs.parse_statement("icici.csv", csv_bytes(ICICI))
        self.assertEqual({name: parsed.headers[index] for name, index in parsed.mapping.items()}["debit"], "Withdrawal Amount (INR)")
        self.assertEqual(parsed.headers[parsed.mapping["date"]], "Transaction Date")  # not Value Date

    def test_the_same_statement_oldest_first_reads_the_same(self):
        lines = ICICI.strip("\n").splitlines()
        reordered = "\n".join([lines[0], lines[3], lines[2], lines[1]])
        a = bs.parse_statement("a.csv", csv_bytes(ICICI))
        b = bs.parse_statement("b.csv", csv_bytes(reordered))
        self.assertFalse(b.newest_first)
        self.assertEqual([(x.date, x.amount, x.direction) for x in a.lines], [(x.date, x.amount, x.direction) for x in b.lines])


class OneSignedAmountColumn(unittest.TestCase):
    def test_dr_cr_beside_the_amount(self):
        parsed = bs.parse_statement("x.csv", csv_bytes(AMOUNT_TYPE))
        self.assertEqual([(line.direction, line.amount) for line in parsed.lines], [("in", D("10000.00")), ("out", D("4000.00")), ("out", D("100.00"))])
        self.assertTrue(parsed.balanced)
        self.assertEqual(parsed.opening_balance, D("50000.00"))

    def test_negative_amounts_with_no_type_column(self):
        text = "Date,Narration,Amount\n01/04/2026,Receipt,5000\n02/04/2026,Payment,-1200.50\n"
        parsed = bs.parse_statement("x.csv", csv_bytes(text))
        self.assertEqual([(line.direction, line.amount) for line in parsed.lines], [("in", D("5000.00")), ("out", D("1200.50"))])

    def test_direction_worked_out_from_the_balance_when_nothing_else_says(self):
        text = "Date,Narration,Amount,Balance\n,Opening Balance,,10000\n01/04/2026,A,5000,15000\n02/04/2026,B,1000,14000\n03/04/2026,C,250,14250\n"
        parsed = bs.parse_statement("x.csv", csv_bytes(text))
        self.assertEqual([line.direction for line in parsed.lines], ["in", "out", "in"])
        self.assertTrue(any("worked out from the balance" in issue.message for issue in parsed.issues))

    def test_direction_that_cannot_be_known_is_refused(self):
        with self.assertRaisesRegex(bs.StatementError, "debits and which are credits"):
            bs.parse_statement("x.csv", csv_bytes("Date,Narration,Amount\n01/04/2026,A,5000\n02/04/2026,B,1000\n"))


class AwkwardFiles(unittest.TestCase):
    def test_a_narration_that_wraps_onto_the_next_row(self):
        text = "Date,Narration,Debit,Credit\n01/04/2026,NEFT CR-ACME PLANT,,1000\n,1 INV 2026-27/185,,\n02/04/2026,Rent,500,\n"
        parsed = bs.parse_statement("x.csv", csv_bytes(text))
        self.assertEqual(len(parsed.lines), 2)
        self.assertEqual(parsed.lines[0].description, "NEFT CR-ACME PLANT 1 INV 2026-27/185")

    def test_page_breaks_with_the_header_repeated_are_skipped(self):
        text = "Date,Narration,Debit,Credit\n01/04/2026,A,,100\nDate,Narration,Debit,Credit\n02/04/2026,B,50,\n"
        parsed = bs.parse_statement("x.csv", csv_bytes(text))
        self.assertEqual(len(parsed.lines), 2)

    def test_semicolon_and_tab_delimited_files(self):
        for delimiter in (";", "\t", "|"):
            text = delimiter.join(["Date", "Narration", "Debit", "Credit"]) + "\n" + delimiter.join(["01/04/2026", "A", "", "100"]) + "\n"
            self.assertEqual(len(bs.parse_statement("x.csv", csv_bytes(text)).lines), 1, repr(delimiter))

    def test_a_file_in_windows_encoding_and_with_a_byte_order_mark(self):
        text = "Date,Narration,Debit,Credit\n01/04/2026,Caf\xe9 ₹,,100\n"
        parsed = bs.parse_statement("x.csv", ("﻿" + text).encode("utf-8"))
        self.assertEqual(len(parsed.lines), 1)
        legacy = bs.parse_statement("x.csv", "Date,Narration,Debit,Credit\n01/04/2026,Caf\xe9,,100\n".encode("cp1252"))
        self.assertIn("Caf", legacy.lines[0].description)

    def test_an_excel_file(self):
        rows = [
            ["Account Statement"], [],
            ["Txn Date", "Description", "Ref No./Cheque No.", "Debit", "Credit", "Balance"],
            [46113.0, "NEFT from client", "UTR123", None, 5000.0, 15000.0],
            [46114.0, "Rent", "", 2000.0, None, 13000.0],
        ]
        parsed = bs.parse_statement("s.xlsx", write_xlsx({"Statement": rows}))
        self.assertEqual([(line.date, line.direction, line.amount) for line in parsed.lines], [(date(2026, 4, 1), "in", D("5000.00")), (date(2026, 4, 2), "out", D("2000.00"))])
        self.assertTrue(parsed.balanced)

    def test_both_a_debit_and_a_credit_on_one_row_is_not_guessed(self):
        text = "Date,Narration,Debit,Credit\n01/04/2026,A,100,100\n02/04/2026,B,,50\n"
        parsed = bs.parse_statement("x.csv", csv_bytes(text))
        self.assertEqual(len(parsed.lines), 1)
        self.assertTrue(any(issue.severity == "error" and "both a debit and a credit" in issue.message for issue in parsed.issues))


class WhatIsRefused(unittest.TestCase):
    def test_a_pdf(self):
        with self.assertRaisesRegex(bs.StatementError, "PDF"):
            bs.parse_statement("s.pdf", b"%PDF-1.4 ...")

    def test_an_old_excel_file(self):
        with self.assertRaisesRegex(bs.StatementError, r"\.xls"):
            bs.parse_statement("s.xls", b"\xd0\xcf\x11\xe0 not a zip")

    def test_an_empty_file_and_a_huge_one(self):
        with self.assertRaisesRegex(bs.StatementError, "empty"):
            bs.parse_statement("s.csv", b"   \n")
        with self.assertRaisesRegex(bs.StatementError, "larger than"):
            bs.parse_statement("s.csv", b"x" * (bs.MAX_BYTES + 1))

    def test_a_file_that_is_not_a_statement(self):
        with self.assertRaisesRegex(bs.StatementError, "Could not find the table"):
            bs.parse_statement("s.csv", csv_bytes("Name,City\nAsha,Bhind\n"))

    def test_a_table_with_no_readable_lines(self):
        with self.assertRaisesRegex(bs.StatementError, "no transactions"):
            bs.parse_statement("s.csv", csv_bytes("Date,Narration,Debit,Credit\nnot a date,A,1,\n"))


class TheBalanceCheck(unittest.TestCase):
    def test_a_missing_line_is_found(self):
        text = AMOUNT_TYPE.replace("02-04-26,Rent,\"4,000.00\",DR,\"56,000.00\"\n", "")
        parsed = bs.parse_statement("x.csv", csv_bytes(text))
        self.assertFalse(parsed.balanced)
        self.assertEqual(parsed.balance_breaks, 1)
        self.assertTrue(any(issue.severity == "error" and "do not follow" in issue.message for issue in parsed.issues))

    def test_no_balance_column_means_nothing_to_check(self):
        parsed = bs.parse_statement("x.csv", csv_bytes("Date,Narration,Debit,Credit\n01/04/2026,A,,100\n02/04/2026,B,50,\n"))
        self.assertIsNone(parsed.balanced)
        self.assertIsNone(parsed.opening_balance)

    def test_a_wrong_column_choice_can_be_corrected(self):
        text = "Date,Narration,Debit,Credit,Other\n01/04/2026,A,,100,7\n"
        parsed = bs.parse_statement("x.csv", csv_bytes(text), mapping={"balance": 4})
        self.assertEqual(parsed.lines[0].balance, D("7.00"))


class Recognising(unittest.TestCase):
    def test_a_line_keeps_its_fingerprint_across_uploads(self):
        a = bs.parse_statement("a.csv", csv_bytes(HDFC))
        b = bs.parse_statement("b.csv", csv_bytes(HDFC))
        self.assertEqual(bs.fingerprints(a.lines), bs.fingerprints(b.lines))

    def test_the_same_period_in_a_different_layout_is_still_the_same_lines(self):
        """The fingerprint does not depend on the columns around the line, the balance, or the case of the narration."""
        a = bs.parse_statement("a.csv", csv_bytes("Date,Narration,Debit,Credit\n01/04/2026,Rent  Paid,500,\n"))
        b = bs.parse_statement("b.csv", csv_bytes("Txn Date,Description,Withdrawal,Deposit,Balance\n01-04-26,RENT PAID,500.00,,9500\n"))
        self.assertEqual(bs.fingerprints(a.lines), bs.fingerprints(b.lines))

    def test_two_identical_lines_on_one_day_are_two_lines(self):
        text = "Date,Narration,Debit,Credit\n01/04/2026,Tea,20,\n01/04/2026,Tea,20,\n01/04/2026,Tea,20,\n"
        prints = bs.fingerprints(bs.parse_statement("x.csv", csv_bytes(text)).lines)
        self.assertEqual(len(prints), 3)
        self.assertEqual(len(set(prints)), 3)

    def test_overlapping_periods_share_their_lines(self):
        first = "Date,Narration,Debit,Credit\n01/04/2026,A,10,\n02/04/2026,B,20,\n03/04/2026,C,30,\n"
        second = "Date,Narration,Debit,Credit\n02/04/2026,B,20,\n03/04/2026,C,30,\n04/04/2026,D,40,\n"
        p1 = set(bs.fingerprints(bs.parse_statement("a.csv", csv_bytes(first)).lines))
        p2 = set(bs.fingerprints(bs.parse_statement("b.csv", csv_bytes(second)).lines))
        self.assertEqual(len(p1 & p2), 2)

    def test_the_file_hash_recognises_the_same_file(self):
        self.assertEqual(bs.parse_statement("a.csv", csv_bytes(HDFC)).sha256, bs.parse_statement("b.csv", csv_bytes(HDFC)).sha256)
        self.assertNotEqual(bs.parse_statement("a.csv", csv_bytes(HDFC)).sha256, bs.parse_statement("a.csv", csv_bytes(ICICI)).sha256)


class WhatThePersonIsShown(unittest.TestCase):
    def test_the_summary_says_what_was_found_and_how(self):
        summary = bs.describe(bs.parse_statement("hdfc.csv", csv_bytes(HDFC)))
        self.assertEqual((summary["line_count"], summary["period_from"], summary["period_to"]), (5, "2026-04-01", "2026-04-30"))
        self.assertEqual((summary["money_in"], summary["money_out"]), (158250.75, 225023.6))
        self.assertEqual((summary["opening_balance"], summary["closing_balance"], summary["balanced"]), (1000000.0, 933227.15, True))
        self.assertEqual(summary["columns"]["debit"], "Withdrawal Amt.")
        self.assertEqual(len(summary["first_lines"]), 5)


if __name__ == "__main__":
    unittest.main()
