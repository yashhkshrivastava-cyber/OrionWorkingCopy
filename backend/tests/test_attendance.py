"""Attendance: the arithmetic a register agrees on with the screen, what a line may hold, what posting enters and when it can be taken back, who may do what,
and how the pay it enters reaches the payroll, the payables and the warehouse. No database is needed."""

import inspect
import json
import sys
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app import attendance, auth, dw_sync, entities, payables, payroll  # noqa: E402
from app.attendance import AttendanceError  # noqa: E402
from app.entities import ATTENDANCE_MIGRATE, SQL_MIGRATIONS  # noqa: E402
from app.routers import attendance_router  # noqa: E402

D = Decimal


def line(**over):
    base = {"employee_code": "EMP-0001", "days_present": "20", "rate_per_day": "500"}
    return {**base, **over}


class TheArithmetic(unittest.TestCase):
    def test_the_figures_agree_with_the_ones_the_screen_is_checked_against(self):
        vectors = json.loads((ROOT / "backend" / "tests" / "attendance_vectors.json").read_text(encoding="utf-8"))
        self.assertGreater(len(vectors), 5)
        for v in vectors:
            def number(text, places):
                return D(text).quantize(D(places)) if text != "" else D(0)

            got = attendance.calculated_amount(number(v["rate"], "0.0001"), number(v["days"], "0.1"), number(v["extra"], "0.01"), number(v["deduction"], "0.01"))
            self.assertEqual(str(got), v["amount"], v)

    def test_a_monthly_salary_over_the_days_of_the_month_pays_the_salary_for_a_full_month(self):
        for month in ("2026-02", "2026-10", "2026-11"):
            rate = attendance.rate_from_salary(18500, month)
            self.assertEqual(attendance.calculated_amount(rate, D(attendance.days_in(month)), D(0), D(0)), D("18500.00"), month)
        self.assertEqual(attendance.rate_from_salary(None, "2026-10"), D(0))

    def test_months_and_the_day_the_pay_is_entered_on(self):
        self.assertEqual(attendance.days_in("2028-02"), 29)
        self.assertEqual(attendance.pay_date("2026-09", today=date(2026, 10, 23)), date(2026, 9, 30))
        self.assertEqual(attendance.pay_date("2026-10", today=date(2026, 10, 23)), date(2026, 10, 23))
        for bad in ("2026-13", "2026-1", "", None, "October"):
            with self.assertRaises(AttendanceError):
                attendance.month_of(bad)


class WhatALineMayHold(unittest.TestCase):
    def test_a_line_is_checked_and_its_amount_is_worked_out_unless_one_is_sent(self):
        got = attendance._clean_line(line(deduction_amount="200"), "2026-10")
        self.assertEqual((got["days_present"], got["rate_per_day"], got["amount"]), (D("20.0"), D("500.0000"), D("9800.00")))
        self.assertEqual(attendance._clean_line(line(amount="9000"), "2026-10")["amount"], D("9000.00"))

    def test_days_cannot_be_more_than_the_month_or_less_than_nothing_and_must_be_numbers(self):
        for bad in ("32", "-1", "abc", "nan", "inf"):
            with self.assertRaises(AttendanceError, msg=bad):
                attendance._clean_line(line(days_present=bad), "2026-10")
        with self.assertRaises(AttendanceError):
            attendance._clean_line(line(days_present="29"), "2026-02")
        self.assertEqual(attendance._clean_line(line(days_present="12.5"), "2026-10")["days_present"], D("12.5"))

    def test_money_cannot_be_negative_or_absurd(self):
        for key in ("rate_per_day", "extra_amount", "deduction_amount", "amount"):
            for bad in ("-5", "1e12", "ten"):
                with self.assertRaises(AttendanceError, msg=(key, bad)):
                    attendance._clean_line(line(**{key: bad}), "2026-10")

    def test_a_line_is_exactly_one_person(self):
        with self.assertRaises(AttendanceError):
            attendance._clean_line({"days_present": "1"}, "2026-10")
        with self.assertRaises(AttendanceError):
            attendance._clean_line(line(worker_code="WRK-0001"), "2026-10")
        made = attendance._clean_line({"new_worker": {"name": "  Sunil   Patel ", "phone": "98765 43210"}, "days_present": "3", "rate_per_day": "450"}, "2026-10")
        self.assertEqual((made["new_worker"]["worker_name"], made["new_worker"]["phone"]), ("Sunil Patel", "98765 43210"))
        with self.assertRaises(AttendanceError):
            attendance._clean_line({"new_worker": {"name": ""}, "days_present": "3"}, "2026-10")
        with self.assertRaises(AttendanceError):
            attendance._clean_line({"new_worker": {"name": "Sunil", "phone": "12"}, "days_present": "3"}, "2026-10")

    def test_the_same_person_cannot_be_on_a_register_twice_and_the_size_is_limited(self):
        with self.assertRaises(AttendanceError) as caught:
            attendance._clean_lines([line(), line(days_present="3")], "2026-10")
        self.assertIn("Line 2", str(caught.exception))
        with self.assertRaises(AttendanceError):
            attendance._clean_lines([line(employee_code=f"EMP-{i}") for i in range(attendance.MAX_LINES + 1)], "2026-10")
        with self.assertRaises(AttendanceError):
            attendance._clean_lines("everyone", "2026-10")


