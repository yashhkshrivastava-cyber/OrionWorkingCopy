"""Browser-side defences: security headers on every response, and whether the session cookie is marked Secure.

What each header is for, in terms of this app:

* ``Content-Security-Policy`` is the second wall if a script ever got into a page (a letter's HTML, a chat message, a bad
  dependency): the browser will run only scripts from this server and will not send data to another host.
* ``X-Frame-Options``: nobody can put Orion in a frame to trick someone into clicking (clickjacking). It is used instead of
  the CSP's ``frame-ancestors`` on purpose: a PDF preview is a blob page that INHERITS the app's policy, and the browser's PDF
  viewer sits in a frame from its own extension (``chrome-extension://``), which ``frame-ancestors 'self'`` refuses, leaving the
  preview blank. ``X-Frame-Options`` guards the app's own pages and does not touch blob pages.
* ``X-Content-Type-Options: nosniff``: an uploaded file is never run as a page or script because its bytes look like one.
* ``Referrer-Policy: same-origin``: the password-reset link carries its token in the address; it must not leak to other sites.
* ``Permissions-Policy``: Orion's own pages may use the microphone, the camera and screen sharing (calls in Messages, and voice notes); nothing
  else, and no other site embedded in a page, can switch on a camera, microphone, location or payment feature.
* ``Strict-Transport-Security``: once a browser has used the HTTPS address it refuses the plain one. Sent only over HTTPS.
* ``Cache-Control: no-store`` on JSON answers: business data is not left in a browser cache on a shared PC.

``ORION_CSP`` = ``enforce`` (default), ``report-only`` (the browser logs what it would block but blocks nothing: use it to find
out what a change broke) or ``off``. ``ORION_COOKIE_SECURE`` = ``auto`` (default: Secure when the browser reached us over
HTTPS), ``1`` (always) or ``0`` (never).
"""

import os
from typing import Optional

from starlette.datastructures import MutableHeaders

# Where the UI's fonts come from. Themes add a Google Fonts stylesheet at run time (theme/themes.ts), so both hosts are named.
FONT_STYLES = "https://fonts.googleapis.com"
FONT_FILES = "https://fonts.gstatic.com"

HSTS_SECONDS = 31 * 24 * 3600  # a month: long enough to matter, short enough to back out of if HTTPS is ever dropped

PERMISSIONS_POLICY = "camera=(self), microphone=(self), display-capture=(self), geolocation=(), payment=(), usb=(), serial=(), interest-cohort=()"

# Pages that load their own code from a CDN (the interactive API docs, which exist only outside production).
CSP_EXEMPT_PREFIXES = ("/docs", "/redoc")


def api_docs_enabled(environ=None) -> bool:
    """The interactive API pages (/docs, /redoc, /openapi.json) list every route and let anyone try them. They are for
    developers: off in production unless ORION_API_DOCS=1."""
    source = environ if environ is not None else os.environ
    production = (source.get("ORION_ENV") or "").strip().lower() == "production"
    return not production or source.get("ORION_API_DOCS") == "1"


# What the browser may ask of this server from ANOTHER origin. The UI is served by the same process in production, so its
# requests are same-origin and need none of this; it matters only for the Vite dev server (another port) and for anything else
# that would call the API with the person's cookie.
CORS_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]
CORS_HEADERS = ["Content-Type", "Accept", "Idempotency-Key", "X-Request-ID"]
DEV_ORIGIN_PATTERN = r"http://(localhost|127\.0\.0\.1|100\.\d+\.\d+\.\d+|10\.\d+\.\d+\.\d+|192\.168\.\d+\.\d+)(:\d+)?"


