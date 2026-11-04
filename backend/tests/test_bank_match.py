"""Matching statement lines to the book: what is certain, what is only suggested, and what is left alone. No database."""

import sys
import unittest
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import bank_match as bm  # noqa: E402

D0 = date(2026, 4, 10)


def line(line_id, amount, *, direction="in", days=0, description="", reference=""):
    return {"line_id": line_id, "amount": amount, "direction": direction, "line_date": D0 + timedelta(days=days), "description": description, "reference": reference}


def move(ref, amount, *, direction="in", days=0, counterparty=None, reference=None, source="revenue", detail=None):
    return {
        "source": source, "source_ref": ref, "amount": amount, "direction": direction, "move_date": D0 + timedelta(days=days),
        "counterparty": counterparty, "reference": reference, "detail": detail,
    }


class Candidates(unittest.TestCase):
    def test_the_amount_and_direction_must_be_exactly_right(self):
        movements = [move("A", 1000), move("B", 1000.01), move("C", 1000, direction="out"), move("D", 999.99)]
        found = bm.candidates(line(1, 1000), movements)
        self.assertEqual([c.movement["source_ref"] for c in found], ["A"])

    def test_the_date_must_be_near(self):
        found = bm.candidates(line(1, 1000), [move("near", 1000, days=3), move("far", 1000, days=40)])
        self.assertEqual([c.movement["source_ref"] for c in found], ["near"])

    def test_a_closer_date_ranks_higher(self):
        found = bm.candidates(line(1, 1000), [move("late", 1000, days=4), move("same", 1000, days=0), move("next", 1000, days=1)])
        self.assertEqual([c.movement["source_ref"] for c in found], ["same", "next", "late"])

    def test_a_bill_number_on_the_line_ranks_a_candidate_first(self):
        found = bm.candidates(
            line(1, 5000, days=0, description="NEFT CR-UTIB0000123-ACME PLANT-INV 2026-27/185"),
            [move("X", 5000, days=0, reference="2026-27/177"), move("Y", 5000, days=3, reference="2026-27/185")],
        )
        self.assertEqual(found[0].movement["source_ref"], "Y")
        self.assertTrue(found[0].strong_text)
        self.assertTrue(any("2026-27/185" in reason for reason in found[0].reasons))

    def test_a_clients_name_helps_but_is_not_needed(self):
        found = bm.candidates(line(1, 5000, description="NEFT CR ACME INDUSTRIES"), [move("X", 5000, counterparty="Acme Industries Pvt Ltd"), move("Y", 5000, counterparty="Civil Hospital")])
        self.assertEqual(found[0].movement["source_ref"], "X")
        self.assertFalse(found[0].strong_text)
        self.assertEqual(len(found), 2)

    def test_the_banks_own_words_are_not_a_name(self):
        self.assertEqual(bm.tokens("NEFT CR-IMPS PAYMENT FROM BANK LIMITED"), set())
        self.assertIn("acme", bm.tokens("NEFT CR ACME"))

    def test_a_short_reference_is_not_enough_to_mean_anything(self):
        score, reasons = bm.text_signals(line(1, 1, description="CS-0001 and 12345"), move("X", 1, reference="CS-0001"))
        self.assertEqual((score, reasons), (0, ()))


class MatchedWithoutAsking(unittest.TestCase):
    def pairs(self, lines, movements):
        return [(a["line_id"], b["source_ref"]) for a, b in bm.auto_pairs(lines, movements)]

    def test_one_line_one_movement(self):
        self.assertEqual(self.pairs([line(1, 1500)], [move("A", 1500, days=1)]), [(1, "A")])

    def test_nothing_that_fits_is_left_alone(self):
        self.assertEqual(self.pairs([line(1, 1500)], [move("A", 1400)]), [])

    def test_two_movements_that_fit_one_line_are_not_guessed(self):
        self.assertEqual(self.pairs([line(1, 1500)], [move("A", 1500), move("B", 1500, days=1)]), [])

    def test_two_lines_that_fit_one_movement_are_not_guessed(self):
        self.assertEqual(self.pairs([line(1, 1500), line(2, 1500, days=1)], [move("A", 1500)]), [])

    def test_two_of_each_with_the_same_amount_are_not_guessed(self):
        self.assertEqual(self.pairs([line(1, 100), line(2, 100)], [move("A", 100), move("B", 100)]), [])

    def test_the_bill_number_settles_which_of_two(self):
        lines = [line(1, 5000, description="INV 2026-27/185 ACME")]
        movements = [move("A", 5000, reference="2026-27/185"), move("B", 5000, reference="2026-27/177")]
        self.assertEqual(self.pairs(lines, movements), [(1, "A")])

    def test_the_bill_number_settles_two_lines_and_two_movements(self):
        lines = [line(1, 5000, description="PAID 2026-27/185"), line(2, 5000, description="PAID 2026-27/177")]
        movements = [move("A", 5000, reference="2026-27/185"), move("B", 5000, reference="2026-27/177")]
        self.assertEqual(sorted(self.pairs(lines, movements)), [(1, "A"), (2, "B")])

    def test_a_movement_is_used_once(self):
        lines = [line(1, 5000, description="2026-27/185"), line(2, 5000, description="2026-27/185")]
        pairs = self.pairs(lines, [move("A", 5000, reference="2026-27/185")])
        self.assertLessEqual(len(pairs), 1)

    def test_a_date_too_far_for_certainty_is_a_suggestion_not_a_match(self):
        lines = [line(1, 1500)]
        movements = [move("A", 1500, days=9)]
        self.assertEqual(self.pairs(lines, movements), [])
        self.assertEqual(len(bm.candidates(lines[0], movements)), 1)