class PostingAndTakingItBack(unittest.TestCase):
    def test_posting_needs_the_confirmation_and_what_the_person_saw(self):
        with self.assertRaises(AttendanceError):
            attendance.post_sheet(1, "ATT-0001")
        with self.assertRaises(AttendanceError):
            attendance.post_sheet(1, "ATT-0001", confirm=True)
        with self.assertRaises(AttendanceError):
            attendance.post_sheet(1, "ATT-0001", confirm=True, seen_count="x", seen_total="1")

    def test_reopening_needs_the_confirmation_and_a_reason(self):
        with self.assertRaises(AttendanceError):
            attendance.reopen_sheet(1, "ATT-0001", reason="because it is wrong")
        with self.assertRaises(AttendanceError):
            attendance.reopen_sheet(1, "ATT-0001", confirm=True, reason="no")

    def test_posting_enters_salary_for_employees_and_an_expense_for_everyone_else_and_leaves_paying_to_the_bank(self):
        source = inspect.getsource(attendance.post_sheet)
        self.assertIn('"orion_ods.employee_transaction"', source)
        self.assertIn('"orion_ods.expense_transaction"', source)
        self.assertIn('"No"', source)  # a salary line starts unpaid
        self.assertIn('"Committed"', source)  # an expense is incurred, not paid
        self.assertNotIn("salary_run", source)
        self.assertNotIn("expense_payment", source)
        self.assertIn("attendance_line_id", source)  # each entry names the register line it came from

    def test_a_register_with_other_people_needs_an_expense_type_and_a_future_month_cannot_be_posted(self):
        source = inspect.getsource(attendance.post_sheet)
        self.assertIn("expense_type_code", source)
        self.assertIn("has not started", source)
        self.assertIn("seen_n", source)

    def test_a_register_cannot_be_reopened_once_any_of_it_has_been_paid(self):
        source = inspect.getsource(attendance.reopen_sheet)
        self.assertIn("salary_run_id IS NOT NULL", source)
        self.assertIn("expense_payment", source)  # any payment ever recorded, even a reversed one
        self.assertIn("record_deleted", source)  # what is taken back is written down

    def test_every_step_is_written_to_the_event_log(self):
        self.assertIn('"posted"', inspect.getsource(attendance.post_sheet))
        self.assertIn('"reopened"', inspect.getsource(attendance.reopen_sheet))
        self.assertIn("action", inspect.getsource(attendance.save_sheet))


