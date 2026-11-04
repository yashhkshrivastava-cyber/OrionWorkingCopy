"""Bad numbers, dropdown values, totals and Excel merges: what the forms and the upload accept, refuse and never guess.

Found by an end-to-end data test (NaN stored in money columns, uploads that overwrote other records, totals left empty,
HTTP 500 on odd input). No database is needed.
"""

import sys
import unittest
from decimal import Decimal
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import db_utils, dw_sync  # noqa: E402
from app.entities import ENTITIES, MERGE_KEYS, merge_columns, merge_fallback  # noqa: E402
from app.excel_import import parse_workbook  # noqa: E402
from app.payload import PayloadError, apply_computed_fields, clean_payload, coerce_input  # noqa: E402
from app.xlsx_io import write_xlsx  # noqa: E402

REVENUE = ENTITIES["Transaction"]
EXPENSE = ENTITIES["Expense Transaction"]
CAR_TRIP = ENTITIES["Car Transaction"]
CASE = ENTITIES["Case"]
CLIENT = ENTITIES["Client"]


def revenue(**kw):
    return clean_payload(REVENUE, {"case_code": "CS-1", "transaction_status": "Committed", **kw})


class NumbersMustBeFinite(unittest.TestCase):
    def test_nan_and_infinity_are_refused_in_every_number_field(self):
        fields = [(name, key) for name, ent in ENTITIES.items() for key, cfg in ent["form_fields"].items()
                  if cfg["type"] in ("number", "integer") and not cfg.get("compute_from") and not cfg.get("readonly")]
        self.assertGreater(len(fields), 10)
        for name, key in fields:
            for bad in ("nan", "NaN", "inf", "-inf", "Infinity", "1e999", float("nan"), float("inf")):
                with self.assertRaises(PayloadError, msg=f"{name}.{key}={bad!r}") as caught:
                    clean_payload(ENTITIES[name], {key: bad}, for_update=True)  # an update only looks at what is sent
                self.assertIn("invalid", str(caught.exception).lower())

    def test_ordinary_numbers_still_pass(self):
        self.assertEqual(coerce_input("1,234.50", "number"), 1234.5)
        self.assertEqual(coerce_input(0, "number"), 0)
        self.assertEqual(coerce_input("-5", "number"), -5)
        self.assertEqual(coerce_input("1e3", "number"), 1000)

    def test_an_integer_must_fit_the_database_column(self):
        for bad in ("inf", "-inf", "1e30", 2**31, -(2**31) - 1, 2**40):
            with self.assertRaises((ValueError, OverflowError), msg=repr(bad)):
                coerce_input(bad, "integer")
        self.assertEqual(coerce_input(2**31 - 1, "integer"), 2**31 - 1)
        self.assertEqual(coerce_input("1500", "integer"), 1500)

    def test_a_nul_character_is_refused_with_a_message_not_a_crash(self):
        with self.assertRaises(PayloadError) as caught:
            clean_payload(ENTITIES["Employee"], {"employee_name": "a\x00b"})
        self.assertIn("Employee Name", str(caught.exception))

    def test_a_nan_already_stored_does_not_break_the_screens_or_the_warehouse(self):
        from app.routers.entities_router import _serialize_value

        for stored in (Decimal("NaN"), Decimal("Infinity"), float("nan")):
            self.assertIsNone(_serialize_value(stored))
        self.assertEqual(_serialize_value(Decimal("12.50")), 12.5)
        # the loader compares values with ==, and NaN != NaN would give the row a new version on every load
        self.assertEqual(dw_sync._norm(Decimal("NaN")), dw_sync._norm(Decimal("NaN")))
        self.assertTrue(dw_sync._changed({"a": Decimal("NaN")}, {"a": float("nan")}, ["a"]) is False)
        self.assertTrue(dw_sync._changed({"a": Decimal("1")}, {"a": Decimal("2")}, ["a"]))

    def test_an_exported_nan_is_blank_not_a_corrupt_file(self):
        from app.excel_import import _export_cell

        self.assertIsNone(_export_cell(Decimal("NaN")))
        self.assertIsNone(_export_cell(float("inf")))
        self.assertEqual(_export_cell(Decimal("3.5")), 3.5)


