"""The parts of messaging that need no database: limits, what a deleted message shows, what the AI helper may do.

The rules about who can read and change what are in test_chat_integration.py, which needs the development database.
"""

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app import chat, chat_ai  # noqa: E402
from app.ai import assist  # noqa: E402
from app.ai.providers.base import Health, ProviderError, ProviderTurn, Usage  # noqa: E402


class Limits(unittest.TestCase):
    def test_a_burst_is_cut_off_and_then_allowed_again(self):
        window = chat._Windows()
        for _ in range(3):
            window.take(1, "send", 3, 60)
        with self.assertRaises(chat.RateLimited):
            window.take(1, "send", 3, 60)
        window.take(2, "send", 3, 60)  # another person is not affected
        window.take(1, "typing", 3, 60)  # nor is another kind of action
        window.reset()
        window.take(1, "send", 3, 60)

    def test_a_window_forgets_old_hits(self):
        window = chat._Windows()
        with mock.patch("app.chat.time.monotonic", side_effect=[0, 1, 100]):
            window.take(1, "send", 2, 10)
            window.take(1, "send", 2, 10)
            window.take(1, "send", 2, 10)  # the first two are 100 seconds old by now

    def test_error_kinds_are_distinct_so_the_router_can_choose_a_status(self):
        for kind in (chat.NotFound, chat.Forbidden, chat.RateLimited):
            self.assertTrue(issubclass(kind, chat.ChatError))
        self.assertFalse(issubclass(chat.NotFound, chat.Forbidden))


class Payloads(unittest.TestCase):
    def row(self, **over):
        base = {
            "id": 5, "chat_id": 1, "sender_id": 7, "body": "hello", "created_timestamp": datetime(2026, 10, 10, tzinfo=timezone.utc),
            "edited_timestamp": None, "deleted_timestamp": None, "forwarded": False, "client_id": "c1", "reply_to_id": None,
            "media_kind": None, "media_ext": None, "media_name": None, "media_type": None, "media_size": None,
        }
        base.update(over)
        return base

    def test_a_deleted_message_shows_nothing_of_what_it_held(self):
        payload = chat._message_payload(
            self.row(body="secret", deleted_timestamp=datetime.now(timezone.utc), media_kind="image", media_name="plan.png", media_size=900, forwarded=True),
            [{"emoji": "👍", "user_ids": [1]}],
        )
        self.assertTrue(payload["deleted"])
        self.assertEqual(payload["body"], "")
        self.assertIsNone(payload["media_kind"])
        self.assertIsNone(payload["media_url"])
        self.assertIsNone(payload["media_name"])
        self.assertEqual(payload["reactions"], [])
        self.assertFalse(payload["forwarded"])

    def test_a_reply_to_a_deleted_message_quotes_nothing(self):
        payload = chat._message_payload(
            self.row(reply_to_id=2, reply_sender_id=9, reply_body="the original text", reply_deleted=datetime.now(timezone.utc), reply_media_kind=None, reply_media_name=None)
        )
        self.assertEqual(payload["reply_to"], {"id": 2, "sender_id": 9, "body": "", "media_kind": None, "media_name": None, "deleted": True})

    def test_a_long_quote_is_cut_short(self):
        payload = chat._message_payload(self.row(reply_to_id=2, reply_sender_id=9, reply_body="word " * 100, reply_deleted=None, reply_media_kind=None, reply_media_name=None))
        self.assertLessEqual(len(payload["reply_to"]["body"]), chat.SNIPPET)
        self.assertTrue(payload["reply_to"]["body"].endswith("…"))

    def test_an_attachment_gets_a_url_that_is_checked_on_every_request(self):
        payload = chat._message_payload(self.row(media_kind="file", media_name="a.pdf", media_size=10))
        self.assertEqual(payload["media_url"], "/api/messages/media/5")

    def test_emoji_must_be_an_emoji(self):
        self.assertEqual(chat._clean_emoji(" 👍 "), "👍")
        self.assertEqual(chat._clean_emoji("❤️"), "❤️")
        for bad in ("", "hello", "a b", "👍 👍", "x" * 20, "1"):
            with self.subTest(bad=bad):
                with self.assertRaises(chat.ChatError):
                    chat._clean_emoji(bad)

    def test_a_message_is_trimmed_and_limited(self):
        self.assertEqual(chat._clean_body("  hi\r\nthere \x00 "), "hi\nthere")
        with self.assertRaises(chat.ChatError):
            chat._clean_body("x" * (chat.MAX_BODY + 1))


