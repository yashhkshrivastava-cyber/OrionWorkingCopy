"""A file attached to a chat message reaches the server, and a message with no text is still a message.

The router once checked the upload against FastAPI's ``UploadFile``, but a form hands back Starlette's, so the file was
dropped without a word and the server answered "Type a message or attach a file." to a message that had one. These tests send
a real multipart request through the router and look at what it hands to ``send_message``.
"""

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import dependencies  # noqa: E402
from app.routers import messages_router  # noqa: E402


class AttachedFiles(unittest.TestCase):
    def setUp(self):
        app = FastAPI()
        app.include_router(messages_router.router)
        app.dependency_overrides[dependencies.get_current_user] = lambda: {"id": 7, "username": "t"}
        self.client = TestClient(app)
        self.sent = []

        def fake_send(chat_id, sender_id, body, media=None, **_options):
            self.sent.append({"body": body, "media": media})
            return {"id": 1, "chat_id": chat_id, "sender_id": sender_id, "body": body, "media_kind": media["kind"] if media else None}

        patches = [
            mock.patch.object(messages_router.chat, "send_message", fake_send),
            mock.patch.object(messages_router, "_fanout", mock.AsyncMock()),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def post(self, **kwargs):
        return self.client.post("/messages/chats/3/messages", **kwargs)

    def test_a_file_with_no_text_is_sent_with_the_file(self):
        response = self.post(data={"body": ""}, files={"file": ("notes.txt", b"hello", "text/plain")})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(self.sent), 1)
        media = self.sent[0]["media"]
        self.assertIsNotNone(media, "the attachment was dropped")
        self.assertEqual(media["original_name"], "notes.txt")
        self.assertEqual(media["data"], b"hello")

    def test_a_file_with_text_is_sent_with_both(self):
        response = self.post(data={"body": "see this"}, files={"file": ("notes.txt", b"hello", "text/plain")})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.sent[0]["body"], "see this")
        self.assertIsNotNone(self.sent[0]["media"])

    def test_plain_text_still_works_as_json(self):
        response = self.post(json={"body": "hello"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.sent[0], {"body": "hello", "media": None})

    def test_an_empty_file_is_refused_with_a_clear_message(self):
        response = self.post(data={"body": ""}, files={"file": ("empty.txt", b"", "text/plain")})
        self.assertEqual(response.status_code, 400)
        self.assertIn("Choose a file", response.json()["detail"])


if __name__ == "__main__":
    unittest.main()