class DropdownsMustBeOptions(unittest.TestCase):
    def test_a_value_outside_the_options_is_a_message(self):
        for name, key in (("Client", "client_status"), ("Case", "case_status"), ("Employee", "employee_status"),
                          ("Transaction", "transaction_status"), ("Expense Transaction", "is_regular_expense"),
                          ("Client", "client_type"), ("Client", "firm_priority"), ("Employee", "employee_type")):
            with self.assertRaises(PayloadError, msg=f"{name}.{key}") as caught:
                clean_payload(ENTITIES[name], {key: "Banana"}, for_update=True)
            self.assertIn("must be one of", str(caught.exception))

    def test_the_options_own_spelling_is_stored_whatever_case_was_typed(self):
        self.assertEqual(clean_payload(CLIENT, {"client_status": "active"}, for_update=True), {"client_status": "Active"})
        self.assertEqual(clean_payload(EXPENSE, {"is_regular_expense": "YES"}, for_update=True), {"is_regular_expense": "Yes"})
        self.assertEqual(clean_payload(ENTITIES["Employee"], {"employee_type": " full-time "}, for_update=True), {"employee_type": "Full-time"})

    def test_blank_stays_blank_and_a_free_choice_stays_free(self):
        self.assertEqual(clean_payload(CLIENT, {"client_status": ""}, for_update=True), {"client_status": None})
        free = clean_payload(ENTITIES["Opportunity"], {"opportunity_type": "Regional"}, for_update=True)  # select_or_custom
        self.assertEqual(free, {"opportunity_type": "Regional"})


class TotalsAreAlwaysWorkedOut(unittest.TestCase):
    def test_a_blank_tax_and_gst_is_nothing_not_a_reason_to_leave_the_total_empty(self):
        self.assertEqual(revenue(transaction_amount=250000.5)["amount_after_tax_gst"], 250000.5)
        self.assertEqual(revenue(transaction_amount=1000, gst=180)["amount_after_tax_gst"], 1180)
        self.assertEqual(revenue(transaction_amount=1000, tax=10, gst=180)["amount_after_tax_gst"], 1190)

    def test_a_row_with_no_amount_has_no_total(self):
        self.assertNotIn("amount_after_tax_gst", revenue(tax=10, gst=180))

    def test_the_same_for_expenses(self):
        self.assertEqual(clean_payload(EXPENSE, {"case_code": "CS-1", "expense_type_code": "EXP-1", "transaction_amount": 500})["amount_after_tax_gst"], 500)

    def test_a_total_that_does_not_add_up_is_refused_but_rounding_is_allowed(self):
        with self.assertRaises(PayloadError) as caught:
            revenue(transaction_amount=100, tax=0, gst=18, amount_after_tax_gst=5)
        self.assertIn("must equal", str(caught.exception))
        self.assertEqual(revenue(transaction_amount=100.2, tax=0, gst=18, amount_after_tax_gst=118)["amount_after_tax_gst"], 118)  # a bill's round-off
        self.assertEqual(revenue(transaction_amount=100, tax=0, gst=18, amount_after_tax_gst=118)["amount_after_tax_gst"], 118)

    def test_changing_only_the_amount_works_out_the_total_from_what_is_stored(self):
        stored = {"transaction_amount": Decimal("450000"), "tax": Decimal("0"), "gst": Decimal("81000"), "amount_after_tax_gst": Decimal("531000")}
        cleaned = clean_payload(REVENUE, {"transaction_amount": 500000}, for_update=True, existing=stored)
        self.assertEqual(cleaned["amount_after_tax_gst"], 581000)

    def test_an_update_that_touches_nothing_in_the_total_leaves_it_alone(self):
        stored = {"transaction_amount": Decimal("100"), "tax": None, "gst": Decimal("18"), "amount_after_tax_gst": Decimal("120")}  # legacy, off by 2
        self.assertEqual(clean_payload(REVENUE, {"transaction_description": "note"}, for_update=True, existing=stored), {"transaction_description": "note"})

    def test_a_stored_total_sent_back_unchanged_is_not_rejected(self):
        stored = {"transaction_amount": Decimal("100"), "tax": Decimal("0"), "gst": Decimal("18"), "amount_after_tax_gst": Decimal("125")}  # legacy
        cleaned = clean_payload(REVENUE, {"transaction_amount": 100, "tax": 0, "gst": 18, "amount_after_tax_gst": 125}, for_update=True, existing=stored)
        self.assertEqual(cleaned["amount_after_tax_gst"], 125)

    def test_kilometres_follow_the_readings_even_when_only_one_is_sent(self):
        stored = {"initial_reading": Decimal("1000"), "final_reading": Decimal("1100"), "driven_km": Decimal("100")}
        self.assertEqual(clean_payload(CAR_TRIP, {"final_reading": 1250}, for_update=True, existing=stored)["driven_km"], 250)
        self.assertEqual(clean_payload(CAR_TRIP, {"initial_reading": 100, "final_reading": 200})["driven_km"], 100)

    def test_month_year_follows_the_date(self):
        from datetime import date

        stored = {"transaction_date": date(2025, 1, 31), "month_year": "2025-01"}
        self.assertEqual(clean_payload(ENTITIES["Employee Transaction"], {"transaction_date": "2025-03-31"}, for_update=True, existing=stored)["month_year"], "2025-03")


