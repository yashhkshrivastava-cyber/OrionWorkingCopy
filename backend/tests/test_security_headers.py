"""Browser-side defences: security headers on every response, and the session cookie's Secure flag.

None of this needs a database. Run from the repo root:  python -m pytest backend/tests

A Content-Security-Policy that is too strict breaks the app silently (a blank PDF preview, a missing font), and one that is
too loose protects nothing, so these pin both: the policy's shape, and that everything the frontend loads is allowed by it.
The real browser check (every page, the PDF preview, the chat socket, a download) was done against the production build.
"""

import re
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI, WebSocket
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app import security_headers as sh  # noqa: E402
from app.main import app  # noqa: E402

FRONTEND = ROOT / "frontend"


def directives(policy: str) -> dict[str, list[str]]:
    return {part.split()[0]: part.split()[1:] for part in policy.split(";") if part.strip()}


class Policy(unittest.TestCase):
    policy = directives(sh.build_csp())

    def test_scripts_come_only_from_this_server(self):
        self.assertEqual(self.policy["script-src"], ["'self'"])  # no inline, no eval, no other host

    def test_nothing_is_sent_to_another_host(self):
        self.assertEqual(self.policy["connect-src"], ["'self'"])  # includes the chat WebSocket on the same host
        self.assertEqual(self.policy["default-src"], ["'self'"])
        self.assertEqual(self.policy["form-action"], ["'self'"])
        self.assertEqual(self.policy["base-uri"], ["'self'"])

    def test_inline_is_allowed_for_styles_only(self):
        for name, sources in self.policy.items():
            if name != "style-src":
                self.assertNotIn("'unsafe-inline'", sources, name)
            self.assertNotIn("'unsafe-eval'", sources, name)

    def test_previews_of_files_the_browser_holds_are_allowed(self):
        for name in ("frame-src", "object-src", "img-src", "media-src"):
            self.assertIn("blob:", self.policy[name], name)

    def test_there_is_no_frame_ancestors_because_it_blanks_pdf_previews(self):
        """A PDF preview is a blob page that inherits this policy; the browser's PDF viewer lives in a chrome-extension://
        frame inside it, which frame-ancestors 'self' refuses. Found by testing the production build: every preview was a
        blank box. Clickjacking is covered by X-Frame-Options instead."""
        self.assertNotIn("frame-ancestors", self.policy)
        self.assertEqual(sh.headers_for(https=False, path="/", content_type="text/html")["X-Frame-Options"], "SAMEORIGIN")

    def test_everything_the_frontend_loads_from_elsewhere_is_allowed(self):
        """A new font, script or API on another host must be added to the policy, or the browser blocks it in production."""
        allowed = {"fonts.googleapis.com", "fonts.gstatic.com", "www.w3.org"}  # w3.org is only an XML namespace string
        text = (FRONTEND / "index.html").read_text(encoding="utf-8")
        for path in (FRONTEND / "src").rglob("*.ts*"):
            text += path.read_text(encoding="utf-8")
        hosts = set(re.findall(r"https?://([a-zA-Z0-9.-]+)", text)) - {"localhost", "127.0.0.1"}
        stray = {host for host in hosts if host not in allowed and not host.endswith(("example.com", "example.org", "reactjs.org", "react.dev"))}
        self.assertEqual(stray, set(), "add these hosts to security_headers.build_csp (or stop loading them)")
        self.assertIn("https://fonts.googleapis.com", self.policy["style-src"])
        self.assertIn("https://fonts.gstatic.com", self.policy["font-src"])

    def test_the_page_has_no_inline_script_because_the_policy_refuses_them(self):
        html = (FRONTEND / "index.html").read_text(encoding="utf-8")
        inline = [tag for tag in re.findall(r"<script\b([^>]*)>", html) if "src=" not in tag]
        self.assertEqual(inline, [], "an inline script in index.html is blocked in production: put it in public/")
        self.assertIn('src="/theme-boot.js"', html)
        boot = FRONTEND / "public" / "theme-boot.js"
        self.assertTrue(boot.is_file())
        self.assertIn("orion-appearance-cache", boot.read_text(encoding="utf-8"))  # still the pre-paint theme, not a stub


class HeadersForOneResponse(unittest.TestCase):
    def headers(self, **kw):
        return sh.headers_for(**{"https": False, "path": "/api/x", "content_type": "application/json", **kw})

    def test_every_response_gets_the_basics(self):
        found = self.headers()
        self.assertEqual(found["X-Content-Type-Options"], "nosniff")
        self.assertEqual(found["Referrer-Policy"], "same-origin")  # a reset link carries its token in the address
        for feature in ("geolocation=()", "payment=()", "usb=()"):
            self.assertIn(feature, found["Permissions-Policy"])
        # Calls and voice notes: Orion's own pages only, never an embedded site.
        for feature in ("camera=(self)", "microphone=(self)", "display-capture=(self)"):
            self.assertIn(feature, found["Permissions-Policy"])
        self.assertIn("Content-Security-Policy", found)

    def test_hsts_only_over_https(self):
        self.assertNotIn("Strict-Transport-Security", self.headers(https=False))
        self.assertRegex(self.headers(https=True)["Strict-Transport-Security"], r"^max-age=\d+$")
        self.assertNotIn("includeSubDomains", self.headers(https=True)["Strict-Transport-Security"])

    def test_the_policy_can_be_watched_before_it_is_enforced_or_switched_off(self):
        self.assertIn("Content-Security-Policy", sh.headers_for(https=False, path="/", content_type=None, environ={}))
        report = sh.headers_for(https=False, path="/", content_type=None, environ={"ORION_CSP": "report-only"})
        self.assertIn("Content-Security-Policy-Report-Only", report)
        self.assertNotIn("Content-Security-Policy", report)
        off = sh.headers_for(https=False, path="/", content_type=None, environ={"ORION_CSP": "off"})
        self.assertFalse([name for name in off if name.startswith("Content-Security-Policy")])
        self.assertIn("X-Content-Type-Options", off)  # the rest stay on
        bad = sh.headers_for(https=False, path="/", content_type=None, environ={"ORION_CSP": "nonsense"})
        self.assertIn("Content-Security-Policy", bad)  # a typo must not switch a protection off

    def test_the_interactive_api_pages_are_exempt_because_they_load_a_cdn(self):
        self.assertNotIn("Content-Security-Policy", self.headers(path="/docs"))
        self.assertNotIn("Content-Security-Policy", self.headers(path="/redoc"))
        self.assertIn("Content-Security-Policy", self.headers(path="/documents"))

    def test_only_json_answers_are_kept_out_of_the_browser_cache(self):
        self.assertEqual(self.headers()["Cache-Control"], "no-store")
        self.assertNotIn("Cache-Control", self.headers(content_type="application/pdf"))
        self.assertNotIn("Cache-Control", self.headers(content_type="image/jpeg"))
        self.assertNotIn("Cache-Control", self.headers(path="/assets/app.js", content_type="text/javascript"))