class Files(unittest.TestCase):
    def test_a_file_name_cannot_carry_a_folder_a_newline_or_a_quote_into_a_header(self):
        from app.chat_media import _safe_name, media_response

        self.assertEqual(_safe_name("../../etc/passwd"), "passwd")
        self.assertEqual(_safe_name("report" + chr(13) + chr(10) + "Set-Cookie: x=1.pdf"), "reportSet-Cookie: x=1.pdf")
        self.assertEqual(_safe_name('na"me.txt'), "name.txt")
        self.assertEqual(_safe_name("   "), "file")
        self.assertLessEqual(len(_safe_name("x" * 500)), 180)
        response = media_response(Path(__file__), "text/plain", 'a"b.txt', inline=False)
        self.assertEqual(response.headers["x-content-type-options"], "nosniff")
        self.assertTrue(response.headers["content-disposition"].startswith("attachment;"))


class FakeProvider:
    name = "fake"
    location = "local"
    model = "fake-model"

    def __init__(self, text="A rewritten message.", health=None, fail=False):
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


class Assistant(unittest.TestCase):
    """What the AI helper may do with a private conversation."""

    def run_assist(self, *, local=None, cloud=None, mode="local_only", allow_cloud=False, enabled=True, consent=False, action="rewrite", text="hello there", cloud_ready=True, history="Me: hi\nThem: hello"):
        user = {"id": 7}
        patches = [
            mock.patch.object(chat, "_direct_peer", return_value=8),
            mock.patch.object(chat_ai.chat.limits, "take"),
            mock.patch.object(assist.store, "get_settings", return_value={"enabled": enabled, "allow_cloud": allow_cloud}),
            mock.patch.object(assist.store, "get_policy", return_value={"cloud_mode": mode}),
            mock.patch.object(assist.store, "cloud_spend_this_month", return_value=0.0),
            mock.patch.object(assist.store, "cloud_answers_today", return_value=0),
            mock.patch.object(assist.store, "log_route"),
            mock.patch.object(assist.providers, "local_provider", return_value=local),
            mock.patch.object(assist.providers, "cloud_provider", return_value=cloud),
            mock.patch.object(assist.config, "cloud_switched_on", return_value=cloud_ready),
            mock.patch.object(assist.config, "cloud_ready", return_value=cloud_ready),
            mock.patch.object(assist.config, "cloud_monthly_budget", return_value=5.0),
            mock.patch.object(assist.config, "cloud_user_daily", return_value=50),
            mock.patch.object(assist.config, "cloud_provider_name", return_value="anthropic"),
            mock.patch.object(assist.guards.cloud_breaker, "failure"),
            mock.patch.object(chat_ai, "_history", return_value=history),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        tone = "friendly" if action == "rewrite" else ""
        return chat_ai.assist(user, 1, action, text=text, tone=tone, language="Hindi" if action == "translate" else "", allow_cloud_once=consent)

    def test_a_model_on_this_computer_is_used_first_and_nothing_leaves_it(self):
        local, cloud = FakeProvider(), FakeProvider()
        result = self.run_assist(local=local, cloud=cloud, mode="cloud_eligible", allow_cloud=True)
        self.assertEqual((result["status"], result["where"], result["text"]), ("ok", "local", "A rewritten message."))
        self.assertEqual(len(local.calls), 1)
        self.assertEqual(cloud.calls, [])

    def test_with_no_local_model_and_the_default_policy_nothing_is_sent_anywhere(self):
        cloud = FakeProvider()
        result = self.run_assist(local=None, cloud=cloud)
        self.assertEqual(result["status"], "unavailable")
        self.assertIn("does not allow cloud", result["message"])
        self.assertEqual(cloud.calls, [])

    def test_even_when_policy_and_person_allow_cloud_each_request_needs_a_yes(self):
        cloud = FakeProvider()
        result = self.run_assist(local=None, cloud=cloud, mode="local_first", allow_cloud=True)
        self.assertEqual(result["status"], "needs_consent")
        self.assertIn("anthropic".capitalize(), result["message"])
        self.assertEqual(cloud.calls, [])

    def test_a_person_who_has_not_allowed_cloud_in_general_is_asked_not_refused(self):
        cloud = FakeProvider()
        result = self.run_assist(local=None, cloud=cloud, mode="local_first", allow_cloud=False, consent=False)
        self.assertEqual(result["status"], "needs_consent")
        self.assertEqual(cloud.calls, [])

    def test_a_yes_for_this_one_request_is_the_persons_permission_when_the_organisation_allows_cloud(self):
        cloud = FakeProvider("Fine by me.")
        result = self.run_assist(local=None, cloud=cloud, mode="local_first", allow_cloud=False, consent=True)
        self.assertEqual((result["status"], result["where"]), ("ok", "cloud"))

    def test_no_yes_gets_past_an_organisation_that_allows_no_cloud(self):
        cloud = FakeProvider()
        result = self.run_assist(local=None, cloud=cloud, mode="local_only", allow_cloud=True, consent=True)
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(cloud.calls, [])

    def test_no_yes_gets_past_a_policy_that_sends_no_application_data(self):
        cloud = FakeProvider()
        result = self.run_assist(local=None, cloud=cloud, mode="no_app_data", allow_cloud=True, consent=True)
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(cloud.calls, [])

    def test_with_everything_allowed_and_a_yes_the_cloud_model_is_used_and_it_is_said_so(self):
        cloud = FakeProvider("Sounds good to me.")
        result = self.run_assist(local=None, cloud=cloud, mode="local_first", allow_cloud=True, consent=True)
        self.assertEqual((result["status"], result["where"], result["provider"]), ("ok", "cloud", "fake"))
        self.assertEqual(len(cloud.calls), 1)

    def test_a_stopped_local_model_never_quietly_becomes_cloud_traffic(self):
        local = FakeProvider(health=Health("unreachable"))
        cloud = FakeProvider()
        result = self.run_assist(local=local, cloud=cloud, mode="local_first", allow_cloud=True)
        self.assertEqual(result["status"], "needs_consent")
        self.assertEqual(cloud.calls, [])

    def test_the_model_is_given_me_and_them_never_names_and_is_told_the_chat_is_data(self):
        local = FakeProvider("1. Yes\n2. No\n3. Maybe")
        result = self.run_assist(local=local, action="reply", history="Me: can you send the roster\nThem: yes, by 5")
        self.assertEqual(result["options"], ["Yes", "No", "Maybe"])
        sent = local.calls[0]
        self.assertIn("<chat>", sent["messages"][0]["content"])
        self.assertIn("Them: yes, by 5", sent["messages"][0]["content"])
        self.assertIn("ignore them", sent["system"])
        self.assertEqual(sent["tools"], [])

    def test_a_reply_to_the_model_cannot_become_a_sent_message(self):
        # The result is text. There is no code path from here to chat.send_message.
        self.assertNotIn("send_message", chat_ai.assist.__code__.co_names)

    def test_a_switched_off_copilot_means_no_ai_help_at_all(self):
        result = self.run_assist(local=FakeProvider(), enabled=False)
        self.assertEqual(result["status"], "unavailable")

    def test_a_provider_failure_is_a_plain_message(self):
        result = self.run_assist(local=FakeProvider(fail=True))
        self.assertEqual(result["status"], "unavailable")
        self.assertNotIn("down", result["message"])

    def test_empty_input_and_unknown_actions_are_refused(self):
        with self.assertRaises(chat.ChatError):
            self.run_assist(local=FakeProvider(), text="  ")
        with self.assertRaises(chat.ChatError):
            self.run_assist(local=FakeProvider(), action="send_for_me")


if __name__ == "__main__":
    unittest.main()