class FakeCursor:
    """Answers the few queries upsert_many makes, from a table held in memory."""

    def __init__(self, rows, pk, kinds):
        self.rows, self.pk, self.kinds = rows, pk, kinds
        self.sql: list[tuple[str, list]] = []
        self.description = None
        self._result: list[tuple] = []

    def execute(self, sql, params=None):
        params = list(params or [])
        self.sql.append((sql, params))
        text = " ".join(sql.split())
        if "information_schema.columns" in text:
            self._result = list(self.kinds.items())
        elif text.startswith(f"SELECT {self.pk} FROM"):
            col = text.split(" WHERE ")[1].split(" ")[0].replace("lower(btrim(", "").split("::")[0].split(")")[0].strip()
            want = str(params[0]).strip().lower()
            self._result = [(r[self.pk],) for r in sorted(self.rows, key=lambda r: r[self.pk]) if str(r.get(col)).strip().lower() == want]
        elif text.startswith("SELECT * FROM"):
            row = next(r for r in self.rows if r[self.pk] == params[0])
            self.description = [(c,) for c in row]
            self._result = [tuple(row.values())]
        else:
            self._result = []

    def fetchall(self):
        return self._result

    def fetchone(self):
        return self._result[0] if self._result else None


class FakeDb:
    def __init__(self, rows, pk="employee_code", kinds=None):
        self.cursor = FakeCursor(rows, pk, kinds or {"employee_code": "text", "employee_name": "text", "employee_designation": "text", "monthly_salary": "numeric"})

    def __call__(self, commit=False):
        outer = self

        class Ctx:
            def __enter__(self):
                return outer.cursor

            def __exit__(self, *a):
                return False

        return Ctx()


PEOPLE = [{"employee_code": "EMP-1", "employee_name": "Asha", "employee_designation": "Guard"},
          {"employee_code": "EMP-2", "employee_name": "Twin", "employee_designation": "Guard"},
          {"employee_code": "EMP-3", "employee_name": "twin", "employee_designation": "Guard"}]


def merge(rows, **kw):
    db = FakeDb([dict(p) for p in PEOPLE])
    with mock.patch.object(db_utils, "db_cursor", db):
        result = db_utils.upsert_many("orion_ods.employee", rows, ["employee_name"], "employee_code", user_id=7, **kw)
    return result, db.cursor.sql


def writes(sql):
    return [s for s, _p in sql if s.lstrip().startswith(("INSERT", "UPDATE"))]


