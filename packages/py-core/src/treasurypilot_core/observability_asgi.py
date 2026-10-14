"""ASGI middleware shared by the api and signer: bind request log context, echo the request id.

Plain ASGI so py-core stays free of web framework dependencies.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

import structlog

from treasurypilot_core.observability import (
    REQUEST_ID_HEADER,
    bind_context,
    clear_context,
    context_from_headers,
    log_invalid_headers,
)

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

_REQUEST_ID_HEADER_BYTES = REQUEST_ID_HEADER.encode()


class CorrelationMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # ASGI header names are already lower-case.
        context, invalid = context_from_headers(
            {name.decode("latin-1"): value.decode("latin-1") for name, value in scope["headers"]}
        )
        request_id = context["request_id"].encode("latin-1")
        clear_context()
        bind_context(**context)
        log_invalid_headers(invalid)
        response_started = False

        async def send_with_request_id(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
                message["headers"] = [
                    *(
                        (name, value)
                        for name, value in message.get("headers", [])
                        if name.lower() != _REQUEST_ID_HEADER_BYTES
                    ),
                    (_REQUEST_ID_HEADER_BYTES, request_id),
                ]
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        except Exception:
            # The server's error handler runs outside this middleware, after the context is
            # cleared, so log and answer the 500 here while the request id is still known.
            structlog.get_logger().exception("unhandled_exception")
            if not response_started:
                await send_with_request_id(
                    {
                        "type": "http.response.start",
                        "status": 500,
                        "headers": [(b"content-type", b"text/plain; charset=utf-8")],
                    }
                )
                await send({"type": "http.response.body", "body": b"Internal Server Error"})
            raise
        finally:
            clear_context()


__all__ = ["CorrelationMiddleware"]
