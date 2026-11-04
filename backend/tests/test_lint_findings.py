"""Faults the linters found when they were first run on the code. Each is pinned here so it stays fixed."""

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import tally_ods  # noqa: E402
from app.ai import safety  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]


class TheCalculator(unittest.TestCase):
    """The pattern that strips thousands separators held a raw backspace character where \b was meant, so it never matched and
    "2,959,000 - 100" was refused."""

    def test_a_thousands_separator_is_read(self):
        self.assertEqual(safety.safe_calc("1,000+2"), 1002)
        self.assertEqual(safety.safe_calc("2,959,000 - 100"), 2958900)

    def test_an_argument_list_is_left_alone(self):
        self.assertEqual(safety.safe_calc("max(1, 2) + round(2.6)"), 5)
        self.assertEqual(safety.safe_calc("max(1,2)"), 2)

    def test_no_control_character_hides_in_a_pattern(self):
        for path in (ROOT / "backend" / "app" / "ai" / "safety.py", ROOT / "backend" / "tests" / "test_ai.py"):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("\x08", text, f"{path.name} holds a raw backspace character (it was meant to be a backslash and b)")


class ResettingTheTallyTables(unittest.TestCase):
    def test_when_the_owner_is_needed_and_there_is_none_the_database_is_heard(self):
        """It used to `raise` outside its handler, which Python answers with "No active exception to reraise" instead of what the
        database said."""
        refused = RuntimeError("permission denied for table voucher")
        with mock.patch.object(tally_ods, "_run_sql", side_effect=refused), mock.patch.object(tally_ods, "_superuser_settings", return_value=None):
            with self.assertRaises(RuntimeError) as caught:
                tally_ods.reset_tally_tables()
        self.assertIn("permission denied for table voucher", str(caught.exception))

    def test_any_other_failure_is_raised_as_it_is(self):
        with mock.patch.object(tally_ods, "_run_sql", side_effect=ValueError("syntax error")), mock.patch.object(tally_ods, "_superuser_settings", return_value={"x": 1}):
            with self.assertRaisesRegex(ValueError, "syntax error"):
                tally_ods.reset_tally_tables()

    def test_the_owner_is_tried_when_the_refusal_is_about_ownership(self):
        calls = []

        def run(sql, settings=None):
            calls.append(settings)
            if settings is None:
                raise RuntimeError("must be owner of table voucher")

        with mock.patch.object(tally_ods, "_run_sql", side_effect=run), mock.patch.object(tally_ods, "_superuser_settings", return_value={"user": "postgres"}):
            tally_ods.reset_tally_tables()
        self.assertEqual(calls, [None, {"user": "postgres"}])


class TheFrontendHooks(unittest.TestCase):
    """A hook after an early return runs a different number of times when the early return is taken, which React forbids."""

    def test_the_two_pages_that_did_it_declare_the_hook_first(self):
        for name, hook, early in (
            ("pages/dashboards/DashboardShell.tsx", "const exploreBase = useMemo", "if (!allowed) return <Navigate"),
            ("pages/OperationalDataPage.tsx", "const datasetGroups = useMemo", "if (loading) return null"),
        ):
            text = (ROOT / "frontend" / "src" / name).read_text(encoding="utf-8")
            self.assertLess(text.index(hook), text.index(early), name)


if __name__ == "__main__":
    unittest.main()