class MergesNeverGuess(unittest.TestCase):
    def test_a_key_that_matches_two_records_is_refused_and_names_them(self):
        with self.assertRaises(db_utils.MergeError) as caught:
            merge([{"employee_name": "Twin", "employee_designation": "Boss", "__row": 5}])
        text = str(caught.exception)
        self.assertEqual(caught.exception.row, 5)
        self.assertIn("EMP-2", text)
        self.assertIn("EMP-3", text)
        self.assertIn("employee_code", text)  # and says how to be specific

    def test_one_match_updates_only_that_record_and_leaves_the_key_alone(self):
        (inserted, updated), sql = merge([{"employee_name": "asha", "employee_designation": "Boss", "__row": 2}])
        self.assertEqual((inserted, updated), (0, 1))
        update = [(s, p) for s, p in sql if s.lstrip().startswith("UPDATE")][0]
        self.assertIn("employee_designation = %s", update[0])
        self.assertNotIn("employee_name = %s", update[0])
        self.assertEqual(update[1][-1], "EMP-1")

    def test_no_match_inserts(self):
        (inserted, updated), sql = merge([{"employee_name": "Newcomer", "__row": 2}])
        self.assertEqual((inserted, updated), (1, 0))
        self.assertTrue(any(s.lstrip().startswith("INSERT") for s, _p in sql))

    def test_a_row_that_names_its_record_updates_that_one_even_when_the_name_is_shared(self):
        (inserted, updated), sql = merge([{"employee_name": "Twin (night)", "employee_designation": "Boss", "__code": "EMP-3", "__row": 2}])
        self.assertEqual((inserted, updated), (0, 1))
        update = [(s, p) for s, p in sql if s.lstrip().startswith("UPDATE")][0]
        self.assertEqual(update[1][-1], "EMP-3")
        self.assertIn("employee_name = %s", update[0])  # a row that names its record may rename it

    def test_a_code_that_does_not_exist_is_an_error_not_an_insert(self):
        with self.assertRaises(db_utils.MergeError) as caught:
            merge([{"employee_name": "X", "__code": "EMP-99", "__row": 9}])
        self.assertEqual(caught.exception.row, 9)
        self.assertIn("EMP-99", str(caught.exception))

    def test_the_row_numbers_and_codes_never_reach_the_database(self):
        _result, sql = merge([{"employee_name": "Newcomer", "__row": 2}, {"employee_name": "Asha", "employee_designation": "X", "__row": 3, "__code": "EMP-1"}])
        for text, _params in sql:
            self.assertNotIn("__row", text)
            self.assertNotIn("__code", text)

    def test_a_blank_key_falls_back_to_another_column(self):
        rows = [{"employee_code": "EMP-1", "employee_name": "Asha", "employee_designation": "Guard"}]
        db = FakeDb(rows, kinds={"employee_code": "text", "employee_name": "text", "employee_designation": "text"})
        with mock.patch.object(db_utils, "db_cursor", db):
            result = db_utils.upsert_many("orion_ods.employee", [{"employee_name": "Asha", "employee_designation": "Boss", "__row": 2}], ["employee_designation_missing"],
                                          "employee_code", user_id=1, fallback_cols=["employee_name"])
        self.assertEqual(result, (0, 1))

    def test_a_blank_key_with_no_fallback_inserts(self):
        (inserted, updated), _sql = merge([{"employee_designation": "Guard", "__row": 2}])
        self.assertEqual((inserted, updated), (1, 0))

    def test_numbers_and_dates_are_compared_as_numbers_and_dates(self):
        self.assertIn("::numeric", db_utils._same("amount", "numeric"))
        self.assertIn("::date", db_utils._same("day", "date"))
        self.assertIn("lower(btrim(", db_utils._same("name", "text"))
        self.assertNotIn("::text", db_utils._same("amount", "numeric").replace("::numeric", ""))

    def test_the_helper_still_takes_the_user(self):
        import inspect

        self.assertIn("user_id", inspect.signature(db_utils.upsert_many).parameters)

    def test_finalize_can_adjust_what_an_update_writes(self):
        seen = {}

        def finalize(stored, changes):
            seen["stored"] = stored["employee_name"]
            return {**changes, "employee_designation": "Adjusted"}

        _result, sql = merge([{"employee_name": "Asha", "employee_designation": "Boss", "__row": 2}], finalize=finalize)
        self.assertEqual(seen["stored"], "Asha")
        self.assertIn("Adjusted", [p for s, params in sql if s.lstrip().startswith("UPDATE") for p in params])


