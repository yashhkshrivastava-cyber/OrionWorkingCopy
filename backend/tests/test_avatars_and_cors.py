"""Profile photos need a signed-in person, and production does not trust a private network range as a web origin."""

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import main  # noqa: E402
from app.dependencies import get_current_user  # noqa: E402
from app.security_headers import CORS_HEADERS, CORS_METHODS, cors_options  # noqa: E402

PRIVATE = "http://192.168.1.50:5173"


def _call_from(origin: str, environ: dict):
    """A request carrying `origin`, answered by a tiny app wrapped in the same middleware the real one gets."""
    app = FastAPI()

    @app.get("/ping")
    def ping():
        return {"ok": True}

    app.add_middleware(CORSMiddleware, **cors_options(environ))
    return TestClient(app).get("/ping", headers={"Origin": origin})


class WhoMayCallFromAnotherOrigin(unittest.TestCase):
    def test_development_trusts_this_pc_and_the_private_ranges(self):
        for origin in ("http://localhost:5173", "http://127.0.0.1:5173", PRIVATE, "http://100.64.1.2:5173"):
            self.assertEqual(_call_from(origin, {}).headers.get("access-control-allow-origin"), origin, origin)

    def test_development_does_not_trust_the_internet(self):
        self.assertIsNone(_call_from("https://evil.example", {}).headers.get("access-control-allow-origin"))

    def test_production_trusts_no_origin_by_default(self):
        for origin in ("http://localhost:5173", PRIVATE, "http://100.64.1.2:5173", "https://evil.example"):
            self.assertIsNone(_call_from(origin, {"ORION_ENV": "production"}).headers.get("access-control-allow-origin"), origin)

    def test_production_trusts_exactly_the_origins_it_is_told(self):
        env = {"ORION_ENV": "production", "ORION_CORS_ORIGINS": "https://orion.example.ts.net/, https://other.example"}
        self.assertEqual(_call_from("https://orion.example.ts.net", env).headers.get("access-control-allow-origin"), "https://orion.example.ts.net")
        self.assertIsNone(_call_from("https://orion.example.ts.net.evil.example", env).headers.get("access-control-allow-origin"))
        self.assertIsNone(_call_from(PRIVATE, env).headers.get("access-control-allow-origin"))

    def test_a_wildcard_is_ignored_in_production(self):
        self.assertEqual(cors_options({"ORION_ENV": "production", "ORION_CORS_ORIGINS": "*"})["allow_origins"], [])

    def test_methods_and_headers_are_named_not_wildcards(self):
        for env in ({}, {"ORION_ENV": "production"}):
            options = cors_options(env)
            self.assertEqual((options["allow_methods"], options["allow_headers"]), (CORS_METHODS, CORS_HEADERS))
        self.assertNotIn("*", CORS_METHODS + CORS_HEADERS)

    def test_every_header_the_ui_sends_is_allowed(self):
        api = Path(__file__).resolve().parents[2] / "frontend" / "src" / "api"
        sent = (api / "client.ts").read_text(encoding="utf-8") + (api / "idempotency.ts").read_text(encoding="utf-8")
        for header in ("Content-Type", "Idempotency-Key"):
            self.assertIn(header, sent)
            self.assertIn(header, CORS_HEADERS)

    def test_the_real_app_uses_the_helper(self):
        self.assertTrue(any(m.cls is CORSMiddleware for m in main.app.user_middleware))


class ProfilePhotos(unittest.TestCase):
    def tearDown(self):
        main.app.dependency_overrides.clear()

    def test_the_old_public_folder_is_gone(self):
        mounts = [r for r in main.app.routes if getattr(r, "name", "") == "avatars"]
        self.assertEqual(mounts, [])

    def test_a_photo_is_refused_without_signing_in(self):
        response = TestClient(main.app).get("/api/media/avatars/7.jpg")
        self.assertEqual(response.status_code, 401)

    def test_a_signed_in_person_gets_the_photo_through_the_old_address(self):
        main.app.dependency_overrides[get_current_user] = lambda: {"id": 1}
        with mock.patch.object(main, "avatar_response", return_value=main.JSONResponse({"photo": True})) as served:
            response = TestClient(main.app).get("/api/media/avatars/7.jpg?v=3")
        self.assertEqual(response.status_code, 200)
        served.assert_called_once_with(7)

    def test_only_a_number_and_a_picture_extension_is_a_photo(self):
        main.app.dependency_overrides[get_current_user] = lambda: {"id": 1}
        client = TestClient(main.app)
        for name in ("..%2Fsecrets.jpg", "7.html", "abc.jpg", "7", "7.jpg.php", "1234567890.jpg"):
            self.assertEqual(client.get(f"/api/media/avatars/{name}").status_code, 404, name)

    def test_no_photo_is_a_404_not_a_crash(self):
        main.app.dependency_overrides[get_current_user] = lambda: {"id": 1}
        with mock.patch("app.avatars.fetch_user_by_id", return_value=None):
            self.assertEqual(TestClient(main.app).get("/api/media/avatars/99.jpg").status_code, 404)


if __name__ == "__main__":
    unittest.main()