class OneDepositSeveralBills(unittest.TestCase):
    def test_movements_that_add_up_to_the_line(self):
        movements = [move("A", 40000, days=-2), move("B", 35000, days=-1), move("C", 25000, days=0), move("D", 12345)]
        found = bm.combinations_for(line(1, 100000), movements)
        self.assertEqual([sorted(m["source_ref"] for m in group) for group in found], [["A", "B", "C"]])

    def test_fewest_movements_first(self):
        movements = [move("A", 60000), move("B", 40000), move("C", 50000), move("D", 30000), move("E", 20000)]
        found = bm.combinations_for(line(1, 100000), movements)
        self.assertTrue(all(len(group) == 2 for group in found))
        self.assertIn(["A", "B"], [sorted(m["source_ref"] for m in group) for group in found])

    def test_only_the_same_direction_and_the_same_period(self):
        movements = [move("A", 40000), move("B", 60000, direction="out"), move("C", 60000, days=60)]
        self.assertEqual(bm.combinations_for(line(1, 100000), movements), [])

    def test_a_busy_month_cannot_make_it_slow(self):
        movements = [move(f"M{i}", 100 + i) for i in range(200)]
        import time

        started = time.monotonic()
        bm.combinations_for(line(1, 1_000_000), movements)
        self.assertLess(time.monotonic() - started, 5)

    def test_it_never_matches_a_single_movement(self):
        self.assertEqual(bm.combinations_for(line(1, 100), [move("A", 100)]), [])


class WhatIsThisLine(unittest.TestCase):
    def kind(self, description, direction):
        found = bm.classify(line(1, 100, direction=direction, description=description))
        return found["category"] if found else None

    def test_interest(self):
        for text in ("INT.PD:01-01-2026 TO 31-03-2026", "Interest credit for Q4", "SB INT CREDITED", "CREDIT INTEREST"):
            self.assertEqual(self.kind(text, "in"), "interest", text)

    def test_charges(self):
        for text in ("SMS CHARGES", "ANNUAL FEE DEBIT CARD", "MIN BAL PENALTY", "ECS RETURN CHARGES", "AMC CHGS"):
            self.assertEqual(self.kind(text, "out"), "bank_charges", text)

    def test_taxes_and_statutory_payments(self):
        self.assertEqual(self.kind("ADVANCE TAX CHALLAN ITNS 280", "out"), "tax")
        self.assertEqual(self.kind("GST PAYMENT CBIC", "out"), "gst_other")
        self.assertEqual(self.kind("EPFO PF PAYMENT", "out"), "statutory")
        self.assertEqual(self.kind("ESIC CONTRIBUTION", "out"), "statutory")

    def test_salary_and_loans_and_refunds(self):
        self.assertEqual(self.kind("NEFT SALARY APRIL", "out"), "salary")
        self.assertEqual(self.kind("EMI 4/36 LOAN A/C", "out"), "loan_repayment")
        self.assertEqual(self.kind("REFUND OF EXCESS PAID", "in"), "refund")

    def test_the_direction_must_fit(self):
        self.assertIsNone(self.kind("INTEREST CREDIT", "out"))
        self.assertIsNone(self.kind("SMS CHARGES", "in"))

    def test_an_ordinary_line_is_not_guessed(self):
        self.assertIsNone(self.kind("NEFT CR-ACME PLANT 1-INVOICE", "in"))
        self.assertIsNone(self.kind("CHQ PAID-000123-SECURITY SERVICES", "out"))

    def test_the_reason_is_in_plain_words(self):
        self.assertIn("interest", bm.classify(line(1, 100, description="INT.PD"))["why"])


class BeforeLeavingThisComputer(unittest.TestCase):
    def test_long_numbers_are_cut_to_their_last_four_digits(self):
        self.assertEqual(bm.mask_numbers("NEFT CR 50100123456789 UTR UTIB0000123456"), "NEFT CR …6789 UTR UTIB…3456")

    def test_short_numbers_and_words_stay(self):
        self.assertEqual(bm.mask_numbers("CHQ 000123 RENT 4/36"), "CHQ 000123 RENT 4/36")


if __name__ == "__main__":
    unittest.main()
