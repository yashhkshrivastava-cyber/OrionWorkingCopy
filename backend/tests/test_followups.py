"""The notifications to create a case and record an EMD once an opportunity is won: what is shown, when one goes away, who may act on it,
and that every way of saving things asks for them to be brought up to date. No database is needed."""

import inspect
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app import entity_service, opportunity_followups as followups  # noqa: E402
from app.entities import FOLLOWUPS_MIGRATE, SQL_MIGRATIONS  # noqa: E402
from app.routers import entities_router, followups_router  # noqa: E402


def item(**over):
    base = {
        "id": 7, "kind": "case", "status": "open", "opportunity_code": "OPP-0007", "opportunity_name": "Gate guards", "tender_id": "T-1",
        "won_on": "2026-10-01", "state": "Madhya Pradesh", "city": "Bhopal", "has_case": False,
    }
    return {**base, **over}


class WhatIsShown(unittest.TestCase):
    def test_the_case_follow_up_opens_the_case_form_for_that_opportunity(self):
        shown = followups._shape(item())
        self.assertEqual(shown["title"], "Create the case for Gate guards")
        self.assertEqual(shown["action"]["label"], "Create case")
        self.assertEqual(shown["action"]["path"], "/data/operational?intent=change&entity=Case&mode=create&opportunity=OPP-0007")
        self.assertEqual(shown["place"], "Bhopal, Madhya Pradesh")
        self.assertFalse(shown["waiting_for_case"])

    def test_the_emd_follow_up_opens_the_emd_form_and_says_when_the_case_has_to_come_first(self):
        waiting = followups._shape(item(kind="emd"))
        self.assertEqual(waiting["action"]["path"], "/data/operational?intent=change&entity=EMD&mode=create&opportunity=OPP-0007")
        self.assertTrue(waiting["waiting_for_case"])
        self.assertIn("Create its case first", waiting["message"])
        ready = followups._shape(item(kind="emd", has_case=True))
        self.assertFalse(ready["waiting_for_case"])
        self.assertNotIn("case first", ready["message"])

    def test_an_opportunity_with_no_name_is_called_by_its_code(self):
        self.assertIn("OPP-0007", followups._shape(item(opportunity_name=None))["title"])

    def test_the_page_reads_the_same_address_the_notification_makes(self):
        page = (ROOT / "frontend" / "src" / "pages" / "OperationalDataPage.tsx").read_text(encoding="utf-8")
        for name in ("'entity'", "'opportunity'", "'mode'", "'create'"):
            self.assertIn(name, page)


class WhenOneGoesAway(unittest.TestCase):
    sql = inspect.getsource(followups.sync)

    def test_a_follow_up_is_settled_by_the_records_not_by_a_click(self):
        # The case counts when it names the opportunity or the opportunity names it; the EMD counts when it names the opportunity or is on its case.
        self.assertIn("c.opportunity_code = o.opportunity_code", followups.CASE_EXISTS)
        self.assertIn("o.opportunity_case_code IS NOT NULL", followups.CASE_EXISTS)
        self.assertIn("e.opportunity_code = o.opportunity_code", followups.EMD_EXISTS)
        self.assertIn("e.case_code = o.opportunity_case_code", followups.EMD_EXISTS)
        self.assertIn("c.opportunity_code = o.opportunity_code", followups.EMD_EXISTS)

    def test_only_a_person_dismisses_one_and_the_system_never_does(self):
        self.assertNotIn("'dismissed'", self.sql)
        self.assertIn("'dismissed'", inspect.getsource(followups.dismiss))

    def test_a_win_is_only_ever_added_once_and_a_look_does_not_use_up_numbers(self):
        self.assertIn("NOT EXISTS", self.sql)
        self.assertIn("ON CONFLICT (opportunity_code, kind) DO NOTHING", self.sql)

    def test_what_is_dismissed_stays_dismissed_and_a_withdrawn_one_returns_with_the_win(self):
        reopen = self.sql[self.sql.index("Won again after being withdrawn"):self.sql.index("Settled:")]
        self.assertIn("f.status IN ('withdrawn', 'done')", reopen)
        self.assertNotIn("dismissed", reopen)
        withdraw = self.sql[self.sql.index("No longer won"):]
        self.assertIn("f.status = 'open' AND NOT", withdraw)

    def test_every_change_is_written_to_the_event_log(self):
        for action in ("created", "reopened", "done", "withdrawn"):
            self.assertIn(f'"{action}"', self.sql)
        for function in (followups.dismiss, followups.reopen):
            self.assertIn("_event(", inspect.getsource(function))

    def test_a_reason_is_tidied_and_limited(self):
        self.assertEqual(followups._clean_note("  Exempt   as an MSME "), "Exempt as an MSME")
        self.assertIsNone(followups._clean_note("   "))
        self.assertIsNone(followups._clean_note(None))
        with self.assertRaises(followups.FollowupError):
            followups._clean_note("x" * (followups.NOTE_LIMIT + 1))

    def test_a_case_made_for_an_opportunity_becomes_the_case_the_opportunity_became(self):
        self.assertIn("SET opportunity_case_code", self.sql)
        self.assertIn("o.opportunity_case_code IS NULL", self.sql)


class WhoAndWhen(unittest.TestCase):
    def test_every_route_needs_permission_to_change_operational_data(self):
        for route in followups_router.router.routes:
            names = {dep.call.__name__ for dep in route.dependant.dependencies}
            self.assertIn("require_ods_write", names, route.path)

    def test_the_schema_is_applied_with_the_others_and_the_first_run_settles_what_was_won_before(self):
        self.assertIn(FOLLOWUPS_MIGRATE, SQL_MIGRATIONS)
        sql = FOLLOWUPS_MIGRATE.read_text(encoding="utf-8")
        self.assertIn("IF to_regclass('orion_ods.opportunity_followup') IS NULL", sql)  # once: a restart never settles a win nobody has seen
        self.assertIn("'Won before follow-ups were introduced'", sql)
        for needed in ("UNIQUE (opportunity_code, kind)", "'open', 'done', 'dismissed', 'withdrawn'", "opportunity_followup_event", "ON DELETE CASCADE"):
            self.assertIn(needed, sql)

    def test_a_save_of_an_opportunity_a_case_or_an_emd_brings_the_follow_ups_up_to_date(self):
        for name in ("Opportunity", "Case", "EMD"):
            with mock.patch.object(followups, "sync_quietly") as sync:
                followups.entity_saved(name, "X-1")
            sync.assert_called_once_with()
        with mock.patch.object(followups, "sync_quietly") as sync:
            followups.entity_saved("Client", "CL-1")
        sync.assert_not_called()

    def test_every_way_of_saving_asks_for_it(self):
        for function in (entity_service.create, entity_service.change, entity_service.remove):
            self.assertIn("opportunity_followups.entity_saved(", inspect.getsource(function), function.__name__)
        self.assertIn("opportunity_followups.sync_quietly()", inspect.getsource(entities_router.upload_excel))

    def test_a_failure_while_updating_never_reaches_the_person_who_saved(self):
        with mock.patch.object(followups, "sync", side_effect=RuntimeError("database is down")), self.assertLogs(followups.logger, "ERROR"):
            followups.sync_quietly()


if __name__ == "__main__":
    unittest.main()
