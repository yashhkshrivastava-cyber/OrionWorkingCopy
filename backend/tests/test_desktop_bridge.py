"""The native window has no tabs; its bridge opens a second window for the pages that ask for "a new tab"."""

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "desktop"))

import orion_windows  # noqa: E402
from orion_windows import WindowBridge, safe_path  # noqa: E402


class WhichPathsAreOpened(unittest.TestCase):
    def test_a_path_inside_the_app_is_kept(self):
        for path in ("/utility/billing/BILL-0012", "/utility/billing/find?number=2026-27%2F202", "/dashboard/orion?fy=2026", "/"):
            self.assertEqual(safe_path(path), path)

    def test_nothing_that_could_leave_the_app_is(self):
        for path in (
            "https://evil.example/x", "//evil.example/x", "http://127.0.0.1:8100/", "javascript:alert(1)", "file:///c:/x", "utility/billing", "",
            "/\\evil.example", "/a\nb", "/a\rb", "/a\x00b", "/" + "a" * 700, None, 5, ["/x"], {"p": "/x"},
        ):
            self.assertIsNone(safe_path(path), repr(path))


class TheBridge(unittest.TestCase):
    def setUp(self):
        self.webview = mock.MagicMock()
        self.bridge = WindowBridge("http://127.0.0.1:8100/", "Orion PROD", self.webview)

    def test_it_opens_a_window_on_the_same_server_sharing_the_bridge(self):
        self.assertTrue(self.bridge.open_window("/utility/billing/BILL-0012"))
        args, kwargs = self.webview.create_window.call_args
        self.assertEqual(args, ("Orion PROD", "http://127.0.0.1:8100/utility/billing/BILL-0012"))
        self.assertIs(kwargs["js_api"], self.bridge)
        self.assertNotIn("confirm_close", kwargs)  # closing a second window must not ask "Close Orion?"

    def test_it_refuses_an_address_that_is_not_the_apps(self):
        for path in ("https://evil.example", "//evil.example", "javascript:alert(1)"):
            self.assertFalse(self.bridge.open_window(path))
        self.webview.create_window.assert_not_called()

    def test_the_page_is_offered_one_method_and_nothing_else(self):
        """pywebview hands every public attribute of the object to the page, so the rest must be underscored."""
        public = [name for name in vars(self.bridge) if not name.startswith("_")]
        self.assertEqual(public, [])
        callable_public = [name for name in dir(WindowBridge) if not name.startswith("_") and callable(getattr(WindowBridge, name))]
        self.assertEqual(callable_public, ["open_window"])


class TheLaunchersUseIt(unittest.TestCase):
    def test_both_launchers_pass_the_bridge_to_the_window_they_open(self):
        for name in ("app.py", "prod_app.py"):
            text = (ROOT / "desktop" / name).read_text(encoding="utf-8")
            self.assertIn("from orion_windows import WindowBridge", text, name)
            self.assertIn("js_api=WindowBridge(", text, name)

    def test_the_page_calls_the_method_the_bridge_has(self):
        page = (ROOT / "frontend" / "src" / "navigation" / "openInNewTab.ts").read_text(encoding="utf-8")
        self.assertIn("open_window", page)
        self.assertTrue(callable(orion_windows.WindowBridge.open_window))


if __name__ == "__main__":
    unittest.main()
