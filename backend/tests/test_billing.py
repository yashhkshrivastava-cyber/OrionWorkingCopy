"""Bill arithmetic and numbering, checked against the bills in use today.

Run from the backend folder:  python -m unittest discover -s tests -v
"""

import json
import sys
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import billing  # noqa: E402
from app.billing import (  # noqa: E402
    BillError,
    _differs,
    bill_number,
    compute_bill,
    fy_label,
    fy_start_year,
    split_payment,
)
from app.entities import locked_reason  # noqa: E402

D = Decimal


class SampleInvoice(unittest.TestCase):
    """Tax invoice 2026-27/202, July 2026, Civil Surgeon Bhind: grand total 9,19,149."""

    def setUp(self):
        self.bill = compute_bill(
            [
                {"particulars": "Skilled (SUPERVISOR)", "qty": 3, "rate": 15144},
                {"particulars": "UnSkilled (Safaikarmi)", "qty": 46, "rate": 12425},
            ]
        )

    def test_lines(self):
        amounts = [row["amount"] for row in self.bill["lines"]]
        self.assertEqual(amounts, [D("45432.00"), D("571550.00")])
        self.assertEqual(self.bill["lines_total"], D("616982.00"))

    def test_charges_on_the_lines_total(self):
        self.assertEqual(self.bill["epf_amount"], D("80207.66"))  # 13% -> printed 80208
        self.assertEqual(self.bill["esic_amount"], D("20051.92"))  # 3.25% -> printed 20052
        self.assertEqual(self.bill["sub_total"], D("717241.58"))  # printed 717242
        self.assertEqual(self.bill["service_amount"], D("61698.20"))  # 10% of lines -> printed 61698
        self.assertEqual(self.bill["taxable_total"], D("778939.78"))  # printed 778940

    def test_gst_and_grand_total(self):
        self.assertEqual(self.bill["cgst_amount"], D("70104.58"))  # printed 70105
        self.assertEqual(self.bill["sgst_amount"], D("70104.58"))
        self.assertEqual(self.bill["grand_total"], D("919149"))  # the figure on the bill
        self.assertEqual(self.bill["round_off"], D("0.06"))

    def test_printed_whole_rupees_match_the_excel_bill(self):
        def shown(key):
            return int(self.bill[key].quantize(D("1"), rounding="ROUND_HALF_UP"))

        self.assertEqual(
            [shown(k) for k in ("epf_amount", "esic_amount", "sub_total", "service_amount", "taxable_total", "cgst_amount")],
            [80208, 20052, 717242, 61698, 778940, 70105],
        )


class RegisterRows(unittest.TestCase):
    """Rows from the Excel bills register, which show GST is not always 9% + 9%."""

    def test_vehicle_rent_at_six_percent_each(self):
        bill = compute_bill(
            [{"particulars": "Vehicle rent", "qty": 1, "rate": "34821.43"}],
            {"epf_pct": 0, "esic_pct": 0, "service_pct": 0, "cgst_pct": 6, "sgst_pct": 6},
        )
        self.assertEqual(bill["taxable_total"], D("34821.43"))
        self.assertEqual(round(bill["cgst_amount"]), 2089)  # register shows 2089
        self.assertEqual(bill["grand_total"], D("39000"))  # register shows 39000

    def test_a_bill_with_no_gst_at_all(self):
        bill = compute_bill(
            [{"particulars": "Site", "qty": 1, "rate": 92562}],
            {"epf_pct": 0, "esic_pct": 0, "service_pct": 0, "cgst_pct": 0, "sgst_pct": 0},
        )
        self.assertEqual(bill["grand_total"], D("92562"))
        self.assertEqual(bill["cgst_amount"], D("0"))


