"""Messaging against a real database: who can see and change what, and the rules of replies, edits, reactions and pins.

These need the development database, so they are off unless asked for:

    $env:ORION_CHAT_DB_TESTS = "1"; .\\.venv\\Scripts\\python.exe -m pytest backend/tests/test_chat_integration.py

They create three throwaway people and remove them afterwards. Never point them at the production database.
"""

import os
import secrets
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

RUN = os.environ.get("ORION_CHAT_DB_TESTS") == "1"

if RUN:
    from fastapi.testclient import TestClient

    from app import auth, chat, dependencies, sessions
    from app.database import db_cursor
    from app.main import app


@unittest.skipUnless(RUN, "set ORION_CHAT_DB_TESTS=1 to run the messaging tests against the development database")
class Messaging(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with db_cursor() as cur:
            cur.execute("select current_database()")
            assert cur.fetchone()[0] == "orion", "development database only"
        chat.ensure_chat_tables()
        password = "Aa1-" + secrets.token_urlsafe(10)
        cls.ids = {}
        with db_cursor(commit=True) as cur:
            cur.execute("delete from orion_ods.app_user where username in ('chat_it_a', 'chat_it_b', 'chat_it_c')")
        for key in ("a", "b", "c"):
            cls.ids[key] = auth.create_user(f"chat_it_{key}", f"Chat {key.upper()}", password, "viewer")
        cls.current = {"id": cls.ids["a"]}
        app.dependency_overrides[dependencies.get_current_user] = lambda: auth.fetch_user_by_id(cls.current["id"])
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        app.dependency_overrides.clear()
        cls._wipe()
        with db_cursor(commit=True) as cur:
            cur.execute("delete from orion_ods.app_user where id = any(%s)", (list(cls.ids.values()),))

    @classmethod
    def _wipe(cls):
        """Removes the test conversations (direct and group), and their files with them."""
        from app.chat_media import unlink_media

        ids = list(cls.ids.values())
        with db_cursor() as cur:
            cur.execute(
                """
                select id from orion_ods.direct_chat
                where user_low = any(%s) or user_high = any(%s) or created_by = any(%s)
                   or id in (select chat_id from orion_ods.chat_member where user_id = any(%s))
                """,
                (ids, ids, ids, ids),
            )
            found = [row[0] for row in cur.fetchall()]
        for chat_id in found:
            files = chat._attachments_for_chat(chat_id)
            with db_cursor(commit=True) as cur:
                cur.execute("delete from orion_ods.direct_chat where id = %s", (chat_id,))
            for message_id, ext in files:
                unlink_media(message_id, ext)

    def setUp(self):
        chat.limits.reset()
        self._wipe()

    # -- helpers -------------------------------------------------------------------------------------------------

    def as_(self, who: str):
        type(self).current = {"id": self.ids[who]}

    def start(self, a: str, b: str) -> int:
        self.as_(a)
        response = self.client.post("/api/messages/chats", json={"user_id": self.ids[b]})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["id"]

    def say(self, who: str, chat_id: int, body: str, **extra) -> dict:
        chat.limits.reset()  # these tests send in bursts; the limit itself is tested on its own
        self.as_(who)
        response = self.client.post(f"/api/messages/chats/{chat_id}/messages", json={"body": body, **extra})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    # -- conversations stay private -----------------------------------------------------------------------------------

    def test_an_outsider_cannot_read_or_use_someone_elses_conversation(self):
        chat_id = self.start("a", "b")
        message = self.say("a", chat_id, "private")
        self.as_("c")
        for method, path, kwargs in [
            ("get", f"/api/messages/chats/{chat_id}", {}),
            ("get", f"/api/messages/chats/{chat_id}/messages", {}),
            ("post", f"/api/messages/chats/{chat_id}/messages", {"json": {"body": "hi"}}),
            ("post", f"/api/messages/chats/{chat_id}/read", {}),
            ("get", f"/api/messages/chats/{chat_id}/media", {}),
            ("patch", f"/api/messages/chats/{chat_id}/settings", {"json": {"muted": True}}),
            ("put", f"/api/messages/chats/{chat_id}/pins/{message['id']}", {}),
            ("patch", f"/api/messages/{message['id']}", {"json": {"body": "x"}}),
            ("delete", f"/api/messages/{message['id']}", {}),
            ("put", f"/api/messages/{message['id']}/reactions", {"json": {"emoji": "👍"}}),
            ("get", f"/api/messages/media/{message['id']}", {}),
            ("delete", f"/api/messages/chats/{chat_id}", {}),
        ]:
            with self.subTest(route=f"{method} {path}"):
                response = getattr(self.client, method)(path, **kwargs)
                self.assertEqual(response.status_code, 404, response.text)
        self.as_("a")
        self.assertEqual(self.client.get(f"/api/messages/chats/{chat_id}").json()["messages"][0]["body"], "private")

    def test_search_only_looks_in_ones_own_conversations(self):
        chat_ab = self.start("a", "b")
        self.say("a", chat_ab, "the quarterly budget is ready")
        self.as_("b")
        self.assertEqual(len(self.client.get("/api/messages/search", params={"q": "budget"}).json()["results"]), 1)
        self.as_("c")
        self.assertEqual(self.client.get("/api/messages/search", params={"q": "budget"}).json()["results"], [])
        self.assertEqual(self.client.get("/api/messages/search", params={"q": "budget", "chat_id": chat_ab}).status_code, 404)

    def test_search_treats_percent_and_underscore_as_ordinary_characters(self):
        chat_id = self.start("a", "b")
        self.say("a", chat_id, "plain words")
        self.say("a", chat_id, "50% off")
        self.as_("a")
        found = self.client.get("/api/messages/search", params={"q": "%%"}).json()["results"]
        self.assertEqual([r["snippet"] for r in found], [])
        found = self.client.get("/api/messages/search", params={"q": "50%"}).json()["results"]
        self.assertEqual([r["snippet"] for r in found], ["50% off"])

    # -- history ------------------------------------------------------------------------------------------------------

    def test_history_is_paged_newest_first_and_older_pages_join_up(self):
        chat_id = self.start("a", "b")
        for n in range(45):
            self.say("a", chat_id, f"m{n}")
        self.as_("a")
        thread = self.client.get(f"/api/messages/chats/{chat_id}").json()
        self.assertEqual(len(thread["messages"]), 40)
        self.assertTrue(thread["has_more"])
        self.assertEqual(thread["messages"][-1]["body"], "m44")
        oldest = thread["messages"][0]["id"]
        older = self.client.get(f"/api/messages/chats/{chat_id}/messages", params={"before": oldest}).json()
        self.assertEqual([m["body"] for m in older["messages"]], [f"m{n}" for n in range(5)])
        self.assertFalse(older["has_more"])

    def test_the_stretch_around_a_message_can_be_loaded(self):
        chat_id = self.start("a", "b")
        ids = [self.say("a", chat_id, f"m{n}")["id"] for n in range(60)]
        self.as_("b")
        around = self.client.get(f"/api/messages/chats/{chat_id}/messages", params={"around": ids[30]}).json()
        bodies = [m["body"] for m in around["messages"]]
        self.assertIn("m30", bodies)
        self.assertTrue(around["has_more"])
        self.assertFalse(around["reaches_latest"])

    # -- sending ------------------------------------------------------------------------------------------------------

    def test_the_same_send_arriving_twice_is_one_message(self):
        chat_id = self.start("a", "b")
        first = self.say("a", chat_id, "once", client_id="abc-123")
        second = self.say("a", chat_id, "once", client_id="abc-123")
        self.assertEqual(first["id"], second["id"])
        self.as_("a")
        self.assertEqual(len(self.client.get(f"/api/messages/chats/{chat_id}").json()["messages"]), 1)

    def test_a_reply_must_be_to_a_message_in_the_same_conversation(self):
        chat_ab = self.start("a", "b")
        chat_ac = self.start("a", "c")
        mine = self.say("a", chat_ab, "question")
        other = self.say("a", chat_ac, "elsewhere")
        reply = self.say("b", chat_ab, "answer", reply_to=mine["id"])
        self.assertEqual(reply["reply_to"]["id"], mine["id"])
        self.assertEqual(reply["reply_to"]["body"], "question")
        self.as_("b")
        bad = self.client.post(f"/api/messages/chats/{chat_ab}/messages", json={"body": "x", "reply_to": other["id"]})
        self.assertEqual(bad.status_code, 400)

    def test_an_empty_message_is_refused(self):
        chat_id = self.start("a", "b")
        self.as_("a")
        self.assertEqual(self.client.post(f"/api/messages/chats/{chat_id}/messages", json={"body": "   "}).status_code, 400)
        self.assertEqual(self.client.post(f"/api/messages/chats/{chat_id}/messages", json={"body": "x" * 4001}).status_code, 400)

    def test_sending_too_fast_is_slowed_down(self):
        chat_id = self.start("a", "b")
        self.as_("a")
        codes = [self.client.post(f"/api/messages/chats/{chat_id}/messages", json={"body": f"m{n}"}).status_code for n in range(45)]
        self.assertEqual(codes.count(200), 40)
        self.assertEqual(codes[-1], 429)

    # -- edit and delete ----------------------------------------------------------------------------------------------

    def test_only_the_sender_can_edit_or_delete(self):
        chat_id = self.start("a", "b")
        message = self.say("a", chat_id, "first draft")
        self.as_("b")
        self.assertEqual(self.client.patch(f"/api/messages/{message['id']}", json={"body": "hijack"}).status_code, 403)
        self.assertEqual(self.client.delete(f"/api/messages/{message['id']}").status_code, 403)
        self.as_("a")
        edited = self.client.patch(f"/api/messages/{message['id']}", json={"body": "second draft"})
        self.assertEqual(edited.status_code, 200)
        self.assertEqual(edited.json()["body"], "second draft")
        self.assertIsNotNone(edited.json()["edited_timestamp"])
        self.assertEqual(self.client.patch(f"/api/messages/{message['id']}", json={"body": "  "}).status_code, 400)

    def test_deleting_leaves_a_marker_and_blanks_what_replies_quote(self):
        chat_id = self.start("a", "b")
        original = self.say("a", chat_id, "secret figure 12345")
        reply = self.say("b", chat_id, "ok", reply_to=original["id"])
        self.as_("a")
        gone = self.client.delete(f"/api/messages/{original['id']}").json()
        self.assertTrue(gone["deleted"])
        self.assertEqual(gone["body"], "")
        thread = self.client.get(f"/api/messages/chats/{chat_id}").json()
        by_id = {m["id"]: m for m in thread["messages"]}
        self.assertTrue(by_id[original["id"]]["deleted"])
        self.assertTrue(by_id[reply["id"]]["reply_to"]["deleted"])
        self.assertNotIn("12345", str(thread))
        self.assertEqual(self.client.patch(f"/api/messages/{original['id']}", json={"body": "back"}).status_code, 400)

    def test_a_deleted_message_is_not_unread_and_not_searchable(self):
        chat_id = self.start("a", "b")
        message = self.say("a", chat_id, "findable words")
        self.as_("a")
        self.client.delete(f"/api/messages/{message['id']}")
        self.as_("b")
        self.assertEqual(self.client.get("/api/messages/unread").json()["count"], 0)
        self.assertEqual(self.client.get("/api/messages/search", params={"q": "findable"}).json()["results"], [])

    # -- reactions, pins, settings ----------------------------------------------------------------------------------

    def test_reactions_toggle_and_are_validated(self):
        chat_id = self.start("a", "b")
        message = self.say("a", chat_id, "nice")
        self.as_("b")
        first = self.client.put(f"/api/messages/{message['id']}/reactions", json={"emoji": "👍"}).json()
        self.assertEqual(first["reactions"], [{"emoji": "👍", "user_ids": [self.ids["b"]]}])
        self.as_("a")
        both = self.client.put(f"/api/messages/{message['id']}/reactions", json={"emoji": "👍"}).json()
        self.assertEqual(both["reactions"][0]["user_ids"], [self.ids["b"], self.ids["a"]])
        self.as_("b")
        off = self.client.put(f"/api/messages/{message['id']}/reactions", json={"emoji": "👍"}).json()
        self.assertEqual(off["reactions"][0]["user_ids"], [self.ids["a"]])
        self.assertEqual(self.client.put(f"/api/messages/{message['id']}/reactions", json={"emoji": "hello"}).status_code, 400)
        self.assertEqual(self.client.put(f"/api/messages/{message['id']}/reactions", json={"emoji": "👍 👍"}).status_code, 400)

    def test_pinning_is_limited_and_only_for_live_messages(self):
        chat_id = self.start("a", "b")
        ids = [self.say("a", chat_id, f"p{n}")["id"] for n in range(chat.MAX_PINS + 1)]
        self.as_("b")
        for message_id in ids[: chat.MAX_PINS]:
            self.assertEqual(self.client.put(f"/api/messages/chats/{chat_id}/pins/{message_id}").status_code, 200)
        self.assertEqual(self.client.put(f"/api/messages/chats/{chat_id}/pins/{ids[-1]}").status_code, 400)
        self.assertEqual(len(self.client.get(f"/api/messages/chats/{chat_id}").json()["pins"]), chat.MAX_PINS)
        self.assertEqual(self.client.delete(f"/api/messages/chats/{chat_id}/pins/{ids[0]}").status_code, 200)

    def test_muting_keeps_a_conversation_out_of_the_badge_and_a_new_message_unarchives(self):
        chat_id = self.start("a", "b")
        self.say("a", chat_id, "hello")
        self.as_("b")
        self.assertEqual(self.client.get("/api/messages/unread").json()["count"], 1)
        self.client.patch(f"/api/messages/chats/{chat_id}/settings", json={"muted": True, "archived": True})
        self.assertEqual(self.client.get("/api/messages/unread").json()["count"], 0)
        row = next(c for c in self.client.get("/api/messages/chats").json() if c["id"] == chat_id)
        self.assertEqual(row["unread"], 1)
        self.assertEqual(row["settings"], {"pinned": False, "muted": True, "archived": True})
        self.say("a", chat_id, "again")
        self.as_("b")
        row = next(c for c in self.client.get("/api/messages/chats").json() if c["id"] == chat_id)
        self.assertFalse(row["settings"]["archived"])
        self.assertTrue(row["settings"]["muted"])

    def test_settings_are_each_persons_own(self):
        chat_id = self.start("a", "b")
        self.say("a", chat_id, "hello")
        self.as_("a")
        self.client.patch(f"/api/messages/chats/{chat_id}/settings", json={"pinned": True})
        self.as_("b")
        row = next(c for c in self.client.get("/api/messages/chats").json() if c["id"] == chat_id)
        self.assertFalse(row["settings"]["pinned"])

    # -- read state --------------------------------------------------------------------------------------------------

    def test_the_sender_can_see_how_far_the_other_person_has_read(self):
        chat_id = self.start("a", "b")
        first = self.say("a", chat_id, "one")
        self.as_("a")
        self.assertEqual(self.client.get(f"/api/messages/chats/{chat_id}").json()["peer_last_read_id"], 0)
        self.as_("b")
        self.client.post(f"/api/messages/chats/{chat_id}/read")
        self.as_("a")
        self.assertEqual(self.client.get(f"/api/messages/chats/{chat_id}").json()["peer_last_read_id"], first["id"])

    # -- forwarding and files -------------------------------------------------------------------------------------

    def test_forwarding_copies_the_message_and_its_file_into_another_conversation(self):
        chat_ab = self.start("a", "b")
        chat_ac = self.start("a", "c")
        self.as_("a")
        sent = self.client.post(
            f"/api/messages/chats/{chat_ab}/messages", data={"body": "the file"}, files={"file": ("notes.txt", b"contents", "text/plain")}
        ).json()
        self.assertEqual(sent["media_kind"], "file")
        forwarded = self.client.post(f"/api/messages/{sent['id']}/forward", json={"chat_id": chat_ac})
        self.assertEqual(forwarded.status_code, 200, forwarded.text)
        copy = forwarded.json()
        self.assertTrue(copy["forwarded"])
        self.assertEqual(copy["media_name"], "notes.txt")
        self.assertNotEqual(copy["id"], sent["id"])
        self.as_("c")
        self.assertEqual(self.client.get(copy["media_url"].replace("/api", "/api")).content, b"contents")
        self.as_("b")
        self.assertEqual(self.client.get(copy["media_url"]).status_code, 404)
        self.as_("c")
        self.assertEqual(self.client.post(f"/api/messages/{sent['id']}/forward", json={"chat_id": chat_ac}).status_code, 404)

    def test_a_deleted_message_cannot_be_forwarded_and_its_file_is_gone(self):
        chat_ab = self.start("a", "b")
        self.as_("a")
        sent = self.client.post(
            f"/api/messages/chats/{chat_ab}/messages", data={"body": ""}, files={"file": ("a.txt", b"x", "text/plain")}
        ).json()
        self.client.delete(f"/api/messages/{sent['id']}")
        self.assertEqual(self.client.get(f"/api/messages/media/{sent['id']}").status_code, 404)
        self.assertEqual(self.client.post(f"/api/messages/{sent['id']}/forward", json={"chat_id": chat_ab}).status_code, 400)

    def test_shared_media_lists_files_for_members_only(self):
        chat_ab = self.start("a", "b")
        self.as_("a")
        self.client.post(f"/api/messages/chats/{chat_ab}/messages", data={"body": ""}, files={"file": ("a.pdf", b"%PDF-1.4", "application/pdf")})
        listed = self.client.get(f"/api/messages/chats/{chat_ab}/media").json()["items"]
        self.assertEqual([i["name"] for i in listed], ["a.pdf"])
        self.as_("c")
        self.assertEqual(self.client.get(f"/api/messages/chats/{chat_ab}/media").status_code, 404)


    # -- live events -------------------------------------------------------------------------------------------------
    #
    # Two test sockets only reach each other when they share one event loop, as they do under the real server. A client used as
    # a context manager keeps one loop for everything it does, so these tests use that on an app that has only the messages
    # router (no startup work).

    def _live(self):
        from fastapi import FastAPI

        from app.routers import messages_router

        mini = FastAPI()
        mini.include_router(messages_router.router, prefix="/api")
        mini.dependency_overrides[dependencies.get_current_user] = lambda: auth.fetch_user_by_id(type(self).current["id"])
        return TestClient(mini)

    def _socket(self, client, who: str):
        from app.config import SESSION_COOKIE_NAME

        token = sessions.create_session(self.ids[who])
        return client.websocket_connect("/api/messages/ws", headers={"cookie": f"{SESSION_COOKIE_NAME}={token}"})

    def _drain(self, ws, wanted: str, limit: int = 12):
        for _ in range(limit):
            event = ws.receive_json()
            if event.get("type") == wanted:
                return event
        self.fail(f"never received a {wanted} event")

    def test_typing_read_and_new_messages_reach_the_other_person_live(self):
        chat_id = self.start("a", "b")
        with self._live() as client, self._socket(client, "a") as ws_a, self._socket(client, "b") as ws_b:
            ws_a.send_json({"type": "typing", "chat_id": chat_id})
            typing = self._drain(ws_b, "typing")
            self.assertEqual((typing["chat_id"], typing["user_id"]), (chat_id, self.ids["a"]))

            ws_a.send_json({"type": "send", "chat_id": chat_id, "body": "live hello", "client_id": "live-1"})
            arrived = self._drain(ws_b, "message")
            self.assertEqual(arrived["message"]["body"], "live hello")
            self.assertEqual(arrived["message"]["client_id"], "live-1")
            self.assertFalse(arrived["muted"])

            ws_b.send_json({"type": "read", "chat_id": chat_id})
            read = self._drain(ws_a, "read")
            self.assertEqual(read["user_id"], self.ids["b"])
            self.assertEqual(read["last_read_id"], arrived["message"]["id"])

    def test_a_reaction_and_an_edit_reach_both_people_live(self):
        chat_id = self.start("a", "b")
        message = self.say("a", chat_id, "first")
        with self._live() as client, self._socket(client, "a") as ws_a, self._socket(client, "b") as ws_b:
            self.as_("b")
            client.put(f"/api/messages/{message['id']}/reactions", json={"emoji": "👍"})
            event = self._drain(ws_a, "reactions")
            self.assertEqual(event["reactions"], [{"emoji": "👍", "user_ids": [self.ids["b"]]}])
            self.as_("a")
            client.patch(f"/api/messages/{message['id']}", json={"body": "second"})
            updated = self._drain(ws_b, "message_updated")
            self.assertEqual(updated["message"]["body"], "second")
            self.assertIsNotNone(updated["message"]["edited_timestamp"])

    def test_a_muted_conversation_says_so_in_the_event_so_the_browser_stays_quiet(self):
        chat_id = self.start("a", "b")
        self.as_("b")
        self.client.patch(f"/api/messages/chats/{chat_id}/settings", json={"muted": True})
        with self._live() as client, self._socket(client, "b") as ws_b:
            self.as_("a")
            client.post(f"/api/messages/chats/{chat_id}/messages", json={"body": "psst"})
            self.assertTrue(self._drain(ws_b, "message")["muted"])

    def test_a_person_cannot_use_someone_elses_conversation_over_the_socket(self):
        chat_id = self.start("a", "b")
        with self._live() as client, self._socket(client, "c") as ws_c:
            ws_c.send_json({"type": "send", "chat_id": chat_id, "body": "intruder"})
            error = self._drain(ws_c, "error")
            self.assertEqual(error["chat_id"], chat_id)
            ws_c.send_json({"type": "typing", "chat_id": chat_id})
            self.assertEqual(self._drain(ws_c, "error")["chat_id"], chat_id)
        self.as_("a")
        self.assertEqual(self.client.get(f"/api/messages/chats/{chat_id}").json()["messages"], [])


    # -- calls and voice notes -----------------------------------------------------------------------------------------

    def test_a_call_leaves_one_line_that_cannot_be_edited_deleted_or_forwarded(self):
        from app import calls

        chat_id = self.start("a", "b")
        call_id = calls._create(chat_id, self.ids["a"], self.ids["b"], "video")
        calls._answered(call_id)
        calls._close(call_id, "ended")
        line = chat.add_call_message(chat_id, self.ids["a"], call_id, seen_by_other=True)
        self.assertEqual((line["call"]["kind"], line["call"]["outcome"], line["call"]["caller_id"]), ("video", "ended", self.ids["a"]))
        self.assertEqual(line["body"], "")
        # an answered call is not unread for the other person; a missed one is
        self.as_("b")
        self.assertEqual(self.client.get("/api/messages/unread").json()["count"], 0)
        missed = calls._create(chat_id, self.ids["a"], self.ids["b"], "voice")
        calls._close(missed, "missed")
        chat.add_call_message(chat_id, self.ids["a"], missed, seen_by_other=False)
        self.assertEqual(self.client.get("/api/messages/unread").json()["count"], 1)
        # nobody can change what happened
        self.as_("a")
        self.assertEqual(self.client.patch(f"/api/messages/{line['id']}", json={"body": "x"}).status_code, 400)
        self.assertEqual(self.client.delete(f"/api/messages/{line['id']}").status_code, 400)
        self.assertEqual(self.client.post(f"/api/messages/{line['id']}/forward", json={"chat_id": chat_id}).status_code, 400)
        listed = self.client.get(f"/api/messages/chats/{chat_id}").json()["messages"]
        self.assertEqual([m["call"]["outcome"] for m in listed if m.get("call")], ["ended", "missed"])

    def test_a_voice_note_is_kept_with_its_length_and_loudness_and_served_as_audio(self):
        chat_id = self.start("a", "b")
        chat.limits.reset()
        response = self.client.post(
            f"/api/messages/chats/{chat_id}/messages",
            data={"body": "", "duration_ms": "4200", "waveform": "5,40,100,20"},
            files={"file": ("voice-note.webm", b"webm data, not really audio", "audio/webm")},
        )
        self.assertEqual(response.status_code, 200, response.text)
        note = response.json()
        self.assertEqual((note["media_kind"], note["media_duration_ms"], note["media_waveform"]), ("audio", 4200, [5, 40, 100, 20]))
        self.as_("b")
        served = self.client.get(note["media_url"])
        self.assertEqual(served.status_code, 200)
        self.assertEqual(served.headers["content-type"], "audio/webm")
        self.assertIn("inline", served.headers["content-disposition"])
        self.assertEqual(served.headers["x-content-type-options"], "nosniff")
        self.assertEqual([i["message_id"] for i in self.client.get(f"/api/messages/chats/{chat_id}/media?kind=audio").json()["items"]], [note["id"]])
        # a loudness picture that is not numbers is dropped, never stored
        self.as_("a")
        chat.limits.reset()
        odd = self.client.post(
            f"/api/messages/chats/{chat_id}/messages",
            data={"body": "", "duration_ms": "1000", "waveform": "<b>x</b>"},
            files={"file": ("voice-note.ogg", b"OggS data", "audio/ogg")},
        ).json()
        self.assertEqual(odd["media_waveform"], [])
        # audio is recognised by what the browser says it is: an audio name on a file that says it is something else is refused
        refused = self.client.post(
            f"/api/messages/chats/{chat_id}/messages", data={"body": ""}, files={"file": ("x.exe", b"MZ", "audio/mpeg")}
        )
        self.assertEqual(refused.status_code, 400)


    # -- group chats ---------------------------------------------------------------------------------------------------

    def make_group(self, who: str, title: str, members: list[str]) -> dict:
        self.as_(who)
        chat.limits.reset()
        response = self.client.post("/api/messages/groups", json={"title": title, "user_ids": [self.ids[m] for m in members]})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def summary(self, who: str, chat_id: int) -> dict:
        self.as_(who)
        response = self.client.get(f"/api/messages/chats/{chat_id}")
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_a_group_has_its_creator_as_admin_a_line_for_its_start_and_nothing_unread(self):
        group = self.make_group("a", "  Site   leads ", ["b", "c"])
        self.assertEqual((group["kind"], group["title"], group["my_role"]), ("group", "Site leads", "admin"))
        self.assertEqual(sorted(m["display_name"] for m in group["members"]), ["Chat A", "Chat B", "Chat C"])
        self.assertEqual({m["group_role"] for m in group["members"] if m["id"] != self.ids["a"]}, {"member"})
        self.assertTrue(group["last_message"]["system"])
        self.assertIn("created the group", group["last_message"]["body"])
        for who in ("a", "b", "c"):
            self.as_(who)
            self.assertEqual(self.client.get("/api/messages/unread").json()["count"], 0, who)

    def test_what_is_said_in_a_group_reaches_everybody_in_it_and_counts_for_each(self):
        group = self.make_group("a", "Team", ["b", "c"])
        message = self.say("a", group["id"], "hello all")
        self.assertEqual(message["sender_name"], "Chat A")
        self.assertNotIn("other_ids", message)  # the answer to the sender does not carry the fan-out list
        for who in ("b", "c"):
            self.as_(who)
            self.assertEqual(self.client.get("/api/messages/unread").json()["count"], 1, who)
            chats = self.client.get("/api/messages/chats").json()
            self.assertEqual([c["id"] for c in chats], [group["id"]])
            self.assertEqual(chats[0]["unread"], 1)
        # reading it takes it off that person's count only
        self.as_("b")
        self.client.post(f"/api/messages/chats/{group['id']}/read")
        self.assertEqual(self.client.get("/api/messages/unread").json()["count"], 0)
        self.as_("c")
        self.assertEqual(self.client.get("/api/messages/unread").json()["count"], 1)
        # the sender sees it as read only when everybody has
        self.assertLess(self.summary("a", group["id"])["peer_last_read_id"], message["id"])  # c has not read it yet
        self.as_("c")
        self.client.post(f"/api/messages/chats/{group['id']}/read")
        a_view = self.summary("a", group["id"])
        self.assertEqual(a_view["peer_last_read_id"], a_view["messages"][-1]["id"])

    def test_somebody_outside_a_group_can_do_nothing_in_it(self):
        group = self.make_group("a", "Private", ["b"])
        message = self.say("a", group["id"], "not for you")
        self.as_("c")
        for method, path, kwargs in [
            ("get", f"/api/messages/chats/{group['id']}", {}),
            ("get", f"/api/messages/chats/{group['id']}/messages", {}),
            ("post", f"/api/messages/chats/{group['id']}/messages", {"json": {"body": "hi"}}),
            ("post", f"/api/messages/chats/{group['id']}/read", {}),
            ("put", f"/api/messages/{message['id']}/reactions", {"json": {"emoji": "👍"}}),
            ("delete", f"/api/messages/chats/{group['id']}", {}),
            ("patch", f"/api/messages/groups/{group['id']}", {"json": {"title": "x"}}),
            ("post", f"/api/messages/groups/{group['id']}/members", {"json": {"user_ids": [self.ids["c"]]}}),
            ("delete", f"/api/messages/groups/{group['id']}/members/{self.ids['b']}", {}),
            ("post", f"/api/messages/{message['id']}/forward", {"json": {"chat_id": group["id"]}}),
        ]:
            with self.subTest(route=f"{method} {path}"):
                response = getattr(self.client, method)(path, **kwargs)
                self.assertEqual(response.status_code, 404, response.text)
        found = self.client.get("/api/messages/search", params={"q": "not for you"}).json()["results"]
        self.assertEqual(found, [])
        self.assertEqual(self.client.get("/api/messages/chats").json(), [])

    def test_only_an_admin_runs_a_group_and_a_member_can_leave(self):
        group = self.make_group("a", "Rules", ["b"])
        self.as_("b")
        for method, path, kwargs in [
            ("patch", f"/api/messages/groups/{group['id']}", {"json": {"title": "Mine now"}}),
            ("post", f"/api/messages/groups/{group['id']}/members", {"json": {"user_ids": [self.ids["c"]]}}),
            ("delete", f"/api/messages/groups/{group['id']}/members/{self.ids['a']}", {}),
            ("put", f"/api/messages/groups/{group['id']}/members/{self.ids['b']}/role", {"json": {"role": "admin"}}),
            ("delete", f"/api/messages/chats/{group['id']}", {}),
        ]:
            with self.subTest(route=f"{method} {path}"):
                self.assertEqual(getattr(self.client, method)(path, **kwargs).status_code, 403)
        # an admin can
        self.as_("a")
        self.assertEqual(self.client.patch(f"/api/messages/groups/{group['id']}", json={"title": "Renamed"}).json()["title"], "Renamed")
        added = self.client.post(f"/api/messages/groups/{group['id']}/members", json={"user_ids": [self.ids["c"], self.ids["b"]]})
        self.assertEqual(added.status_code, 200, added.text)
        self.assertEqual(len(added.json()["members"]), 3)
        self.assertEqual(self.client.post(f"/api/messages/groups/{group['id']}/members", json={"user_ids": [self.ids["c"]]}).status_code, 400)  # all in already
        # a person who is added sees what was said before, and is not told it is unread
        self.say("a", group["id"], "history")
        self.as_("c")
        self.assertEqual([m["body"] for m in self.client.get(f"/api/messages/chats/{group['id']}").json()["messages"] if not m["system"]], ["history"])
        # anybody can leave, and then has nothing to read
        left = self.client.delete(f"/api/messages/groups/{group['id']}/members/{self.ids['c']}")
        self.assertEqual(left.status_code, 200, left.text)
        self.assertEqual(self.client.get(f"/api/messages/chats/{group['id']}").status_code, 404)
        self.assertEqual(self.client.get("/api/messages/chats").json(), [])
        self.as_("a")
        lines = [m["body"] for m in self.client.get(f"/api/messages/chats/{group['id']}").json()["messages"] if m["system"]]
        self.assertTrue(any(line.endswith("Chat C left") for line in lines), lines)
        # an admin removes somebody
        self.as_("a")
        self.assertEqual(self.client.delete(f"/api/messages/groups/{group['id']}/members/{self.ids['b']}").status_code, 200)
        self.as_("b")
        self.assertEqual(self.client.get(f"/api/messages/chats/{group['id']}/messages").status_code, 404)

    def test_a_group_always_has_an_admin_and_goes_with_its_last_person(self):
        group = self.make_group("a", "Handover", ["b", "c"])
        self.as_("a")
        # the only admin cannot be made an ordinary member
        self.assertEqual(self.client.put(f"/api/messages/groups/{group['id']}/members/{self.ids['a']}/role", json={"role": "member"}).status_code, 400)
        # leaving as the only admin hands the group to whoever has been in it longest
        self.assertEqual(self.client.delete(f"/api/messages/groups/{group['id']}/members/{self.ids['a']}").status_code, 200)
        view = self.summary("b", group["id"])
        roles = {m["id"]: m["group_role"] for m in view["members"]}
        self.assertEqual(roles, {self.ids["b"]: "admin", self.ids["c"]: "member"})
        self.assertEqual(view["my_role"], "admin")
        # an admin makes another admin, and the last two can leave one after another
        self.as_("b")
        self.assertEqual(self.client.put(f"/api/messages/groups/{group['id']}/members/{self.ids['c']}/role", json={"role": "admin"}).status_code, 200)
        self.assertEqual(self.client.delete(f"/api/messages/groups/{group['id']}/members/{self.ids['b']}").status_code, 200)
        self.as_("c")
        last = self.client.delete(f"/api/messages/groups/{group['id']}/members/{self.ids['c']}")
        self.assertEqual((last.status_code, last.json()["deleted"]), (200, True))
        with db_cursor() as cur:
            cur.execute("select count(*) from orion_ods.direct_chat where id = %s", (group["id"],))
            self.assertEqual(cur.fetchone()[0], 0)

    def test_a_group_is_made_with_real_people_a_name_and_a_limit(self):
        self.as_("a")
        chat.limits.reset()
        post = lambda body: self.client.post("/api/messages/groups", json=body)  # noqa: E731
        self.assertEqual(post({"title": "   ", "user_ids": [self.ids["b"]]}).status_code, 400)
        self.assertEqual(post({"title": "x" * 61, "user_ids": [self.ids["b"]]}).status_code, 400)
        self.assertEqual(post({"title": "Alone", "user_ids": []}).status_code, 400)
        self.assertEqual(post({"title": "Alone", "user_ids": [self.ids["a"]]}).status_code, 400)  # only yourself
        self.assertEqual(post({"title": "Ghosts", "user_ids": [self.ids["b"], 987654321]}).status_code, 400)
        again = post({"title": "Same people", "user_ids": [self.ids["b"], self.ids["b"]]})
        self.assertEqual(len(again.json()["members"]), 2)  # a repeated person is one person

    def test_a_line_nobody_wrote_cannot_be_changed_reacted_to_pinned_or_forwarded(self):
        group = self.make_group("a", "Records", ["b"])
        line = group["last_message"]
        self.as_("a")
        other = self.start("a", "c")
        for method, path, kwargs in [
            ("patch", f"/api/messages/{line['id']}", {"json": {"body": "x"}}),
            ("delete", f"/api/messages/{line['id']}", {}),
            ("put", f"/api/messages/{line['id']}/reactions", {"json": {"emoji": "👍"}}),
            ("put", f"/api/messages/chats/{group['id']}/pins/{line['id']}", {}),
            ("post", f"/api/messages/{line['id']}/forward", {"json": {"chat_id": other}}),
        ]:
            with self.subTest(route=f"{method} {path}"):
                self.assertEqual(getattr(self.client, method)(path, **kwargs).status_code, 400)

    def test_calls_and_ai_help_are_for_one_to_one_conversations_only(self):
        group = self.make_group("a", "No calls", ["b"])
        self.as_("a")
        self.assertEqual(self.client.post(f"/api/messages/chats/{group['id']}/assist", json={"action": "summarize"}).status_code, 400)
        from app import calls

        with self.assertRaises(chat.ChatError):
            chat._direct_peer(group["id"], self.ids["a"])
        self.assertTrue(calls.CALL_KINDS)

    def test_messages_in_a_group_can_be_edited_reacted_to_pinned_and_found_by_its_members_only(self):
        group = self.make_group("a", "Everything", ["b", "c"])
        said = self.say("b", group["id"], "quarterly numbers ready")
        self.as_("c")
        reacted = self.client.put(f"/api/messages/{said['id']}/reactions", json={"emoji": "👍"})
        self.assertEqual(reacted.status_code, 200, reacted.text)
        self.assertEqual(self.client.put(f"/api/messages/chats/{group['id']}/pins/{said['id']}").status_code, 200)
        self.assertEqual([r["chat_id"] for r in self.client.get("/api/messages/search", params={"q": "quarterly"}).json()["results"]], [group["id"]])
        self.as_("b")
        self.assertEqual(self.client.patch(f"/api/messages/{said['id']}", json={"body": "quarterly numbers are ready"}).status_code, 200)
        self.as_("c")
        # somebody else's message cannot be edited, but a group is deleted only by an admin
        self.assertEqual(self.client.patch(f"/api/messages/{said['id']}", json={"body": "mine"}).status_code, 403)
        self.assertEqual(self.client.delete(f"/api/messages/chats/{group['id']}").status_code, 403)
        self.as_("a")
        self.assertEqual(self.client.delete(f"/api/messages/chats/{group['id']}").status_code, 200)
        self.as_("b")
        self.assertEqual(self.client.get(f"/api/messages/chats/{group['id']}").status_code, 404)


    def test_a_group_message_typing_and_changes_reach_every_member_live_and_nobody_else(self):
        group = self.make_group("a", "Live", ["b", "c"])
        outsider = self.ids["c"]
        self.assertTrue(outsider)
        with self._live() as client, self._socket(client, "a") as ws_a, self._socket(client, "b") as ws_b, self._socket(client, "c") as ws_c:
            ws_a.send_json({"type": "send", "chat_id": group["id"], "body": "to all", "client_id": "grp-1"})
            for ws in (ws_a, ws_b, ws_c):
                got = self._drain(ws, "message")
                self.assertEqual((got["message"]["body"], got["message"]["sender_name"]), ("to all", "Chat A"))
            ws_b.send_json({"type": "typing", "chat_id": group["id"]})
            for ws in (ws_a, ws_c):
                self.assertEqual(self._drain(ws, "typing")["user_id"], self.ids["b"])
            # b leaves: everybody left is told something changed, b is told the conversation is gone, and b hears nothing more
            self.as_("b")
            self.assertEqual(client.delete(f"/api/messages/groups/{group['id']}/members/{self.ids['b']}").status_code, 200)
            self.assertEqual(self._drain(ws_b, "chat_deleted")["chat_id"], group["id"])
            for ws in (ws_a, ws_c):
                self.assertEqual(self._drain(ws, "chat_changed")["chat_id"], group["id"])
            self.as_("a")
            client.post(f"/api/messages/chats/{group['id']}/messages", json={"body": "after b left", "client_id": "grp-2"})
            self.assertEqual(self._drain(ws_c, "message")["message"]["body"], "after b left")
            ws_b.send_json({"type": "ping"})
            seen = []
            for _ in range(6):
                event = ws_b.receive_json()
                seen.append(event.get("type"))
                if event.get("type") == "pong":
                    break
            self.assertNotIn("message", seen)


if __name__ == "__main__":
    unittest.main()
