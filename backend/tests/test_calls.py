"""The call switchboard (calls.py) without a database: who is rung, who may pass set-up messages, how each call ends and what it leaves in the chat."""

import asyncio
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app import calls, chat  # noqa: E402

ADA = {"id": 1, "display_name": "Ada"}
BEN = {"id": 2, "display_name": "Ben"}


class FakeHub:
    def __init__(self, online):
        self.online = set(online)
        self.sent = []

    def is_online(self, user_id):
        return user_id in self.online

    async def send_user(self, user_id, payload):
        self.sent.append((user_id, payload))

    def to(self, user_id, kind):
        return [p for u, p in self.sent if u == user_id and p["type"] == kind]


class Switchboard(unittest.TestCase):
    def setUp(self):
        chat.limits.reset()
        self.hub = FakeHub({1, 2})
        self.messages = []
        self.closed = []
        self.patches = [
            mock.patch.object(calls, "hub", self.hub),
            mock.patch.object(calls, "_create", side_effect=self._create),
            mock.patch.object(calls, "_answered"),
            mock.patch.object(calls, "_close", side_effect=lambda call_id, outcome: self.closed.append((call_id, outcome))),
            mock.patch.object(calls, "_person", side_effect=lambda user_id: {"id": user_id, "display_name": {1: "Ada", 2: "Ben"}.get(user_id, "x")}),
            mock.patch.object(chat, "_direct_peer", side_effect=lambda chat_id, user_id: 2 if user_id == 1 else 1),
            mock.patch.object(chat, "add_call_message", side_effect=self._line),
            mock.patch.object(chat, "is_muted", return_value=False),
            mock.patch.object(chat, "unread_count", return_value=0),
        ]
        for patch in self.patches:
            patch.start()
        self.addCleanup(lambda: [patch.stop() for patch in self.patches])
        self.desk = calls.CallDesk()

    def _create(self, chat_id, caller_id, callee_id, kind):
        return 7

    def _line(self, chat_id, caller_id, call_id, *, seen_by_other):
        self.messages.append(seen_by_other)
        return {"id": 99, "chat_id": chat_id, "sender_id": caller_id, "other_ids": [2 if caller_id == 1 else 1]}

    def run_async(self, coroutine):
        return asyncio.run(coroutine)

    def test_a_call_rings_the_other_person_and_tells_the_caller(self):
        async def scenario():
            await self.desk.invite(ADA, 5, "video")
            self.assertEqual(self.desk.live[7].state, "ringing")
            self.desk.live[7].timer.cancel()

        self.run_async(scenario())
        ring = self.hub.to(2, "call_ring")[0]["call"]
        self.assertEqual((ring["id"], ring["kind"], ring["caller"]["display_name"]), (7, "video", "Ada"))
        self.assertEqual(self.hub.to(1, "call_started")[0]["call"]["id"], 7)

    def test_only_voice_or_video_can_be_asked_for(self):
        with self.assertRaises(chat.ChatError):
            self.run_async(self.desk.invite(ADA, 5, "hologram"))

    def test_nobody_rings_someone_who_is_offline_and_it_is_kept_as_missed(self):
        self.hub.online = {1}
        self.run_async(self.desk.invite(ADA, 5, "voice"))
        self.assertEqual(self.closed, [(7, "missed")])
        self.assertEqual(self.messages, [False])  # unread for the person who missed it
        ended = self.hub.to(1, "call_ended")[0]
        self.assertEqual((ended["outcome"], ended["reason"]), ("missed", "offline"))
        self.assertEqual(ended["peer"]["id"], 2)  # the caller is told who was not there
        self.assertEqual(self.hub.to(2, "call_ring"), [])
        self.assertEqual(self.desk.live, {})

    def test_someone_already_in_a_call_is_busy(self):
        async def scenario():
            self.desk.live[3] = calls.Live(3, 9, 2, 3, "voice", state="active")
            await self.desk.invite(ADA, 5, "voice")

        self.run_async(scenario())
        self.assertEqual(self.hub.to(1, "call_ended")[0]["reason"], "busy")
        self.assertEqual(self.hub.to(2, "call_ring"), [])

    def test_a_person_cannot_start_a_second_call(self):
        async def scenario():
            self.desk.live[3] = calls.Live(3, 9, 1, 3, "voice", state="active")
            await self.desk.invite(ADA, 5, "voice")

        with self.assertRaises(chat.ChatError):
            self.run_async(scenario())

    def test_answering_connects_both_and_stops_the_ringing(self):
        async def scenario():
            await self.desk.invite(ADA, 5, "voice")
            timer = self.desk.live[7].timer
            await self.desk.accept(BEN, 7)
            await asyncio.sleep(0)
            self.assertTrue(timer.cancelled())
            self.assertEqual(self.desk.live[7].state, "active")

        self.run_async(scenario())
        for who in (1, 2):
            self.assertEqual(self.hub.to(who, "call_accepted")[0]["by"], 2)

    def test_only_the_person_rung_can_answer_and_only_while_it_rings(self):
        async def scenario():
            await self.desk.invite(ADA, 5, "voice")
            with self.assertRaises(chat.ChatError):
                await self.desk.accept(ADA, 7)  # the caller cannot answer their own call
            await self.desk.accept(BEN, 7)
            with self.assertRaises(chat.ChatError):
                await self.desk.accept(BEN, 7)  # nor twice

        self.run_async(scenario())

    def test_a_stranger_cannot_touch_a_call(self):
        async def scenario():
            await self.desk.invite(ADA, 5, "voice")
            self.desk.live[7].timer.cancel()
            for action in (self.desk.accept, self.desk.end):
                with self.assertRaises(chat.NotFound):
                    await action({"id": 3, "display_name": "Cy"}, 7)
            with self.assertRaises(chat.NotFound):
                await self.desk.signal({"id": 3, "display_name": "Cy"}, 7, {"type": "offer"})
            with self.assertRaises(chat.NotFound):
                await self.desk.end(ADA, "not-a-number")

        self.run_async(scenario())

    def test_set_up_messages_go_only_to_the_other_person_of_a_live_call(self):
        async def scenario():
            await self.desk.invite(ADA, 5, "video")
            with self.assertRaises(chat.ChatError):
                await self.desk.signal(ADA, 7, {"type": "offer", "sdp": "x"})  # not connected yet
            await self.desk.accept(BEN, 7)
            await self.desk.signal(ADA, 7, {"type": "offer", "sdp": "x"})
            await self.desk.signal(BEN, 7, {"type": "candidate", "candidate": {"candidate": "c"}})
            await self.desk.signal(BEN, 7, {"type": "state", "mic": False, "cam": True, "screen": False})
            await self.desk.signal(ADA, 7, {"type": "run-this", "sdp": "x"})  # not a kind of set-up message: dropped
            await self.desk.signal(ADA, 7, "offer")  # not an object: dropped

        self.run_async(scenario())
        self.assertEqual([m["data"]["type"] for m in self.hub.to(2, "call_signal")], ["offer"])
        self.assertEqual([m["data"]["type"] for m in self.hub.to(1, "call_signal")], ["candidate", "state"])
        self.assertEqual(self.hub.to(2, "call_signal")[0]["from"], 1)

    def test_a_huge_set_up_message_is_refused(self):
        async def scenario():
            await self.desk.invite(ADA, 5, "voice")
            await self.desk.accept(BEN, 7)
            await self.desk.signal(ADA, 7, {"type": "offer", "sdp": "x" * (calls.MAX_SIGNAL_BYTES + 1)})

        with self.assertRaises(chat.ChatError):
            self.run_async(scenario())

    def test_how_a_call_ends_depends_on_who_ends_it_and_when(self):
        cases = [
            ("the caller gives up while it rings", ADA, False, "cancelled", False),
            ("the person rung turns it down", BEN, False, "declined", True),
            ("either hangs up a call under way", BEN, True, "ended", True),
        ]
        for label, who, answered, outcome, seen in cases:
            with self.subTest(label):
                self.closed.clear()
                self.messages.clear()
                self.desk = calls.CallDesk()

                async def scenario(who=who, answered=answered):
                    await self.desk.invite(ADA, 5, "voice")
                    if answered:
                        await self.desk.accept(BEN, 7)
                    await self.desk.end(who, 7)

                self.run_async(scenario())
                self.assertEqual(self.closed, [(7, outcome)])
                self.assertEqual(self.messages, [seen])
                self.assertEqual(self.desk.live, {})

    def test_a_call_nobody_answers_is_missed(self):
        async def scenario():
            with mock.patch.object(calls, "RING_SECONDS", 0.01):
                await self.desk.invite(ADA, 5, "voice")
                await asyncio.sleep(0.1)

        self.run_async(scenario())
        self.assertEqual(self.closed, [(7, "missed")])
        self.assertEqual(self.hub.to(1, "call_ended")[0]["reason"], "no_answer")
        self.assertEqual(self.messages, [False])

    def test_a_call_ends_when_the_person_in_it_goes_away(self):
        async def scenario():
            await self.desk.invite(ADA, 5, "voice")
            await self.desk.accept(BEN, 7)
            await self.desk.on_disconnect(2)

        self.run_async(scenario())
        self.assertEqual(self.closed, [(7, "ended")])
        self.assertEqual(self.hub.to(1, "call_ended")[0]["outcome"], "ended")

    def test_a_reload_while_ringing_does_not_drop_the_call_but_the_caller_leaving_does(self):
        async def scenario():
            await self.desk.invite(ADA, 5, "voice")
            await self.desk.on_disconnect(2)
            self.assertIn(7, self.desk.live)
            self.assertIs(self.desk.ringing_for(2), self.desk.live[7])
            await self.desk.on_disconnect(1)
            self.assertEqual(self.desk.live, {})

        self.run_async(scenario())
        self.assertEqual(self.closed, [(7, "cancelled")])

    def test_too_many_calls_in_a_minute_are_slowed(self):
        async def scenario():
            for _ in range(7):
                self.desk.live.clear()
                await self.desk.invite(ADA, 5, "voice")

        with self.assertRaises(chat.RateLimited):
            self.run_async(scenario())