class ExtraCharges(unittest.TestCase):
    """Charges a user names on one bill. They count towards the taxable value, so GST is charged on them."""

    lines = [{"particulars": "Vehicle rent", "qty": 1, "rate": 10000}]
    no_charges = {"epf_pct": 0, "esic_pct": 0, "service_pct": 0, "cgst_pct": 9, "sgst_pct": 9}

    def test_a_percentage_charge_is_on_the_lines_total(self):
        bill = compute_bill(self.lines, self.no_charges, [{"label": "Fuel surcharge", "kind": "pct", "value": 5}])
        self.assertEqual(bill["extra_charges"][0]["amount"], D("500"))
        self.assertEqual(bill["taxable_total"], D("10500"))
        self.assertEqual(bill["cgst_amount"], D("945"))
        self.assertEqual(bill["grand_total"], D("12390"))  # 10500 + 945 + 945

    def test_a_fixed_charge_is_added_as_it_is(self):
        bill = compute_bill(self.lines, self.no_charges, [{"label": "Toll", "kind": "amount", "value": "250.50"}])
        self.assertEqual(bill["extra_charges"][0]["amount"], D("250.50"))
        self.assertEqual(bill["taxable_total"], D("10250.50"))

    def test_extra_charges_sit_beside_the_standard_ones(self):
        bill = compute_bill(self.lines, {**self.no_charges, "service_pct": 10}, [{"label": "Toll", "kind": "amount", "value": 100}])
        self.assertEqual(bill["taxable_total"], D("11100"))  # 10000 + service 1000 + toll 100
        self.assertEqual(bill["sub_total"], D("10000"))  # the sub total stays lines + EPFO + ESIC

    def test_a_bill_without_extra_charges_is_what_it_was(self):
        self.assertEqual(compute_bill(self.lines, self.no_charges)["extra_charges"], [])
        self.assertEqual(compute_bill(self.lines, self.no_charges, None)["grand_total"], D("11800"))

    def test_a_blank_row_is_ignored_and_a_half_filled_one_is_refused(self):
        bill = compute_bill(self.lines, self.no_charges, [{"label": "", "kind": "pct", "value": ""}])
        self.assertEqual(bill["extra_charges"], [])
        with self.assertRaises(BillError):
            compute_bill(self.lines, self.no_charges, [{"label": "", "kind": "pct", "value": 5}])
        with self.assertRaises(BillError):
            compute_bill(self.lines, self.no_charges, [{"label": "Toll", "kind": "amount", "value": "lots"}])
        with self.assertRaises(BillError):
            compute_bill(self.lines, self.no_charges, [{"label": "Too much", "kind": "pct", "value": 101}])
        with self.assertRaises(BillError):
            compute_bill(self.lines, self.no_charges, [{"label": "Toll", "kind": "weekly", "value": 5}])

    def test_a_name_with_no_value_is_a_charge_of_nothing(self):
        bill = compute_bill(self.lines, self.no_charges, [{"label": "Toll", "kind": "amount", "value": None}])
        self.assertEqual(bill["extra_charges"][0]["amount"], D("0"))
        self.assertEqual(bill["taxable_total"], D("10000"))

    def test_there_is_a_limit_on_how_many(self):
        many = [{"label": f"Charge {i}", "kind": "amount", "value": 1} for i in range(billing.MAX_EXTRA_CHARGES + 1)]
        with self.assertRaises(BillError):
            compute_bill(self.lines, self.no_charges, many)


class HiddenParts(unittest.TestCase):
    def test_only_known_parts_can_be_hidden(self):
        self.assertEqual(billing.clean_hidden(["pf_no", "esi_no", "pf_no"]), ["esi_no", "pf_no"])
        self.assertEqual(billing.clean_hidden(None), [])
        with self.assertRaises(BillError):
            billing.clean_hidden(["pf_no", "grand_total"])  # the grand total always prints

    def test_the_bill_keeps_what_was_hidden_and_the_charges_it_named(self):
        from app.billing import _clean_bill

        class Cur:  # the case lookup _clean_bill makes
            def execute(self, *args):
                pass

            def fetchone(self):
                return ("CL-0001",)

        values = _clean_bill(Cur(), {
            "bill_date": date(2026, 8, 5), "service_month": "2026-07", "case_code": "CS-0001", "party_name": "Client",
            "lines": [{"particulars": "Vehicle", "qty": 1, "rate": 1000}],
            "rates": {"epf_pct": 0, "esic_pct": 0, "service_pct": 0},
            "extra_charges": [{"label": "Toll", "kind": "amount", "value": 50}], "hidden": ["pf_no", "esi_no"],
        })
        self.assertEqual(json.loads(values["hidden"]), ["esi_no", "pf_no"])
        self.assertEqual(json.loads(values["extra_charges"])[0], {"label": "Toll", "kind": "amount", "value": 50.0, "amount": 50.0})
        self.assertEqual(values["taxable_total"], D("1050"))

    def test_header_details_need_a_name_and_a_value_and_blank_rows_are_ignored(self):
        clean = billing.clean_header_fields
        self.assertEqual(clean([{"label": " Vendor  code ", "value": "V-102"}, {"label": "", "value": ""}]),
                         [{"label": "Vendor code", "value": "V-102"}])
        self.assertEqual(clean(None), [])
        for half in ({"label": "Vendor code", "value": ""}, {"label": "", "value": "V-102"}):
            with self.assertRaises(BillError):
                clean([half])
        with self.assertRaises(BillError):
            clean([{"label": f"D{i}", "value": "x"} for i in range(billing.MAX_HEADER_FIELDS + 1)])

    def test_client_details_follow_the_same_rules_as_header_details(self):
        clean = billing.clean_party_fields
        self.assertEqual(clean([{"label": "State code", "value": "09"}]), [{"label": "State code", "value": "09"}])
        self.assertEqual(clean([{"label": "", "value": ""}]), [])
        with self.assertRaises(BillError) as caught:
            clean([{"label": "State code", "value": ""}])
        self.assertIn("client detail", str(caught.exception).lower())
        with self.assertRaises(BillError):
            clean([{"label": f"D{i}", "value": "x"} for i in range(billing.MAX_PARTY_FIELDS + 1)])

    def test_the_bill_stores_header_and_client_details_apart(self):
        from app.billing import _clean_bill

        class Cur:
            def execute(self, *args):
                pass

            def fetchone(self):
                return ("CL-0001",)

        values = _clean_bill(Cur(), {
            "bill_date": date(2026, 8, 5), "service_month": "2026-07", "case_code": "CS-0001", "party_name": "Client",
            "lines": [{"particulars": "Vehicle", "qty": 1, "rate": 1000}],
            "header_fields": [{"label": "Vendor code", "value": "V-1"}], "party_fields": [{"label": "State code", "value": "09"}],
        })
        self.assertEqual(json.loads(values["header_fields"]), [{"label": "Vendor code", "value": "V-1"}])
        self.assertEqual(json.loads(values["party_fields"]), [{"label": "State code", "value": "09"}])

    def test_changing_only_what_is_hidden_is_a_change_to_the_bill(self):
        stored = {"hidden": [], "extra_charges": []}
        self.assertTrue(_differs(stored, {"hidden": '["pf_no"]'}))
        self.assertFalse(_differs(stored, {"hidden": "[]", "extra_charges": "[]"}))


