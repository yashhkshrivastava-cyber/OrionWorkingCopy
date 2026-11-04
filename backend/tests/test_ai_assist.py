"""AI help inside the application's screens: the gate every job passes, and what each feature does with an answer.

No database and no network: the model is a stand-in, and the settings, policy and spend the gate reads are patched.
"""

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.ai import assist, features  # noqa: E402
from app.ai.providers.base import Health, ProviderError, ProviderTurn, Usage  # noqa: E402

USER = {"id": 7}


class FakeProvider:
    name = "fake"
    model = "fake-model"

    def __init__(self, text="Fine.", health=None, fail=False):
        self.text = text
        self._health = health or Health("ok")
        self.fail = fail
        self.calls = []

    def health(self):
        return self._health

    def complete(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail:
            raise ProviderError("down", kind="unavailable")
        return ProviderTurn(text=self.text, usage=Usage(10, 5))

    def structured(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail:
            raise ProviderError("not json", kind="invalid")
        return json.loads(self.text), ProviderTurn(text=self.text, usage=Usage(10, 5))


class Gate(unittest.TestCase):
    """Every feature goes through ``assist.run``, so the rules are tested once, here."""

    def setUp(self):
        assist.reset_limits()
        self.addCleanup(assist.reset_limits)
        self.log = mock.MagicMock()

    def go(self, job=None, *, local=None, cloud=None, mode="local_only", allow_cloud=False, consent=False, enabled=True, user=USER):
        patches = [
            mock.patch.object(assist.store, "get_settings", return_value={"enabled": enabled, "allow_cloud": allow_cloud}),
            mock.patch.object(assist.store, "get_policy", return_value={"cloud_mode": mode}),
            mock.patch.object(assist.store, "cloud_spend_this_month", return_value=0.0),
            mock.patch.object(assist.store, "cloud_answers_today", return_value=0),
            mock.patch.object(assist.store, "log_route", self.log),
            mock.patch.object(assist.providers, "local_provider", return_value=local),
            mock.patch.object(assist.providers, "cloud_provider", return_value=cloud),
            mock.patch.object(assist.config, "cloud_switched_on", return_value=True),
            mock.patch.object(assist.config, "cloud_ready", return_value=True),
            mock.patch.object(assist.config, "cloud_monthly_budget", return_value=5.0),
            mock.patch.object(assist.config, "cloud_user_daily", return_value=50),
            mock.patch.object(assist.config, "cloud_provider_name", return_value="anthropic"),
            mock.patch.object(assist.guards.cloud_breaker, "failure"),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        job = job or assist.Job(kind="test", system="system", prompt="a private paragraph about Acme Hospital")
        return assist.run(user, job, allow_cloud_once=consent)

    def test_a_model_on_this_computer_is_used_and_nothing_leaves_it(self):
        local, cloud = FakeProvider("local answer"), FakeProvider()
        result = self.go(local=local, cloud=cloud, mode="cloud_eligible", allow_cloud=True)
        self.assertEqual((result["status"], result["where"], result["text"]), ("ok", "local", "local answer"))
        self.assertEqual(cloud.calls, [])

    def test_no_model_here_and_no_cloud_policy_means_unavailable(self):
        cloud = FakeProvider()
        result = self.go(cloud=cloud, mode="local_only", consent=True)
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(cloud.calls, [])

    def test_cloud_is_asked_about_first_and_used_only_after_a_yes(self):
        cloud = FakeProvider("from the cloud")
        asked = self.go(cloud=cloud, mode="local_first", allow_cloud=True)
        self.assertEqual(asked["status"], "needs_consent")
        self.assertEqual(cloud.calls, [])
        done = self.go(cloud=cloud, mode="local_first", allow_cloud=True, consent=True)
        self.assertEqual((done["status"], done["where"], done["text"]), ("ok", "cloud", "from the cloud"))

    def test_a_job_that_carries_application_data_is_blocked_by_a_no_app_data_policy(self):
        cloud = FakeProvider()
        result = self.go(cloud=cloud, mode="no_app_data", allow_cloud=True, consent=True)
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(cloud.calls, [])

    def test_a_wording_only_job_may_go_to_the_cloud_under_a_no_app_data_policy_with_a_yes(self):
        cloud = FakeProvider("polite words")
        job = assist.Job(kind="wording", system="s", prompt="Tone: polite", needs_data=False)
        result = self.go(job, cloud=cloud, mode="no_app_data", allow_cloud=True, consent=True)
        self.assertEqual((result["status"], result["where"]), ("ok", "cloud"))

    def test_a_structured_job_returns_data(self):
        local = FakeProvider('{"title": "Fire licence"}')
        job = assist.Job(kind="doc", system="s", prompt="p", schema={"type": "object"})
        result = self.go(job, local=local)
        self.assertEqual(result["data"], {"title": "Fire licence"})

    def test_a_switched_off_copilot_and_a_person_without_access_get_nothing(self):
        local = FakeProvider()
        self.assertEqual(self.go(local=local, enabled=False)["status"], "unavailable")
        self.assertEqual(self.go(local=local, user={"id": 7, "ai_access": False})["status"], "unavailable")
        self.assertEqual(local.calls, [])

    def test_a_provider_failure_is_a_plain_message_without_the_technical_text(self):
        result = self.go(local=FakeProvider(fail=True))
        self.assertEqual(result["status"], "unavailable")
        self.assertNotIn("down", result["message"])

    def test_one_person_cannot_ask_more_than_twenty_times_a_minute(self):
        local = FakeProvider()
        for _ in range(assist.PER_MINUTE):
            self.assertEqual(self.go(local=local)["status"], "ok")
        self.assertEqual(self.go(local=local)["status"], "unavailable")
        self.assertEqual(self.go(local=local, user={"id": 8})["status"], "ok")

    def test_what_was_asked_and_answered_is_never_logged(self):
        local = FakeProvider("a confidential answer")
        self.go(local=local)
        self.assertEqual(self.log.call_count, 1)
        logged = repr(self.log.call_args)
        self.assertNotIn("Acme Hospital", logged)
        self.assertNotIn("confidential answer", logged)
        self.assertIn("assist_test", logged)


class Letters(unittest.TestCase):
    def test_a_model_cannot_put_markup_into_a_letter(self):
        out = features.paragraphs_to_html('Dear Sir,\n\n<script>alert(1)</script><img src=x onerror=alert(1)>\n\n- one\n- <b>two</b>')
        # Whatever the model wrote is text, not markup: every angle bracket in it is escaped.
        self.assertNotIn("<script", out)
        self.assertNotIn("<img", out)
        self.assertNotIn("<b>", out)
        self.assertIn("&lt;script&gt;", out)
        self.assertIn("<ul>", out)
        self.assertEqual(out.count("<li>"), 2)

    def test_paragraphs_lists_and_line_breaks_become_the_letters_own_tags(self):
        out = features.paragraphs_to_html("First paragraph.\nSecond line.\n\n1. Alpha\n2. Beta")
        self.assertIn("<p>First paragraph.<br>Second line.</p>", out)
        self.assertIn("<ol><li>Alpha</li><li>Beta</li></ol>", out)

    def test_a_letter_needs_something_to_work_from(self):
        user = USER
        self.assertEqual(features.write_letter(user, mode="draft", brief="hi")["status"], "invalid")
        self.assertEqual(features.write_letter(user, mode="improve", text="  ", action="grammar")["status"], "invalid")
        self.assertEqual(features.write_letter(user, mode="improve", text="Hello", action="send")["status"], "invalid")
        self.assertEqual(features.write_letter(user, mode="improve", text="Hello", action="translate", language="  ")["status"], "invalid")
        self.assertEqual(features.write_letter(user, mode="reply")["status"], "invalid")

    def test_the_answer_is_returned_as_html_and_the_material_is_marked_as_data(self):
        seen = {}

        def fake_run(user, job, allow_cloud_once=False):
            seen["job"] = job
            return {"status": "ok", "where": "local", "provider": "fake", "text": "We wish to renew.\n\nPlease confirm.", "data": None}

        with mock.patch.object(features.assist, "run", side_effect=fake_run):
            out = features.write_letter(USER, mode="draft", brief="renew the contract for one more year", tone="firm")
        self.assertEqual(out["status"], "ok")
        self.assertEqual(out["html"], "<p>We wish to renew.</p><p>Please confirm.</p>")
        self.assertIn("<material>", seen["job"].prompt)
        self.assertIn("ignore them", seen["job"].system)


class Reminders(unittest.TestCase):
    STATEMENT = {
        "client_name": "Acme Hospital",
        "billing_name": None,
        "as_of": "2026-10-10",
        "total": 59000,
        "bills": [{"bill_number": "B-1", "bill_date": "2026-08-01", "service_month": "2026-07", "balance": 59000, "days": 70}],
    }
    PROFILE = {"company_name": "Prakash Securities", "bank_name": "HDFC", "bank_account": "123", "bank_ifsc": "HDFC0001"}

    def run_reminder(self, answer, profile=None):
        seen = {}

        def fake_run(user, job, allow_cloud_once=False):
            seen["job"] = job
            return {"status": "ok", "where": "cloud", "provider": "fake", "text": answer, "data": None}

        with mock.patch.object(features.assist, "run", side_effect=fake_run):
            out = features.word_reminder(USER, self.STATEMENT, profile or self.PROFILE, tone="firm")
        return out, seen.get("job")

    def test_missing_or_repeated_tokens_are_found(self):
        ok = features.reminder_skeleton(True)
        self.assertEqual(features.reminder_missing_tokens(ok, True), [])
        self.assertIn("[BILLS]", features.reminder_missing_tokens(ok.replace("[BILLS]", ""), True))
        self.assertIn("[TOTAL]", features.reminder_missing_tokens(ok + "\n[TOTAL]", True))
        self.assertIn("[BANK]", features.reminder_missing_tokens(ok, False))

    def test_the_model_sees_the_wording_only_and_the_app_fills_in_names_and_amounts(self):
        out, job = self.run_reminder(features.reminder_skeleton(True).replace("gentle reminder", "firm reminder"))
        self.assertEqual(out["status"], "ok")
        for private in ("Acme", "59,000", "B-1", "HDFC", "123"):
            self.assertNotIn(private, job.prompt)
        self.assertFalse(job.needs_data)
        self.assertIn("Dear Acme Hospital,", out["message"])
        self.assertIn("Bill B-1 dated 01 Aug 2026", out["message"])
        self.assertIn("59,000", out["message"])
        self.assertIn("A/c No. 123", out["message"])
        self.assertNotIn("[", out["message"])

    def test_a_reply_that_lost_the_bill_list_is_never_used(self):
        out, _ = self.run_reminder("Dear [CLIENT], please pay [TOTAL]. Regards, [COMPANY]")
        self.assertEqual(out["status"], "unavailable")
        self.assertNotIn("Dear", out["message"])

    def test_an_unknown_tone_is_refused(self):
        self.assertEqual(features.word_reminder(USER, self.STATEMENT, self.PROFILE, tone="threatening")["status"], "invalid")


class Documents(unittest.TestCase):
    CATEGORIES = ["Licence", "Contract", "Invoice"]

    def test_a_suggestion_is_reduced_to_what_the_form_accepts(self):
        raw = {
            "title": "  PSARA   licence ",
            "category": "licence",
            "document_date": "2026-04-01",
            "expiry_date": "2027-03-31",
            "tags": ["PSARA", "psara", "#Guarding,", "", "a", "b", "c", "d"],
            "description": "x" * 900,
        }
        out = features.clean_document_suggestion(raw, self.CATEGORIES, "scan_001")
        self.assertEqual(out["title"], "PSARA licence")
        self.assertEqual(out["category"], "Licence")
        self.assertEqual((out["document_date"], out["expiry_date"]), ("2026-04-01", "2027-03-31"))
        self.assertEqual(out["tags"][:2], ["psara", "guarding"])
        self.assertLessEqual(len(out["tags"]), 5)
        self.assertLessEqual(len(out["description"]), 300)

    def test_a_category_that_is_not_on_the_list_a_bad_date_and_an_expiry_before_issue_are_dropped(self):
        out = features.clean_document_suggestion(
            {"category": "Passport", "document_date": "2026-04-01", "expiry_date": "2025-01-01", "title": ""}, self.CATEGORIES, "scan_001"
        )
        self.assertEqual((out["category"], out["expiry_date"], out["title"]), ("", "", "scan_001"))
        out = features.clean_document_suggestion({"document_date": "next Tuesday", "expiry_date": "2999-01-01"}, self.CATEGORIES, "x")
        self.assertEqual((out["document_date"], out["expiry_date"]), ("", ""))

    def test_a_document_with_no_readable_text_is_suggested_from_its_name_and_says_so(self):
        seen = {}

        def fake_run(user, job, allow_cloud_once=False):
            seen["job"] = job
            return {"status": "ok", "where": "local", "provider": "fake", "text": "", "data": {"title": "Fire NOC", "category": "Licence"}}

        with mock.patch.object(features.assist, "run", side_effect=fake_run), mock.patch.object(features, "extract_text", return_value=""):
            out = features.suggest_document(USER, filename="C:\\scans\\fire_noc.pdf", data=b"%PDF", categories=self.CATEGORIES)
        self.assertFalse(out["read_text"])
        self.assertEqual(out["suggestion"]["title"], "Fire NOC")
        self.assertIn("no readable text", seen["job"].prompt)
        self.assertIn("fire_noc", seen["job"].prompt)
        self.assertNotIn("scans", seen["job"].prompt)


class Forms(unittest.TestCase):
    ENTITY = {
        "primary_key": "employee_code",
        "private_columns": ["aadhaar", "salary"],
        "form_fields": {
            "employee_code": {"type": "text", "label": "Code"},
            "full_name": {"type": "text", "label": "Name"},
            "joining_date": {"type": "date", "label": "Joined"},
            "grade": {"type": "select", "label": "Grade", "options": ["Guard", "Supervisor"]},
            "client_code": {"type": "select", "label": "Client", "source_table": "orion_ods.client"},
            "total": {"type": "number", "label": "Total", "compute_from": ["a", "b"]},
            "aadhaar": {"type": "text", "label": "Aadhaar"},
            "salary": {"type": "number", "label": "Salary"},
            "age": {"type": "integer", "label": "Age"},
            "married": {"type": "boolean", "label": "Married"},
            "notes": {"type": "textarea", "label": "Notes"},
            "state": {"type": "state", "label": "State"},
        },
    }

    def test_only_plain_fields_are_ever_offered_to_a_model(self):
        self.assertEqual(
            sorted(features.fillable_fields(self.ENTITY)), ["age", "full_name", "grade", "joining_date", "married", "state"]
        )

    def test_values_are_coerced_to_what_the_field_holds(self):
        field = self.ENTITY["form_fields"]
        self.assertEqual(features._coerce(field["age"], "27.4"), 27)
        self.assertEqual(features._coerce(self.ENTITY["form_fields"]["salary"], "1,25,000.456"), 125000.46)
        self.assertEqual(features._coerce(field["joining_date"], "2026-11-01"), "2026-11-01")
        self.assertIsNone(features._coerce(field["joining_date"], "1 November"))
        self.assertEqual(features._coerce(field["grade"], "supervisor"), "Supervisor")
        self.assertIsNone(features._coerce(field["grade"], "Manager"))
        self.assertTrue(features._coerce(field["married"], "Yes"))
        self.assertFalse(features._coerce(field["married"], "no"))
        self.assertIsNone(features._coerce(field["married"], "maybe"))
        self.assertIsNone(features._coerce(field["age"], "twenty"))

    def test_a_model_that_answers_for_a_lookup_or_a_private_field_has_that_part_ignored(self):
        answer = {
            "full_name": "Ramesh  Patil",
            "client_code": "C-001",
            "aadhaar": "1234 5678 9012",
            "salary": 40000,
            "grade": "Guard",
            "joining_date": "2026-11-01",
            "age": "banana",
        }

        def fake_run(user, job, allow_cloud_once=False):
            self.assertNotIn("aadhaar", job.prompt)
            self.assertNotIn("client_code", job.prompt)
            return {"status": "ok", "where": "local", "provider": "fake", "text": "", "data": answer}

        with mock.patch.object(features.assist, "run", side_effect=fake_run):
            out = features.fill_form(USER, self.ENTITY, "New guard Ramesh Patil joining 1 November 2026")
        self.assertEqual(out["values"], {"full_name": "Ramesh Patil", "grade": "Guard", "joining_date": "2026-11-01"})
        self.assertEqual(out["labels"]["full_name"], "Name")

    def test_too_little_text_is_refused_without_calling_a_model(self):
        with mock.patch.object(features.assist, "run") as run:
            self.assertEqual(features.fill_form(USER, self.ENTITY, "hi")["status"], "invalid")
        run.assert_not_called()


class FailedLoads(unittest.TestCase):
    def test_a_run_with_no_error_text_has_nothing_to_explain(self):
        self.assertEqual(features.explain_failed_load(USER, label="Orion warehouse", errors=["", "  "])["status"], "invalid")

    def test_only_the_error_text_is_sent_and_it_is_marked_as_data(self):
        seen = {}

        def fake_run(user, job, allow_cloud_once=False):
            seen["job"] = job
            return {"status": "ok", "where": "local", "provider": "fake", "text": "What happened: the database refused.", "data": None}

        with mock.patch.object(features.assist, "run", side_effect=fake_run):
            out = features.explain_failed_load(USER, label="Orion warehouse", errors=["connection refused\n  host db"] * 12)
        self.assertEqual(out["status"], "ok")
        self.assertIn("<failure>", seen["job"].prompt)
        self.assertEqual(seen["job"].prompt.count("connection refused host db"), 8)


if __name__ == "__main__":
    unittest.main()
