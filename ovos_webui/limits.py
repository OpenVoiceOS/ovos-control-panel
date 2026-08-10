"""An ASGI middleware that caps a request body while it is being read.

A ``Content-Length`` header is a claim, not a fact. A request with
``Transfer-Encoding: chunked`` carries no length at all, so a check on the
header alone lets a caller stream as much as it likes: the whole body is read
into memory before any handler, and therefore before any of this package's own
size checks, can look at it.

This middleware counts the bytes as they arrive and stops the request as soon
as the count passes the limit, so the memory a request can use is bounded
whatever headers it sends.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

Scope = dict[str, Any]
Receive = Callable[[], Awaitable[dict[str, Any]]]
Send = Callable[[dict[str, Any]], Awaitable[None]]


class BodyTooLarge(Exception):
    """Raised inside the ASGI chain when a body passes its limit."""


class BodyLimitMiddleware:
    """Cap the request body of every call.

    ``limit_for`` receives the scope and returns the number of bytes allowed
    for that path, so the upload endpoint can have a larger limit than the
    endpoints that take JSON.
    """

    def __init__(self, app, limit_for: Callable[[Scope], int], status_code: int = 413):
        self.app = app
        self.limit_for = limit_for
        self.status_code = status_code

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        limit = self.limit_for(scope)
        headers = {k.decode("latin-1").lower(): v.decode("latin-1")
                   for k, v in scope.get("headers") or []}

        # A declared length that is already too big is refused without reading
        # a single byte of the body.
        declared = headers.get("content-length")
        if declared is not None:
            try:
                if int(declared) > limit:
                    await self._refuse(send, "the request body is too large")
                    return
            except ValueError:
                await self._refuse(send, "content-length is not a number", 400)
                return

        read = 0
        tripped = False

        async def counting_receive() -> dict[str, Any]:
            nonlocal read, tripped
            message = await receive()
            if message.get("type") == "http.request":
                read += len(message.get("body", b"") or b"")
                if read > limit:
                    tripped = True
                    # Stop the stream. The handler sees a truncated body and
                    # the response below replaces whatever it would have said.
                    return {"type": "http.disconnect"}
            return message

        started = False
        first_status = None

        async def guarded_send(message: dict[str, Any]) -> None:
            nonlocal started, first_status
            if tripped:
                # The body was too large. Say so, once, and drop the rest.
                if not started:
                    started = True
                    await self._refuse(send, "the request body is too large")
                return
            if message.get("type") == "http.response.start":
                started = True
                first_status = message.get("status")
            await send(message)

        try:
            await self.app(scope, counting_receive, guarded_send)
        except Exception:
            if tripped and not started:
                await self._refuse(send, "the request body is too large")
                return
            raise
        if tripped and not started:
            await self._refuse(send, "the request body is too large")

    async def _refuse(self, send: Send, detail: str, status_code: int | None = None) -> None:
        import json

        body = json.dumps({"detail": detail}).encode("utf-8")
        await send({
            "type": "http.response.start",
            "status": status_code or self.status_code,
            "headers": [(b"content-type", b"application/json"),
                        (b"content-length", str(len(body)).encode("latin-1"))],
        })
        await send({"type": "http.response.body", "body": body})