class LineLayout(unittest.TestCase):
    """How a bill's lines are laid out and worked out: by the day or month, with columns of its own, under a tender."""

    class Cur:
        def execute(self, *args):
            pass

        def fetchone(self):
            return ("CL-0001",)

    def clean(self, **data):
        from app.billing import _clean_bill

        return _clean_bill(self.Cur(), {
            "bill_date": date(2026, 11, 4), "service_month": "2026-10", "case_code": "CS-0001", "party_name": "Client",
            "lines": [{"particulars": "Vehicle", "qty": 1, "rate": 1000}], **data,
        })

    def test_an_empty_layout_is_the_original_one(self):
        setup = billing.clean_line_setup(None)
        self.assertEqual(setup, {"basis": "unit", "qty_multiplies": True, "month_days": None, "totals_row": False, "charge_by_line": False, "service_on": "lines", "labels": {}, "columns": []})
        self.assertEqual(billing.clean_line_setup({}), setup)
        row = compute_bill([{"particulars": "Vehicle", "qty": 2, "rate": "10.50"}])["lines"][0]
        self.assertEqual(set(row), {"particulars", "qty", "rate", "amount"})  # nothing new on a bill that does not use it

    def test_a_daily_rate_is_rate_times_days_and_the_quantity_can_be_left_out_of_it(self):
        lines = [{"particulars": "Staff", "qty": 22, "rate": 693, "days": 481}]
        alone = compute_bill(lines, line_setup={"basis": "daily", "qty_multiplies": False})["lines"][0]
        counted = compute_bill(lines, line_setup={"basis": "daily", "qty_multiplies": True})["lines"][0]
        self.assertEqual((alone["amount"], alone["days"]), (D("333333.00"), D("481.00")))
        self.assertEqual(counted["amount"], D("333333.00") * 22)

    def test_a_monthly_rate_is_shared_over_the_days_of_the_month(self):
        lines = [{"particulars": "Car", "qty": 1, "rate": 25000, "days": 10}]
        setup = {"basis": "monthly"}
        self.assertEqual(compute_bill(lines, line_setup=setup, service_month=date(2026, 10, 1))["lines"][0]["amount"], D("8064.52"))  # 31 days
        self.assertEqual(compute_bill(lines, line_setup=setup, service_month=date(2027, 2, 1))["lines"][0]["amount"], D("8928.57"))  # 28 days
        self.assertEqual(compute_bill(lines, line_setup={**setup, "month_days": 30}, service_month=date(2026, 10, 1))["lines"][0]["amount"], D("8333.33"))

    def test_a_monthly_line_with_no_days_is_the_whole_month(self):
        row = compute_bill([{"particulars": "Car", "qty": 1, "rate": "34821.43"}], line_setup={"basis": "monthly"}, service_month=date(2026, 10, 1))["lines"][0]
        self.assertEqual((row["amount"], row["days"]), (D("34821.43"), D("31")))

    def test_a_day_based_line_needs_its_days_and_a_counted_quantity(self):
        with self.assertRaises(BillError):
            compute_bill([{"particulars": "Guard", "qty": 1, "rate": 500}], line_setup={"basis": "daily"})
        with self.assertRaises(BillError):
            compute_bill([{"particulars": "Guard", "qty": 1, "rate": 500, "days": 0}], line_setup={"basis": "daily"})
        with self.assertRaises(BillError):
            compute_bill([{"particulars": "Guard", "rate": 500, "days": 3}], line_setup={"basis": "daily"})
        compute_bill([{"particulars": "Guard", "rate": 500, "days": 3}], line_setup={"basis": "daily", "qty_multiplies": False})

    def test_the_bills_own_columns_keep_a_value_for_every_line(self):
        setup = {"columns": [{"key": "area", "label": "Area"}]}
        rows = compute_bill([{"particulars": "A", "qty": 1, "rate": 5, "fields": {"area": " (B) ", "gone": "x"}}, {"particulars": "B", "qty": 1, "rate": 5}], line_setup=setup)["lines"]
        self.assertEqual([row["fields"] for row in rows], [{"area": "(B)"}, {"area": ""}])

    def test_a_line_with_only_a_column_value_is_not_blank(self):
        setup = {"columns": [{"key": "area", "label": "Area"}]}
        with self.assertRaises(BillError):
            compute_bill([{"particulars": "A", "qty": 1, "rate": 5}, {"qty": "", "rate": "", "fields": {"area": "C"}}], line_setup=setup)

    def test_the_layout_is_checked(self):
        bad = [{"basis": "weekly"}, {"month_days": 32}, {"month_days": "x"}, {"labels": {"colour": "Red"}},
               {"columns": [{"key": "Area", "label": "Area"}]}, {"columns": [{"key": "a", "label": ""}]},
               {"columns": [{"key": "a", "label": "A"}, {"key": "a", "label": "B"}]},
               {"columns": [{"key": f"c{i}", "label": "X"} for i in range(billing.MAX_LINE_COLUMNS + 1)]}]
        for setup in bad:
            with self.subTest(setup), self.assertRaises(BillError):
                billing.clean_line_setup(setup)
        self.assertEqual(billing.clean_line_setup({"labels": {"qty": "  No. of   Person ", "rate": ""}})["labels"], {"qty": "No. of Person"})

    def test_the_tender_and_the_layout_are_stored_with_the_bill(self):
        values = self.clean(tender_id="  GEM/2026/B/1 ", tender_start_date=date(2026, 1, 1), line_setup={"basis": "daily", "qty_multiplies": False},
                            lines=[{"particulars": "Staff", "qty": 2, "rate": 100, "days": 5}])
        self.assertEqual((values["tender_id"], values["tender_start_date"]), ("GEM/2026/B/1", date(2026, 1, 1)))
        self.assertEqual(json.loads(values["line_setup"])["basis"], "daily")
        self.assertEqual(json.loads(values["lines"])[0]["amount"], 500.0)
        none = self.clean()
        self.assertEqual((none["tender_id"], none["tender_start_date"]), (None, None))
        self.assertEqual(json.loads(none["line_setup"])["basis"], "unit")

    def test_a_tender_or_a_layout_change_is_a_change_to_the_bill(self):
        stored = {"tender_id": None, "tender_start_date": None, "line_setup": billing.clean_line_setup(None)}
        self.assertTrue(_differs(stored, {"tender_id": "T-1"}))
        self.assertTrue(_differs(stored, {"line_setup": json.dumps({**stored["line_setup"], "totals_row": True})}))
        self.assertFalse(_differs(stored, {"tender_id": None, "line_setup": json.dumps(stored["line_setup"])}))

    def test_the_tender_can_be_left_off_the_printed_bill(self):
        self.assertEqual(billing.clean_hidden(["tender_id", "tender_date"]), ["tender_date", "tender_id"])

    def test_the_pdf_has_the_columns_the_bill_chose(self):
        from app.billing_pdf import invoice_pdf, line_columns

        setup = {"basis": "daily", "qty_multiplies": False, "totals_row": True, "labels": {"particulars": "Category", "amount": "Total"},
                 "columns": [{"key": "area", "label": "Area"}]}
        figures = compute_bill([{"particulars": "Staff", "qty": 22, "rate": 693, "days": 481, "fields": {"area": "(B)"}}], line_setup=setup)
        chosen = {"line_setup": figures["line_setup"]}
        self.assertEqual([c for c, _ in line_columns(chosen)], ["particulars", "field:area", "qty", "rate", "days", "amount"])
        self.assertEqual([h for _, h in line_columns(chosen)], ["Category", "Area", "Qty", "Rate per day", "Days", "Total"])
        self.assertEqual([c for c, _ in line_columns({**chosen, "hidden": ["qty_rate"]})], ["particulars", "field:area", "amount"])
        self.assertEqual([c for c, _ in line_columns({})], ["particulars", "qty", "rate", "amount"])
        row = {key: float(value) if isinstance(value, Decimal) else value for key, value in figures["lines"][0].items()}
        bill = {"bill_number": "2026-27/1", "bill_date": "2026-11-04", "service_month": "2026-10-01", "party_name": "Client", "status": "Issued",
                "lines": [row], "line_setup": figures["line_setup"], "profile": {**billing.DEFAULT_PROFILE}, "tender_id": "GEM/2026/B/1",
                "tender_start_date": "2026-01-01", "ref_no": "\u0915\u094d\u0930./\u0905.\u092a\u094d\u0930\u093e\u0936\u093e./2026/209-16",
                "rates": {}, "extra_charges": [], "grand_total": 333333.0, "lines_total": 333333.0}
        for hidden in ([], ["tender_id", "tender_date"]):
            self.assertTrue(invoice_pdf({**bill, "hidden": hidden}).startswith(b"%PDF"))


