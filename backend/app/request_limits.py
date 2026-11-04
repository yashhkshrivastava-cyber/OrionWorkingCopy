"""A limit on how much one request may carry, for the addresses that take uploads.

The framework writes an upload to disk as it arrives and only then runs the endpoint, so a size check inside the endpoint comes after the
disk has been filled. This refuses a request that is too big as soon as that is known: by the length the browser declared, and, for a
request that does not declare one (or declares it wrongly), as the body arrives.

It sits innermost, directly around the application, so that the error it raises while the body is being read reaches it and not the
catch-all that turns an unexpected error into a 500.
"""

from __future__ import annotations

import json
from typing import Any, Awaitable, Callable, MutableMapping

Scope = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[MutableMapping[str, Any]]]
Send = Callable[[MutableMapping[str, Any]], Awaitable[None]]


class _TooLarge(Exception):
    pass


class RequestSizeLimitMiddleware:
    def __init__(self, app: Any, limits: dict[str, int]):
        self.app = app
        # the most specific address first
        self.limits = sorted(limits.items(), key=lambda item: -len(item[0]))

    def _limit_for(self, path: str) -> int | None:
        for prefix, limit in self.limits:
            if path == prefix or path.startswith(prefix + "/"):
                return limit
        return None

    @staticmethod
    async def _refuse(send: Send, limit: int) -> None:
        megabytes = max(1, limit // (1024 * 1024))
        body = json.dumps({"detail": f"That is too much to send at once. The most is about {megabytes} MB."}).encode()
        await send({"type": "http.response.start", "status": 413,
                    "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode()), (b"connection", b"close")]})
        await send({"type": "http.response.body", "body": body})

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        limit = self._limit_for(scope.get("path", "")) if scope["type"] == "http" else None
        if limit is None:
            await self.app(scope, receive, send)
            return
        declared = dict(scope.get("headers") or []).get(b"content-length")
        if declared and declared.isdigit() and int(declared) > limit:
            await self._refuse(send, limit)
            return

        seen = 0

        async def counted() -> MutableMapping[str, Any]:
            nonlocal seen
            message = await receive()
            if message["type"] == "http.request":
                seen += len(message.get("body", b""))
                if seen > limit:
                    raise _TooLarge()
            return message

        started = False

        async def watching(message: MutableMapping[str, Any]) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, counted, watching)
        except _TooLarge:
            if not started:
                await self._refuse(send, limit)