class TheMergeKeysTellRecordsApart(unittest.TestCase):
    def test_an_expense_is_told_apart_by_its_amount_and_a_car_trip_by_its_reading(self):
        self.assertIn("transaction_amount", merge_columns("Expense Transaction"))
        self.assertIn("initial_reading", merge_columns("Car Transaction"))

    def test_every_merge_key_and_fallback_is_a_column_of_the_form(self):
        for name, keys in MERGE_KEYS.items():
            for key in keys:
                self.assertIn(key, ENTITIES[name]["form_fields"], f"{name}.{key}")
        for name in ("Opportunity",):
            for key in merge_fallback(name):
                self.assertIn(key, ENTITIES[name]["form_fields"])
        self.assertEqual(merge_fallback("Opportunity"), ["opportunity_name"])
        self.assertEqual(merge_fallback("Client"), [])


def workbook(entity_name, header, rows):
    return write_xlsx({"Records": [header, *rows]})


class TheFileCanNameRecordsAndSaysWhichRows(unittest.TestCase):
    def parse(self, header, rows):
        return parse_workbook(ENTITIES["Employee"], workbook("Employee", header, rows), entity_name="Employee")

    def test_a_code_column_is_recognised_under_the_usual_spellings(self):
        for header in ("employee_code", "Employee Code", "employeeCode", "EMPLOYEE CODE"):
            rows, errors = self.parse(["employee_name", header], [["Asha", "EMP-0001"]])
            self.assertEqual(errors, [], header)
            self.assertEqual(rows[0]["__code"], "EMP-0001", header)

    def test_every_row_carries_its_row_number_in_the_sheet(self):
        rows, errors = self.parse(["employee_name"], [["A"], ["B"], [None], ["C"]])
        self.assertEqual([r["__row"] for r in rows], [2, 3, 5])

    def test_the_same_name_on_two_rows_says_which_rows(self):
        _rows, errors = self.parse(["employee_name"], [["Asha"], ["Ravi"], [" asha "]])
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0]["row"], 4)
        self.assertIn("Rows 2 and 4", errors[0]["message"])

    def test_rows_that_name_different_records_may_share_a_name(self):
        rows, errors = self.parse(["employee_name", "employee_code"], [["Twin", "EMP-2"], ["Twin", "EMP-3"]])
        self.assertEqual(errors, [])
        self.assertEqual([r["__code"] for r in rows], ["EMP-2", "EMP-3"])

    def test_the_same_code_twice_is_an_error(self):
        _rows, errors = self.parse(["employee_name", "employee_code"], [["A", "EMP-2"], ["B", "emp-2"]])
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0]["row"], 3)

    def test_a_code_with_nothing_to_change_is_reported(self):
        _rows, errors = self.parse(["employee_name", "employee_code"], [[None, "EMP-2"]])
        self.assertEqual(errors[0]["row"], 2)

    def test_the_template_tells_people_about_the_code_column(self):
        from app.excel_import import build_template
        import io
        import zipfile

        data = build_template("Employee", ENTITIES["Employee"])
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            text = " ".join(z.read(n).decode("utf-8", "ignore") for n in z.namelist() if "sharedStrings" in n or "sheet2" in n)
        self.assertIn("employee_code", text)
        self.assertIn("more than one existing record", text)


class UploadedTotalsFollowTheStoredRecord(unittest.TestCase):
    """A blank tax cell keeps the stored tax, so the total has to be worked out from the stored tax too."""

    def finalize(self):
        # the closure lives in the route; exercise the same logic through apply_computed_fields
        stored = {"transaction_amount": Decimal("1000"), "tax": Decimal("0"), "gst": Decimal("180"), "amount_after_tax_gst": Decimal("1180")}
        changes = {"transaction_amount": 2000.0, "amount_after_tax_gst": 2000.0}   # the row had only an amount, so its total was just 2000
        fields = REVENUE["form_fields"]
        merged = apply_computed_fields(fields, {"transaction_amount": changes["transaction_amount"]}, stored)
        return merged

    def test_the_total_of_an_updated_row_uses_the_stored_gst(self):
        self.assertEqual(self.finalize()["amount_after_tax_gst"], 2180)


if __name__ == "__main__":
    unittest.main()