class EnteredFigures(unittest.TestCase):
    """Lines left out of charges, and figures a person enters instead of the calculated ones."""

    LINES = [{"particulars": "Guard", "qty": 10, "rate": 1000}, {"particulars": "Vehicle", "qty": 1, "rate": 50000, "skip": ["epf", "esic", "service"]}]

    def test_a_charge_is_taken_of_the_lines_that_are_part_of_it(self):
        bill = compute_bill(self.LINES)
        self.assertEqual((bill["lines_total"], bill["epf_amount"], bill["esic_amount"], bill["service_amount"]), (D("60000.00"), D("1300.00"), D("325.00"), D("1000.00")))
        one = compute_bill([self.LINES[0], {**self.LINES[1], "skip": ["esic"]}])
        self.assertEqual((one["epf_amount"], one["esic_amount"], one["service_amount"]), (D("7800.00"), D("325.00"), D("6000.00")))

    def test_a_line_can_only_be_left_out_of_a_known_charge(self):
        with self.assertRaises(BillError):
            compute_bill([{**self.LINES[0], "skip": ["gst"]}])

    def test_an_entered_charge_stands_and_what_follows_is_worked_out_from_it(self):
        bill = compute_bill([self.LINES[0]], manual_figures={"epf_amount": "1000", "cgst_amount": "", "sgst_amount": "300.505"})
        self.assertEqual(bill["epf_amount"], D("1000.00"))
        self.assertEqual(bill["sub_total"], D("10000.00") + D("1000.00") + bill["esic_amount"])
        self.assertEqual(bill["sgst_amount"], D("300.51"))
        self.assertEqual(bill["cgst_amount"], D("1109.25"))  # 9% of the taxable value, which is worked out from the entered EPFO
        self.assertEqual(bill["manual_figures"], {"epf_amount": {"value": D("1000.00"), "auto": D("1300.00")},
                                                  "sgst_amount": {"value": D("300.51"), "auto": D("1109.25")}})

    def test_a_charge_with_no_percentage_can_still_be_entered(self):
        bill = compute_bill([self.LINES[0]], {"service_pct": 0}, manual_figures={"service_amount": "750.50"})
        self.assertEqual((bill["service_amount"], bill["taxable_total"] - bill["sub_total"]), (D("750.50"), D("750.50")))

    def test_only_known_figures_can_be_entered_and_they_must_be_amounts(self):
        for bad in ({"grand_total": "5"}, {"epf_amount": "x"}, {"epf_amount": "-1"}, {"cgst_amount": "10000000000.01"}):
            with self.subTest(bad), self.assertRaises(BillError):
                compute_bill([self.LINES[0]], manual_figures=bad)

    def test_a_line_amount_can_be_entered_and_keeps_what_it_would_have_been(self):
        rows = compute_bill([{"particulars": "Guard", "qty": 10, "rate": 1000, "amount_manual": "9999.99"},
                             {"particulars": "Lump sum", "qty": "", "rate": "", "amount_manual": "12500"},
                             {"particulars": "Driver", "qty": 1, "rate": 500}])["lines"]
        self.assertEqual([r["amount"] for r in rows], [D("9999.99"), D("12500.00"), D("500.00")])
        self.assertEqual((rows[0]["manual"], rows[0]["auto_amount"]), (True, D("10000.00")))
        self.assertEqual((rows[1]["manual"], rows[1]["auto_amount"], rows[1]["rate"], rows[1]["qty"]), (True, None, None, None))
        self.assertNotIn("manual", rows[2])

    def test_an_entered_line_amount_must_be_an_amount(self):
        for bad in ("abc", "-5", "10000000000.01"):
            with self.subTest(bad), self.assertRaises(BillError):
                compute_bill([{"particulars": "Guard", "qty": 10, "rate": 1000, "amount_manual": bad}])

    def test_the_bill_stores_what_was_entered_and_a_change_to_it_is_a_change(self):
        from app.billing import _clean_bill

        class Cur:
            def execute(self, *args):
                pass

            def fetchone(self):
                return ("CL-0001",)

        values = _clean_bill(Cur(), {"bill_date": date(2026, 8, 5), "service_month": "2026-07", "case_code": "CS-0001", "party_name": "Client",
                                     "lines": [{"particulars": "Guard", "qty": 10, "rate": 1000}], "manual_figures": {"epf_amount": "1000"}})
        self.assertEqual(json.loads(values["manual_figures"]), {"epf_amount": {"value": 1000.0, "auto": 1300.0}})
        self.assertTrue(_differs({"manual_figures": {}}, {"manual_figures": values["manual_figures"]}))
        self.assertFalse(_differs({"manual_figures": {}}, {"manual_figures": "{}"}))

    def test_the_totals_use_the_names_the_bill_gave_and_print_an_entered_charge_at_zero_percent(self):
        from app.billing_pdf import total_lines

        bill = compute_bill([self.LINES[0]], {"epf_pct": 13, "esic_pct": 0, "service_pct": 0, "cgst_pct": 9, "sgst_pct": 9},
                            line_setup={"labels": {"lines_total": "Wages Total", "epf": "EPF", "taxable_total": "Total"}},
                            manual_figures={"esic_amount": "100", "epf_amount": "1200"})
        row = {key: float(value) for key, value in bill.items() if isinstance(value, Decimal)}
        view = {**row, "rates": {k: float(v) for k, v in bill["rates"].items()}, "extra_charges": [], "line_setup": bill["line_setup"],
                "manual_figures": {k: {"value": float(v["value"]), "auto": float(v["auto"])} for k, v in bill["manual_figures"].items()}}
        self.assertEqual([label for label, _, _ in total_lines(view)], ["Wages Total", "EPF @ 13%", "ESIC", "Sub total", "Total", "CGST @ 9%", "SGST @ 9%"])

    def test_the_pdf_draws_a_bill_with_entered_figures_and_amount_only_lines(self):
        from app.billing_pdf import invoice_pdf

        bill = compute_bill([{"particulars": "Lump sum", "qty": "", "rate": "", "amount_manual": "12500"}], manual_figures={"epf_amount": "1"})
        row = {key: float(value) if isinstance(value, Decimal) else value for key, value in bill["lines"][0].items()}
        figures = {key: float(value) for key, value in bill.items() if isinstance(value, Decimal)}
        pdf = invoice_pdf({**figures, "bill_number": "2026-27/1", "bill_date": "2026-11-04", "service_month": "2026-10-01", "party_name": "Client",
                           "status": "Issued", "lines": [row], "line_setup": bill["line_setup"], "profile": {**billing.DEFAULT_PROFILE},
                           "rates": {k: float(v) for k, v in bill["rates"].items()}, "extra_charges": [],
                           "manual_figures": {k: {"value": float(v["value"]), "auto": float(v["auto"])} for k, v in bill["manual_figures"].items()}})
        self.assertTrue(pdf.startswith(b"%PDF"))