def cors_options(environ=None) -> dict:
    """Who may call the API from another origin, with the cookie. Development: this PC and the private/Tailscale ranges, so a
    phone on the same network can reach the Vite server. Production: nobody, unless ORION_CORS_ORIGINS lists exact origins
    (comma separated, e.g. ``https://orion.example.ts.net``); a private address range is not an origin to trust there."""
    source = environ if environ is not None else os.environ
    options = {"allow_credentials": True, "allow_methods": CORS_METHODS, "allow_headers": CORS_HEADERS}
    if (source.get("ORION_ENV") or "").strip().lower() == "production":
        listed = [o.strip().rstrip("/") for o in (source.get("ORION_CORS_ORIGINS") or "").split(",") if o.strip() and o.strip() != "*"]
        return {**options, "allow_origins": listed, "allow_origin_regex": None}
    return {**options, "allow_origins": ["http://localhost:5173", "http://127.0.0.1:5173"], "allow_origin_regex": DEV_ORIGIN_PATTERN}


def csp_mode(environ=None) -> str:
    value = ((environ or os.environ).get("ORION_CSP") or "enforce").strip().lower()
    return value if value in ("enforce", "report-only", "off") else "enforce"


def build_csp() -> str:
    """The policy. ``'unsafe-inline'`` is for styles only: React sets style="..." attributes on elements, which cannot be
    avoided; scripts get no such allowance. Blob URLs are for previews of files the browser already holds (PDFs, photos).
    There is no ``frame-ancestors``: see the module note (it blanks every PDF preview)."""
    return "; ".join(
        (
            "default-src 'self'",
            "script-src 'self'",
            f"style-src 'self' 'unsafe-inline' {FONT_STYLES}",
            f"font-src 'self' data: {FONT_FILES}",
            "img-src 'self' data: blob:",
            "media-src 'self' blob:",
            "connect-src 'self'",
            "frame-src 'self' blob:",
            "object-src 'self' blob:",
            "worker-src 'self' blob:",
            "base-uri 'self'",
            "form-action 'self'",
        )
    )


def cookie_secure_mode(environ=None) -> str:
    value = ((environ or os.environ).get("ORION_COOKIE_SECURE") or "auto").strip().lower()
    if value in ("1", "true", "yes", "on"):
        return "always"
    if value in ("0", "false", "no", "off"):
        return "never"
    return "auto"


def is_https(request_or_scope) -> bool:
    """Whether the browser reached us over HTTPS. Behind the Tailscale proxy on this PC, uvicorn has already replaced the
    scheme with the one the proxy was given (X-Forwarded-Proto), so this is the browser's scheme, not the proxy's."""
    url = getattr(request_or_scope, "url", None)
    if url is not None:
        return url.scheme == "https"
    return request_or_scope.get("scheme") == "https"


def cookie_secure(request, environ=None) -> bool:
    """The ``secure`` flag for the session cookie. A Secure cookie is never sent over plain HTTP, so a copy of it cannot be read
    off the network by anyone on the same Wi-Fi. In ``auto`` it is set exactly when the browser used HTTPS; a plain-HTTP
    address (the office LAN) keeps working, only without that protection, which is why ``1`` exists for when everyone uses HTTPS."""
    mode = cookie_secure_mode(environ)
    if mode == "always":
        return True
    if mode == "never":
        return False
    return is_https(request)


def headers_for(*, https: bool, path: str, content_type: Optional[str], environ=None) -> dict[str, str]:
    """Every header to add to one response (a header the route already set is left alone)."""
    found = {
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "SAMEORIGIN",
        "Referrer-Policy": "same-origin",
        "Permissions-Policy": PERMISSIONS_POLICY,
    }
    mode = csp_mode(environ)
    if mode != "off" and not path.startswith(CSP_EXEMPT_PREFIXES):
        found["Content-Security-Policy-Report-Only" if mode == "report-only" else "Content-Security-Policy"] = build_csp()
    if https:
        found["Strict-Transport-Security"] = f"max-age={HSTS_SECONDS}"
    if path.startswith("/api") and (content_type or "").lower().startswith("application/json"):
        found["Cache-Control"] = "no-store"
    return found


class SecurityHeadersMiddleware:
    """Plain ASGI (not BaseHTTPMiddleware), so streamed files and the chat WebSocket pass through untouched."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        https, path = is_https(scope), scope.get("path", "")

        async def with_headers(message):
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in headers_for(https=https, path=path, content_type=headers.get("content-type")).items():
                    if name not in headers:
                        headers[name] = value
            await send(message)

        await self.app(scope, receive, with_headers)
