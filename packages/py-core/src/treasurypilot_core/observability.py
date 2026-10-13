"""Structured JSON logging and correlation ids shared by api, worker and signer."""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Awaitable, Callable, Iterable, MutableMapping
from typing import Any
from uuid import uuid4

import structlog
from structlog.contextvars import bind_contextvars, clear_contextvars, get_contextvars
from structlog.typing import EventDict, WrappedLogger

from treasurypilot_core.privacy import redact_event

CONTEXT_IDS = ("correlation_id", "org_id", "request_id", "plan_id", "operation_id")
# Prefixed so a proxy's own X-Request-Id never overwrites the payment request id.
CONTEXT_HEADERS = {key: "x-tp-" + key.replace("_", "-") for key in CONTEXT_IDS}
_SAFE_ID = re.compile(r"[A-Za-z0-9._:-]{1,128}")

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

_handler: logging.Handler | None = None
logger = structlog.get_logger("treasurypilot.http")


def configure_logging(service: str, level: str | int = "INFO") -> None:
    """Render structlog and stdlib records as one redacted JSON line on stderr."""

    global _handler

    def add_service(_logger: WrappedLogger, _method: str, event_dict: EventDict) -> EventDict:
        event_dict["service"] = service
        return event_dict

    shared: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        add_service,
    ]
    structlog.configure(
        processors=[*shared, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=False,
    )
    # Redaction (M14) runs after every enrichment and before the only sink.
    render: list[Any] = [
        structlog.stdlib.ProcessorFormatter.remove_processors_meta,
        redact_event,
        structlog.processors.JSONRenderer(),
    ]
    handler = logging.StreamHandler()
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(foreign_pre_chain=shared, processors=render)
    )
    root = logging.getLogger()
    # Replace only our own handler so test capture handlers survive reconfiguration.
    if _handler is not None:
        root.removeHandler(_handler)
    root.addHandler(handler)
    root.setLevel(level)
    _handler = handler
    # uvicorn installs its own plain-text handlers; route errors through ours and
    # drop its access log, which the middleware's ``http.request`` line replaces.
    for name in ("uvicorn", "uvicorn.error"):
        logging.getLogger(name).handlers.clear()
        logging.getLogger(name).propagate = True
    logging.getLogger("uvicorn.access").disabled = True


def context_headers() -> dict[str, str]:
    """Return the bound correlation ids as outbound HTTP headers (e.g. worker -> signer)."""

    bound = get_contextvars()
    return {CONTEXT_HEADERS[key]: str(bound[key]) for key in CONTEXT_IDS if bound.get(key)}


class CorrelationMiddleware:
    """Bind correlation ids for one HTTP request and log one line when it finishes.

    Public services trust only the inbound correlation id; internal services may
    accept every id via ``trusted_ids``.
    """

    def __init__(self, app: ASGIApp, *, trusted_ids: Iterable[str] = ("correlation_id",)) -> None:
        self.app = app
        self.trusted_ids = tuple(trusted_ids)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = {
            name.decode("latin-1").lower(): value.decode("latin-1")
            for name, value in scope.get("headers", [])
        }
        ids = {
            key: value
            for key in self.trusted_ids
            if (value := headers.get(CONTEXT_HEADERS[key])) and _SAFE_ID.fullmatch(value)
        }
        ids.setdefault("correlation_id", str(uuid4()))
        status = 500

        async def send_with_id(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                message["headers"] = [
                    *message.get("headers", []),
                    (CONTEXT_HEADERS["correlation_id"].encode(), ids["correlation_id"].encode()),
                ]
            await send(message)

        clear_contextvars()
        bind_contextvars(**ids)
        started = time.perf_counter()
        try:
            await self.app(scope, receive, send_with_id)
        finally:
            logger.info(
                "http.request",
                method=scope["method"],
                path=scope["path"],
                status=status,
                duration_ms=round((time.perf_counter() - started) * 1000, 1),
            )
            clear_contextvars()