class ServiceChargeBasis(unittest.TestCase):
    """What the service charge's percentage is taken of: the lines (the original), or the lines with the EPFO and ESIC."""

    LINES = [{"particulars": "Guard", "qty": 10, "rate": 1000}]

    def test_the_lines_are_the_original_basis(self):
        bill = compute_bill(self.LINES)
        self.assertEqual(billing.clean_line_setup(None)["service_on"], "lines")
        self.assertEqual(bill["service_amount"], D("1000.00"))

    def test_on_the_lines_with_the_epfo_and_esic(self):
        bill = compute_bill(self.LINES, line_setup={"service_on": "lines_epf_esic"})
        self.assertEqual((bill["epf_amount"], bill["esic_amount"], bill["service_amount"]), (D("1300.00"), D("325.00"), D("1162.50")))

    def test_it_follows_an_epfo_that_was_entered_and_still_leaves_out_lines(self):
        entered = compute_bill(self.LINES, line_setup={"service_on": "lines_epf_esic"}, manual_figures={"epf_amount": "1000", "esic_amount": "0"})
        self.assertEqual(entered["service_amount"], D("1100.00"))
        left_out = compute_bill([*self.LINES, {"particulars": "Vehicle", "qty": 1, "rate": 50000, "skip": ["service"]}], line_setup={"service_on": "lines_epf_esic"})
        self.assertEqual(left_out["service_amount"], (D("10000.00") + left_out["epf_amount"] + left_out["esic_amount"]) / 10)

    def test_only_those_two_bases_exist(self):
        with self.assertRaises(BillError):
            billing.clean_line_setup({"service_on": "total"})