class SessionCookie(unittest.TestCase):
    def request(self, scheme):
        return SimpleNamespace(url=SimpleNamespace(scheme=scheme))

    def test_secure_exactly_when_the_browser_used_https(self):
        self.assertTrue(sh.cookie_secure(self.request("https"), environ={}))
        self.assertFalse(sh.cookie_secure(self.request("http"), environ={}))

    def test_it_can_be_forced_on_or_off(self):
        for value in ("1", "true", "YES", " on "):
            self.assertTrue(sh.cookie_secure(self.request("http"), environ={"ORION_COOKIE_SECURE": value}), value)
        for value in ("0", "false", "no", "off"):
            self.assertFalse(sh.cookie_secure(self.request("https"), environ={"ORION_COOKIE_SECURE": value}), value)
        self.assertTrue(sh.cookie_secure(self.request("https"), environ={"ORION_COOKIE_SECURE": "auto"}))

    def test_the_cookie_is_set_and_cleared_with_the_same_attributes(self):
        from app.routers import auth_router
        import inspect

        login, logout = inspect.getsource(auth_router.login), inspect.getsource(auth_router.logout)
        self.assertIn("secure=cookie_secure(request)", login)
        self.assertIn("secure=cookie_secure(request)", logout)  # or some browsers keep a cookie they were told to delete
        for source in (login, logout):
            self.assertIn("httponly=True", source)
            self.assertIn('samesite="lax"', source)


class ApiDocs(unittest.TestCase):
    def test_production_does_not_publish_the_list_of_routes(self):
        self.assertTrue(sh.api_docs_enabled({}))
        self.assertTrue(sh.api_docs_enabled({"ORION_ENV": "development"}))
        self.assertFalse(sh.api_docs_enabled({"ORION_ENV": "production"}))
        self.assertFalse(sh.api_docs_enabled({"ORION_ENV": " Production "}))
        self.assertTrue(sh.api_docs_enabled({"ORION_ENV": "production", "ORION_API_DOCS": "1"}))


class Middleware(unittest.TestCase):
    def mini(self):
        mini = FastAPI()
        mini.add_middleware(sh.SecurityHeadersMiddleware)

        @mini.get("/api/data")
        def data():
            return {"ok": True}

        @mini.get("/api/cached")
        def cached():
            return JSONResponse({"ok": True}, headers={"Cache-Control": "max-age=60", "X-Frame-Options": "DENY"})

        @mini.get("/page")
        def page():
            return PlainTextResponse("hello")

        @mini.websocket("/ws")
        async def socket(websocket: WebSocket):
            await websocket.accept()
            await websocket.send_json({"hello": 1})
            await websocket.close()

        return TestClient(mini)

    def test_headers_are_added_to_every_kind_of_answer(self):
        client = self.mini()
        for path in ("/api/data", "/page", "/missing"):
            response = client.get(path)
            self.assertEqual(response.headers["x-content-type-options"], "nosniff", path)
            self.assertIn("content-security-policy", response.headers, path)

    def test_a_header_the_route_chose_is_left_alone(self):
        response = self.mini().get("/api/cached")
        self.assertEqual(response.headers["cache-control"], "max-age=60")
        self.assertEqual(response.headers["x-frame-options"], "DENY")

    def test_json_is_not_cached_and_html_text_may_be(self):
        client = self.mini()
        self.assertEqual(client.get("/api/data").headers["cache-control"], "no-store")
        self.assertNotIn("cache-control", client.get("/page").headers)

    def test_hsts_follows_the_scheme_the_browser_used(self):
        self.assertNotIn("strict-transport-security", TestClient(self.mini().app, base_url="http://testserver").get("/page").headers)
        self.assertIn("strict-transport-security", TestClient(self.mini().app, base_url="https://testserver").get("/page").headers)

    def test_the_chat_socket_passes_through_untouched(self):
        with self.mini().websocket_connect("/ws") as socket:
            self.assertEqual(socket.receive_json(), {"hello": 1})

    def test_the_real_app_has_it_on_its_first_wall(self):
        response = TestClient(app).get("/api/health")  # answers without the database
        self.assertEqual(response.json(), {"status": "ok"})
        self.assertIn("content-security-policy", response.headers)
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertTrue(any(m.cls is sh.SecurityHeadersMiddleware for m in app.user_middleware))


if __name__ == "__main__":
    unittest.main()
