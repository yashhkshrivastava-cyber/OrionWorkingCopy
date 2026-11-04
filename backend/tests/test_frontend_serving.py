"""The built web app is served with the cache rules that its split into separate, content-hashed files makes safe, and compressed."""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from starlette.middleware.gzip import GZipMiddleware  # noqa: E402

from app import frontend_serving, main  # noqa: E402


class TheBuiltApp(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.dist = Path(self.folder.name) / "dist"
        (self.dist / "assets").mkdir(parents=True)
        (self.dist / "index.html").write_text("<html>app</html>", encoding="utf-8")
        (self.dist / "assets" / "Billing-3fa9c1.js").write_text("export const x = 1", encoding="utf-8")
        (self.dist / "theme-boot.js").write_text("// boot", encoding="utf-8")
        (Path(self.folder.name) / "secret.txt").write_text("outside the build", encoding="utf-8")
        self.app = FastAPI()

        @self.app.get("/api/ping")
        def ping():
            return {"ok": True}

        self.assertTrue(frontend_serving.mount_frontend(self.app, self.dist))
        self.client = TestClient(self.app)

    def test_a_hashed_file_is_kept_for_a_year_and_never_asked_about(self):
        response = self.client.get("/assets/Billing-3fa9c1.js")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["cache-control"], "public, max-age=31536000, immutable")

    def test_the_page_that_names_the_files_is_checked_every_time(self):
        for path in ("/", "/utility/billing", "/documents"):
            response = self.client.get(path)
            self.assertEqual((response.status_code, response.text), (200, "<html>app</html>"), path)
            self.assertEqual(response.headers["cache-control"], "no-cache", path)

    def test_other_files_outside_assets_are_checked_every_time_too(self):
        response = self.client.get("/theme-boot.js")
        self.assertEqual((response.status_code, response.text), (200, "// boot"))
        self.assertEqual(response.headers["cache-control"], "no-cache")

    def test_a_file_that_has_gone_is_a_404_not_the_page(self):
        """After a release an open tab asks for an old file: it must see a failure (the tab then says it is out of date), not
        index.html in place of a script, which the browser would refuse to run in a confusing way."""
        response = self.client.get("/assets/Billing-0ldh4sh.js")
        self.assertEqual(response.status_code, 404)
        self.assertNotIn("cache-control", response.headers)

    def test_the_api_is_not_swallowed(self):
        self.assertEqual(self.client.get("/api/ping").json(), {"ok": True})
        self.assertEqual(self.client.get("/api/not-a-route").status_code, 404)

    def test_nothing_outside_the_build_is_served(self):
        for path in ("/../secret.txt", "/%2e%2e/secret.txt", "/..%2fsecret.txt"):
            response = self.client.get(path)
            self.assertNotIn("outside the build", response.text, path)

    def test_no_build_means_nothing_is_mounted(self):
        empty = FastAPI()
        self.assertFalse(frontend_serving.mount_frontend(empty, Path(self.folder.name) / "nowhere"))


class Compression(unittest.TestCase):
    def test_the_real_app_compresses_what_is_worth_it_and_streams_are_left_alone(self):
        found = [m for m in main.app.user_middleware if m.cls is GZipMiddleware]
        self.assertEqual(len(found), 1)
        self.assertGreaterEqual(found[0].kwargs["minimum_size"], 500)
        # The assistant's answers arrive as server-sent events: compressing one would hold it back until the buffer filled.
        import inspect

        excluded = inspect.signature(GZipMiddleware.__init__).parameters["exclude_content_types"].default
        self.assertIn("text/event-stream", excluded)

    def test_it_sits_inside_the_request_id_layer_and_outside_the_security_headers(self):
        names = [m.cls.__name__ for m in main.app.user_middleware]  # outermost first
        self.assertLess(names.index("RequestContextMiddleware"), names.index("GZipMiddleware"))
        self.assertLess(names.index("GZipMiddleware"), names.index("SecurityHeadersMiddleware"))

    def test_a_large_answer_is_compressed_when_the_browser_accepts_it(self):
        app = FastAPI()

        @app.get("/big")
        def big():
            return {"rows": ["a row of business data"] * 500}

        app.add_middleware(GZipMiddleware, minimum_size=1024, compresslevel=5)
        plain = TestClient(app).get("/big", headers={"Accept-Encoding": "identity"})
        zipped = TestClient(app).get("/big", headers={"Accept-Encoding": "gzip"})
        self.assertNotIn("content-encoding", plain.headers)
        self.assertEqual(zipped.headers["content-encoding"], "gzip")
        self.assertEqual(zipped.json(), plain.json())


if __name__ == "__main__":
    unittest.main()