class OwnTemplateDetails(unittest.TestCase):
    """A bill can print its own bank details, terms, signature or company details instead of the template's."""

    TEMPLATE = billing.profile_snapshot({})

    def test_only_template_details_can_be_given_and_they_are_cleaned_like_the_template(self):
        clean = billing.clean_profile_fields({"bank_account": "  1234 ", "terms": ["  One  ", "", "Two"], "signatory": None})
        self.assertEqual(clean, {"bank_account": "1234", "terms": ["One", "Two"], "signatory": ""})
        for bad in ({"default_service_description": "x"}, {"font_family": "serif"}, {"terms": "one line"}, {"company_name": "  "}):
            with self.subTest(bad), self.assertRaises(BillError):
                billing.clean_profile_fields(bad)
        self.assertEqual(len(billing.clean_profile_fields({"terms": [str(i) for i in range(20)]})["terms"]), 8)

    def test_a_new_bill_prints_the_template_with_what_was_changed_and_remembers_only_that(self):
        profile, own = billing.apply_profile_edits(self.TEMPLATE, {}, self.TEMPLATE, {"bank_account": "999", "bank_ifsc": self.TEMPLATE["bank_ifsc"]})
        self.assertEqual(profile["bank_account"], "999")
        self.assertEqual(profile["bank_name"], self.TEMPLATE["bank_name"])
        self.assertEqual(own, {"bank_account": "999"})  # a value that is the template's is not the bill's own

    def test_an_edit_changes_only_what_was_sent_and_a_template_changed_since_is_not_an_edit(self):
        old_template = {**self.TEMPLATE, "bank_account": "OLD"}
        issued = {**old_template, "terms": ["Own term"]}  # the bill printed the old account and its own terms
        template_now = {**self.TEMPLATE, "bank_account": "NEW"}
        profile, own = billing.apply_profile_edits(issued, {"terms": ["Own term"]}, template_now, {"bank_account": "OLD", "terms": ["Own term"]})
        self.assertEqual((profile, own), (issued, {"terms": ["Own term"]}))  # nothing changed, so nothing is made its own
        profile, own = billing.apply_profile_edits(issued, {"terms": ["Own term"]}, template_now, {"bank_account": "NEW", "terms": self.TEMPLATE["terms"]})
        self.assertEqual((profile["bank_account"], profile["terms"], own), ("NEW", self.TEMPLATE["terms"], {}))  # back to the template's

    def test_changing_a_detail_is_a_change_to_the_bill(self):
        stored = {"profile": {"bank_account": "1"}, "profile_overrides": {}}
        self.assertTrue(_differs(stored, {"profile": json.dumps({"bank_account": "2"}), "profile_overrides": "{}"}))
        self.assertFalse(_differs(stored, {"profile": json.dumps({"bank_account": "1"}), "profile_overrides": "{}"}))

    def test_a_bill_with_its_own_details_draws(self):
        from app.billing_pdf import invoice_pdf

        profile, _ = billing.apply_profile_edits(self.TEMPLATE, {}, self.TEMPLATE, {"bank_name": "Other Bank", "terms": ["Pay in 7 days."], "gstin": "23AAAAA0000A1Z5"})
        figures = compute_bill([{"particulars": "Guard", "qty": 1, "rate": 100}])
        row = {k: float(v) if isinstance(v, Decimal) else v for k, v in figures["lines"][0].items()}
        bill = {**{k: float(v) for k, v in figures.items() if isinstance(v, Decimal)}, "bill_number": "2026-27/1", "bill_date": "2026-11-04",
                "service_month": "2026-10-01", "party_name": "Client", "status": "Issued", "lines": [row], "profile": profile,
                "rates": {k: float(v) for k, v in figures["rates"].items()}, "extra_charges": []}
        self.assertTrue(invoice_pdf(bill).startswith(b"%PDF"))