class Network(unittest.TestCase):
    def test_no_servers_are_named_unless_the_env_names_them(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            for name in ("ORION_CALL_STUN_URLS", "ORION_CALL_TURN_URLS", "ORION_CALL_TURN_USER", "ORION_CALL_TURN_PASSWORD"):
                os.environ.pop(name, None)
            self.assertEqual(calls.ice_servers(), [])

    def test_a_relay_needs_its_address_and_both_parts_of_its_login(self):
        env = {"ORION_CALL_STUN_URLS": "stun:a.example:3478, stun:b.example:3478", "ORION_CALL_TURN_URLS": "turn:t.example:3478", "ORION_CALL_TURN_USER": "u"}
        with mock.patch.dict(os.environ, env, clear=False):
            os.environ.pop("ORION_CALL_TURN_PASSWORD", None)
            self.assertEqual(calls.ice_servers(), [{"urls": ["stun:a.example:3478", "stun:b.example:3478"]}])
            os.environ["ORION_CALL_TURN_PASSWORD"] = "p"
            self.assertEqual(calls.ice_servers()[1], {"urls": ["turn:t.example:3478"], "username": "u", "credential": "p"})


class CallLines(unittest.TestCase):
    def test_a_call_line_shows_what_happened_and_nothing_else(self):
        row = {
            "id": 5, "chat_id": 1, "sender_id": 1, "body": "", "created_timestamp": None, "deleted_timestamp": None,
            "call_id": 7, "call_kind": "video", "call_outcome": "ended", "call_caller_id": 1, "call_seconds": 125,
        }
        payload = chat._message_payload(row)
        self.assertEqual(payload["call"], {"id": 7, "kind": "video", "outcome": "ended", "caller_id": 1, "seconds": 125})
        self.assertIsNone(chat._message_payload({**row, "call_id": None})["call"])

    def test_a_voice_note_carries_a_clean_loudness_picture(self):
        self.assertEqual(chat.clean_waveform("0,50,100,7"), "0,50,100,7")
        self.assertEqual(chat.clean_waveform("0,500,-5"), "0,100,0")
        self.assertIsNone(chat.clean_waveform("<script>"))
        self.assertIsNone(chat.clean_waveform(""))
        self.assertEqual(len(chat.clean_waveform(",".join(["9"] * 200)).split(",")), chat.WAVEFORM_BARS)
        row = {"id": 1, "chat_id": 1, "sender_id": 1, "body": "", "created_timestamp": None, "deleted_timestamp": None,
               "media_kind": "audio", "media_duration_ms": 4200, "media_waveform": "10,20"}
        payload = chat._message_payload(row)
        self.assertEqual((payload["media_duration_ms"], payload["media_waveform"]), (4200, [10, 20]))
        self.assertEqual(chat._message_payload({**row, "media_kind": "image"})["media_waveform"], [])


if __name__ == "__main__":
    unittest.main()
