"""Opening a second Orion window, for the native desktop launchers (app.py and prod_app.py).

The web app opens some screens "in a new tab" so the screen you are on stays as it is (a bill from a dashboard, a record from a list).
A native window has no tabs: the window library either hands a new-tab request to the system browser, where nobody is signed in, or
loads it over the current screen, which loses the place. So the launcher gives the page this bridge, and the page calls
``window.pywebview.api.open_window("/utility/billing/BILL-0012")``, which opens another window on the same server. Every window of a
launch shares one browser profile (the launcher's ``storage_path``), so the second window is already signed in.

Only a path inside this app is opened: never another address.
"""

from __future__ import annotations

from typing import Any, Optional
from urllib.parse import urlsplit

MAX_PATH = 600
WIDTH, HEIGHT = 1280, 860
MIN_SIZE = (960, 640)


def safe_path(path: Any) -> Optional[str]:
    """The path if it is an address inside the app (a path from the root, no other host, no control characters), else None."""
    if not isinstance(path, str) or not path.startswith("/") or path.startswith("//") or len(path) > MAX_PATH:
        return None
    if "\\" in path or any(ord(ch) < 32 or ord(ch) == 127 for ch in path):
        return None
    parts = urlsplit(path)
    if parts.scheme or parts.netloc:
        return None
    return path


class WindowBridge:
    """The object the launcher passes as ``js_api``. Its public methods are what the page can call; everything else is underscored,
    because the window library offers every public attribute to the page."""

    def __init__(self, base_url: str, title: str, webview_module: Any) -> None:
        self._base = base_url.rstrip("/")
        self._title = title
        self._webview = webview_module

    def open_window(self, path: str) -> bool:
        """Open ``path`` of this app in a new window. False when the path is not one of this app's."""
        target = safe_path(path)
        if target is None:
            return False
        self._webview.create_window(
            self._title,
            f"{self._base}{target}",
            js_api=self,  # a window opened from a window can open another
            width=WIDTH,
            height=HEIGHT,
            min_size=MIN_SIZE,
            text_select=True,
        )
        return True