class PrintedTotals(unittest.TestCase):
    """The rows the PDF prints above the grand total (BillDocument.tsx draws the same ones)."""

    def bill(self, **changes):
        figures = compute_bill(
            [{"particulars": "Guard", "qty": 10, "rate": 1000}],
            {"epf_pct": 13, "esic_pct": 3.25, "service_pct": 10, "cgst_pct": 9, "sgst_pct": 9},
            [{"label": "Toll", "kind": "amount", "value": 100}],
        )
        row = {key: float(value) for key, value in figures.items() if isinstance(value, Decimal)}
        return {
            **row, "rates": {k: float(v) for k, v in figures["rates"].items()},
            "extra_charges": [{**c, "value": float(c["value"]), "amount": float(c["amount"])} for c in figures["extra_charges"]],
            **changes,
        }

    def labels(self, bill):
        from app.billing_pdf import total_lines

        return [label for label, _, _ in total_lines(bill)]

    def test_everything_prints_unless_it_is_left_off(self):
        self.assertEqual(
            self.labels(self.bill()),
            ["Total of lines", "EPFO @ 13%", "ESIC @ 3.25%", "Sub total", "Service charges @ 10%", "Toll",
             "Taxable value", "CGST @ 9%", "SGST @ 9%", "Round off"],
        )
        self.assertNotIn("Round off", self.labels(self.bill(hidden=["round_off"])))

    def test_a_charge_at_zero_percent_is_not_printed(self):
        bill = self.bill(rates={"epf_pct": 0, "esic_pct": 0, "service_pct": 10, "cgst_pct": 9, "sgst_pct": 9})
        labels = self.labels(bill)
        self.assertNotIn("Sub total", labels)
        self.assertFalse(any(label.startswith(("EPFO", "ESIC")) for label in labels))

    def test_hidden_totals_are_left_out_but_the_charges_stay(self):
        labels = self.labels(self.bill(hidden=["lines_total", "sub_total", "taxable_total"]))
        self.assertNotIn("Total of lines", labels)
        self.assertNotIn("Sub total", labels)
        self.assertNotIn("Taxable value", labels)
        self.assertIn("EPFO @ 13%", labels)
        self.assertIn("Toll", labels)

    def test_a_percentage_charge_is_labelled_with_its_rate(self):
        bill = self.bill(extra_charges=[{"label": "Fuel", "kind": "pct", "value": 2.5, "amount": 250.0}])
        self.assertIn("Fuel @ 2.5%", self.labels(bill))

    def test_the_pdf_draws_with_parts_left_off(self):
        from app.billing_pdf import invoice_pdf

        profile = {**billing.DEFAULT_PROFILE}
        base = {"bill_number": "2026-27/1", "bill_date": "2026-08-05", "service_month": "2026-07-01", "party_name": "Client",
                "party_gstin": "23ABCDE1234F1Z5", "party_address": "Road", "lines": [
                    {"particulars": "Vehicle", "qty": 1, "rate": 1000, "amount": 1000}], "profile": profile, "status": "Issued"}
        details = [{"label": f"Detail {i}", "value": f"V-{i}"} for i in range(billing.MAX_HEADER_FIELDS)]
        for hidden in ([], billing.clean_hidden(sorted(billing.HIDEABLE_KEYS))):
            for header_fields in ([], details):  # with many details the header wraps onto a second row
                pdf = invoice_pdf({**self.bill(), **base, "hidden": hidden, "header_fields": header_fields,
                                   "party_fields": [{"label": "State code", "value": "09"}]})
                self.assertTrue(pdf.startswith(b"%PDF"))


class Validation(unittest.TestCase):
    def test_a_bill_needs_a_line(self):
        with self.assertRaises(BillError):
            compute_bill([])
        with self.assertRaises(BillError):
            compute_bill([{"particulars": "", "qty": "", "rate": ""}])

    def test_a_line_needs_quantity_and_description(self):
        with self.assertRaises(BillError):
            compute_bill([{"particulars": "Guard", "qty": 0, "rate": 100}])
        with self.assertRaises(BillError):
            compute_bill([{"particulars": "", "qty": 2, "rate": 100}])
        with self.assertRaises(BillError):
            compute_bill([{"particulars": "Guard", "qty": "two", "rate": 100}])

    def test_percentages_stay_between_zero_and_one_hundred(self):
        with self.assertRaises(BillError):
            compute_bill([{"particulars": "Guard", "qty": 1, "rate": 1}], {"cgst_pct": 101})
        with self.assertRaises(BillError):
            compute_bill([{"particulars": "Guard", "qty": 1, "rate": 1}], {"epf_pct": -1})

    def test_blank_rows_are_ignored(self):
        bill = compute_bill(
            [{"particulars": "Guard", "qty": 2, "rate": 100}, {"particulars": "", "qty": "", "rate": ""}]
        )
        self.assertEqual(len(bill["lines"]), 1)

    def test_fractional_quantities_are_exact(self):
        bill = compute_bill([{"particulars": "Guard", "qty": "1.5", "rate": "100.10"}])
        self.assertEqual(bill["lines"][0]["amount"], D("150.15"))