class WhatTheOthersSee(unittest.TestCase):
    def test_a_line_entered_by_a_register_is_locked_in_the_generic_forms(self):
        for name in ("Employee Transaction", "Expense Transaction"):
            self.assertIn("attendance register", entities.locked_reason(name, {"attendance_line_id": 7}))
            self.assertIsNone(entities.locked_reason(name, {"attendance_line_id": None}))

    def test_payroll_lists_the_case_a_salary_was_worked_at_and_each_case_with_unpaid_pay(self):
        source = inspect.getsource(payroll.unpaid_lines)
        self.assertIn("COALESCE(t.case_code, e.employee_case_code)", source)
        self.assertIn('"cases"', source)

    def test_payables_can_be_filtered_by_case_and_lists_the_cases_owed_on(self):
        self.assertIn("case_code", inspect.signature(payables.list_payables).parameters)
        self.assertIn('"cases"', inspect.getsource(payables.list_payables))

    def test_the_warehouse_puts_a_salary_line_at_the_case_it_was_worked_at(self):
        spec = dw_sync.FACTS["Employee Transaction"]
        self.assertIn("case_code", spec["ods_cols"])
        self.assertIn("case_code", spec["dw_cols"])
        calls = []

        class Pit:
            employee = mock.Mock(at=lambda code, when: {"employee_sk": 1, "manager_code": None, "employee_case_code": "CS-HOME"})

            @staticmethod
            def case_keys(code, when):
                calls.append(code)
                return {}

        dw_sync._pit_employee_txn(Pit, {"employee_code": "EMP-1", "case_code": "CS-WORK", "transaction_date": date(2026, 10, 5)}, dw_sync.datetime.now())
        dw_sync._pit_employee_txn(Pit, {"employee_code": "EMP-1", "case_code": None, "transaction_date": date(2026, 10, 5)}, dw_sync.datetime.now())
        self.assertEqual(calls, ["CS-WORK", "CS-HOME"])

    def test_the_warehouse_schema_has_the_column(self):
        sql = (ROOT / ".cursor" / "db" / "dw_schema.sql").read_text(encoding="utf-8")
        self.assertIn("ALTER TABLE orion_dw.fact_employee_transaction ADD COLUMN IF NOT EXISTS case_code TEXT", sql)


class WhoMayDoWhat(unittest.TestCase):
    def test_every_route_needs_a_permission_and_changes_need_the_write_one(self):
        for route in attendance_router.router.routes:
            names = {dep.call.__name__ for dep in route.dependant.dependencies}
            self.assertTrue(names & {"require_attendance", "require_attendance_write"}, route.path)
            if route.methods & {"POST", "PUT", "DELETE"} or route.path.endswith("/parse"):
                self.assertIn("require_attendance_write", names, f"{sorted(route.methods)} {route.path}")

    def test_the_access_pair_is_defined_for_every_role_and_a_write_includes_a_view(self):
        for role in ("admin", "editor", "viewer"):
            self.assertIn("attendance_access", auth.ROLE_DEFAULT_DATA_ACCESS[role])
            self.assertIn("attendance_write", auth.ROLE_DEFAULT_DATA_ACCESS[role])
        self.assertFalse(auth.ROLE_DEFAULT_DATA_ACCESS["viewer"]["attendance_access"])
        self.assertTrue(auth.ROLE_DEFAULT_DATA_ACCESS["editor"]["attendance_write"])
        self.assertIn(("attendance_write", "attendance_access"), auth.WRITE_IMPLIES_ACCESS)
        self.assertTrue(auth.can_access_page({"role": "viewer", "attendance_access": True}, "attendance"))
        self.assertFalse(auth.can_access_page({"role": "admin", "attendance_access": False, "attendance_write": False}, "attendance"))
        self.assertTrue(auth.can_write_attendance({"attendance_write": True}))
        self.assertFalse(auth.can_write_attendance({"attendance_write": False, "role": "admin"}))

    def test_posting_takes_an_idempotency_key(self):
        self.assertIn("_once(", inspect.getsource(attendance_router.post_sheet))

    def test_the_schema_is_applied_with_the_others_and_holds_what_the_code_relies_on(self):
        self.assertIn(ATTENDANCE_MIGRATE, SQL_MIGRATIONS)
        sql = ATTENDANCE_MIGRATE.read_text(encoding="utf-8")
        for needed in (
            "attendance_sheet", "attendance_line", "attendance_worker", "attendance_event", "UNIQUE (case_code, month_year)", "attendance_line_one_person",
            "employee_transaction ADD COLUMN IF NOT EXISTS case_code", "employee_transaction ADD COLUMN IF NOT EXISTS attendance_line_id",
            "expense_transaction ADD COLUMN IF NOT EXISTS attendance_line_id", "attendance_access",
        ):
            self.assertIn(needed, sql)


class Workbooks(unittest.TestCase):
    def test_a_workbook_that_is_not_one_is_refused_with_a_reason(self):
        for content in (b"", b"not a workbook"):
            with self.assertRaises(AttendanceError):
                attendance.parse_upload("CS-1", "2026-10", content)

    def test_the_template_and_the_upload_use_the_same_headings(self):
        self.assertEqual(attendance.COLUMNS[0], "Employee Code")
        self.assertIn("Days Present", attendance.COLUMNS)
        self.assertEqual(attendance._key("Days Present"), "dayspresent")
        self.assertEqual(attendance._key(" Rate per Day "), "rateperday")


if __name__ == "__main__":
    unittest.main()
