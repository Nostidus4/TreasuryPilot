"""Bind request correlation context for every HTTP request and echo the request id."""

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from treasurypilot_core.observability import (
    REQUEST_ID_HEADER,
    bind_context,
    clear_context,
    context_from_headers,
    log_invalid_headers,
)


class CorrelationMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        context, invalid = context_from_headers(
            {name.lower(): value for name, value in Headers(scope=scope).items()}
        )
        clear_context()
        bind_context(**context)
        log_invalid_headers(invalid)

        async def send_with_request_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message)[REQUEST_ID_HEADER] = context["request_id"]
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        finally:
            clear_context()