class Numbering(unittest.TestCase):
    def test_financial_year_runs_april_to_march(self):
        self.assertEqual(fy_start_year(date(2026, 3, 31)), 2025)
        self.assertEqual(fy_start_year(date(2026, 4, 1)), 2026)
        self.assertEqual(fy_start_year(date(2027, 1, 15)), 2026)

    def test_number_format(self):
        self.assertEqual(fy_label(2026), "2026-27")
        self.assertEqual(fy_label(2099), "2099-00")
        self.assertEqual(bill_number(2026, 1), "2026-27/1")
        self.assertEqual(bill_number(2026, 202), "2026-27/202")


class EditDetection(unittest.TestCase):
    """An edit only makes a new version when something stored actually changes."""

    def setUp(self):
        # The stored row as psycopg2 returns it, and the same bill as _clean_bill prepares it.
        self.stored = {
            "bill_date": date(2026, 8, 5),
            "case_code": "CS-0001",
            "party_name": "Civil Surgeon, Bhind",
            "ref_no": None,
            "lines": [{"particulars": "Guard", "qty": 2.0, "rate": 100.0, "amount": 200.0}],
            "rates": {"cgst_pct": 9.0, "sgst_pct": 9.0},
            "grand_total": D("236.00"),
            "version_no": 3,
        }
        self.entered = {
            "bill_date": date(2026, 8, 5),
            "case_code": "CS-0001",
            "party_name": "Civil Surgeon, Bhind",
            "ref_no": None,
            "lines": '[{"particulars": "Guard", "qty": 2.0, "rate": 100.0, "amount": 200.0}]',
            "rates": '{"cgst_pct": 9.0, "sgst_pct": 9.0}',
            "grand_total": D("236"),
        }

    def test_saving_the_same_bill_is_not_a_change(self):
        self.assertFalse(_differs(self.stored, self.entered))

    def test_a_changed_line_is_a_change(self):
        self.entered["lines"] = '[{"particulars": "Guard", "qty": 3.0, "rate": 100.0, "amount": 300.0}]'
        self.assertTrue(_differs(self.stored, self.entered))

    def test_tagging_a_different_case_is_a_change(self):
        self.entered["case_code"] = "CS-0002"
        self.assertTrue(_differs(self.stored, self.entered))

    def test_filling_in_a_blank_field_is_a_change(self):
        self.entered["ref_no"] = "PO/77"
        self.assertTrue(_differs(self.stored, self.entered))


class PartPayments(unittest.TestCase):
    """A payment smaller than what is open splits the revenue entry in two."""

    def setUp(self):
        # Bill 2026-27/202: taxable 7,78,939.78, GST 1,40,209.16, grand total 9,19,149.
        self.open = {"taxable": D("778939.78"), "gst": D("140209.16"), "total": D("919149.00")}

    def test_the_two_parts_add_back_to_the_entry(self):
        received, remaining = split_payment(self.open, D("300000.00"))
        for key in ("taxable", "gst", "total"):
            self.assertEqual(received[key] + remaining[key], self.open[key])

    def test_the_received_part_is_the_money_that_came_in(self):
        received, remaining = split_payment(self.open, D("300000.00"))
        self.assertEqual(received["total"], D("300000.00"))
        self.assertEqual(remaining["total"], D("619149.00"))

    def test_taxable_and_gst_follow_the_same_share(self):
        received, _ = split_payment(self.open, D("459574.50"))  # exactly half
        self.assertEqual(received["taxable"], D("389469.89"))
        self.assertEqual(received["gst"], D("70104.58"))

    def test_a_bill_with_no_gst_splits_cleanly(self):
        received, remaining = split_payment({"taxable": D("50000"), "gst": D("0"), "total": D("50000")}, D("25000"))
        self.assertEqual(received, {"taxable": D("25000.00"), "gst": D("0.00"), "total": D("25000")})
        self.assertEqual(remaining["total"], D("25000"))


class LockedRevenueEntries(unittest.TestCase):
    """The generic Transaction form cannot change an entry that a bill owns."""

    def test_a_hand_entered_transaction_is_not_locked(self):
        self.assertIsNone(locked_reason("Transaction", {"bill_code": None, "transaction_status": "Committed"}))

    def test_a_bill_entry_is_locked_whatever_its_status(self):
        for state in ("Prospective", "Committed", "Cancelled"):
            self.assertTrue(locked_reason("Transaction", {"bill_code": "BILL-0001", "transaction_status": state}))

    def test_a_received_entry_says_an_admin_can_reverse_it(self):
        reason = locked_reason("Transaction", {"bill_code": "BILL-0001", "transaction_status": "Committed"})
        self.assertIn("admin", reason)

    def test_other_entities_are_never_locked(self):
        self.assertIsNone(locked_reason("Client", {"bill_code": "BILL-0001"}))


if __name__ == "__main__":
    unittest.main()
