"""The AI help endpoints of the screens: who may call them, and what a bad request gets back.

A real request goes through each router with the person's permissions set in the user record. The model is never reached:
what is asked of it is covered by test_ai_assist.py.
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
from app.routers import billing_router, documents_router, entities_router, etl_router, letterhead_router  # noqa: E402

# Nothing the person has been given: every flag off, so a route that forgot its permission check would let them in.
NOTHING = {
    "id": 7, "username": "t", "role": "viewer", "ods_write": False, "billing_write": False, "billing_access": False,
    "letterhead_write": False, "letterhead_access": False, "documents_write": False, "documents_access": False,
    "etl_access": False, "etl_write": False,
}


class Routes(unittest.TestCase):
    def client(self, router, **flags):
        app = FastAPI()
        app.include_router(router)
        user = {**NOTHING, **flags}
        app.dependency_overrides[dependencies.get_current_user] = lambda: user
        return TestClient(app)

    def test_every_ai_endpoint_refuses_a_person_without_the_matching_permission(self):
        calls = [
            (letterhead_router.router, "post", "/letterhead/ai", {"json": {"mode": "draft", "brief": "renew the contract"}}),
            (billing_router.router, "post", "/billing/receivables/C1/reminder/ai", {"json": {"tone": "polite"}}),
            (entities_router.router, "post", "/entities/Client/ai/fill", {"json": {"text": "a message about a new client"}}),
            (etl_router.router, "post", "/etl/runs/1/explain", {"json": {}}),
            (documents_router.router, "post", "/documents/ai/suggest", {"data": {"scope": "client"}, "files": {"file": ("a.txt", b"x", "text/plain")}}),
        ]
        for router, method, path, kwargs in calls:
            with self.subTest(path=path):
                response = getattr(self.client(router), method)(path, **kwargs)
                self.assertEqual(response.status_code, 403, response.text)

    def test_a_letter_request_with_nothing_to_go_on_is_a_plain_400(self):
        client = self.client(letterhead_router.router, letterhead_write=True)
        response = client.post("/letterhead/ai", json={"mode": "draft", "brief": "hi"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("what the letter is about", response.json()["detail"])

    def test_an_unknown_mode_or_tone_is_not_a_server_error(self):
        client = self.client(letterhead_router.router, letterhead_write=True)
        self.assertEqual(client.post("/letterhead/ai", json={"mode": "mystery"}).status_code, 400)

    def test_a_letter_answer_passes_through_as_html(self):
        client = self.client(letterhead_router.router, letterhead_write=True)
        answer = {"status": "ok", "where": "local", "provider": "fake", "text": "We wish to renew.", "data": None}
        with mock.patch("app.ai.features.assist.run", return_value=answer):
            response = client.post("/letterhead/ai", json={"mode": "draft", "brief": "renew the contract for a year"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["html"], "<p>We wish to renew.</p>")

    def test_a_reminder_for_a_client_with_nothing_due_is_a_404_and_a_bad_tone_a_400(self):
        client = self.client(billing_router.router, billing_write=True)
        with mock.patch.object(billing_router.receivables, "client_statement", return_value=None):
            self.assertEqual(client.post("/billing/receivables/C1/reminder/ai", json={"tone": "polite"}).status_code, 404)
        statement = {"client_name": "A", "as_of": "2026-10-10", "total": 1, "bills": []}
        with mock.patch.object(billing_router.receivables, "client_statement", return_value=statement), mock.patch.object(
            billing_router.billing, "get_profile", return_value={}
        ):
            self.assertEqual(client.post("/billing/receivables/C1/reminder/ai", json={"tone": "angry"}).status_code, 400)

    def test_form_filling_checks_the_entity_and_the_text(self):
        client = self.client(entities_router.router, ods_write=True)
        self.assertEqual(client.post("/entities/Nonsense/ai/fill", json={"text": "some pasted text here"}).status_code, 404)
        self.assertEqual(client.post("/entities/Client/ai/fill", json={"text": "hi"}).status_code, 400)

    def test_explaining_a_run_needs_a_run_with_an_error_to_explain(self):
        client = self.client(etl_router.router, etl_access=True)
        with mock.patch.object(etl_router.etl, "get_run", return_value=None):
            self.assertEqual(client.post("/etl/runs/9/explain", json={}).status_code, 404)
        run = {"pipeline": "orion", "error": None, "steps": []}
        with mock.patch.object(etl_router.etl, "get_run", return_value=run), mock.patch.object(etl_router, "_visible", return_value={"orion"}):
            self.assertEqual(client.post("/etl/runs/9/explain", json={}).status_code, 400)

    def test_a_document_suggestion_needs_a_place_and_a_file_with_something_in_it(self):
        client = self.client(documents_router.router, documents_write=True)
        response = client.post("/documents/ai/suggest", data={"scope": "nowhere"}, files={"file": ("a.txt", b"hello", "text/plain")})
        self.assertEqual(response.status_code, 400)
        scope = next(iter(documents_router.documents.CATEGORIES))
        response = client.post("/documents/ai/suggest", data={"scope": scope}, files={"file": ("a.txt", b"", "text/plain")})
        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
