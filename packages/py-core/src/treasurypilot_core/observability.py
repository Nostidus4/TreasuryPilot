"""Structured JSON logging and correlation context shared by api, worker and signer.

Framework-free on purpose: ASGI middleware and Celery hooks live in each service.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from typing import Literal, cast
from uuid import uuid4

import structlog
from structlog.contextvars import bind_contextvars, clear_contextvars, get_contextvars
from structlog.typing import EventDict, Processor, WrappedLogger

from treasurypilot_core.privacy import redact_event

CONTEXT_FIELDS = ("correlation_id", "request_id", "org_id", "plan_id", "operation_id")
REQUEST_ID_HEADER = "x-request-id"
# Headers a caller may send; the api and signer bind them as *claimed* context.
CONTEXT_HEADERS = {
    "org_id": "x-org-id",
    "plan_id": "x-plan-id",
    "operation_id": "x-operation-id",
}

LogFormat = Literal["json", "console"]

_VALID_ID = re.compile(r"[A-Za-z0-9._:-]{8,64}")
# A bare 64-hex string looks like a private key and would be redacted, so it is not a valid id.
_BARE_HEX_64 = re.compile(r"[0-9a-fA-F]{64}")


def is_valid_id(value: object) -> bool:
    """Accept ids that are safe to log and survive redaction."""

    return (
        isinstance(value, str)
        and _VALID_ID.fullmatch(value) is not None
        and _BARE_HEX_64.fullmatch(value) is None
    )


def bind_context(**fields: str) -> None:
    """Bind correlation fields for every later log line in this task or request."""

    unknown = set(fields) - set(CONTEXT_FIELDS)
    if unknown:
        raise ValueError(f"unknown log context fields: {sorted(unknown)}")
    bind_contextvars(**fields)


def clear_context() -> None:
    clear_contextvars()


def current_context() -> dict[str, str]:
    bound = get_contextvars()
    return {name: bound[name] for name in CONTEXT_FIELDS if name in bound}


def context_from_headers(headers: Mapping[str, str]) -> tuple[dict[str, str], list[str]]:
    """Derive log context from lower-cased HTTP headers.

    Returns the context plus the names of headers that were present but invalid. An invalid
    request id is replaced by a fresh uuid; other invalid ids are dropped.
    """

    request_id = headers.get(REQUEST_ID_HEADER)
    invalid: list[str] = []
    if request_id is not None and not is_valid_id(request_id):
        invalid.append(REQUEST_ID_HEADER)
        request_id = None
    request_id = request_id or str(uuid4())
    context = {"correlation_id": request_id, "request_id": request_id}
    for field, header in CONTEXT_HEADERS.items():
        value = headers.get(header)
        if value is None:
            continue
        if is_valid_id(value):
            context[field] = value
        else:
            invalid.append(header)
    return context, invalid


def configure_logging(service: str, level: str = "INFO", fmt: LogFormat = "json") -> None:
    """Route structlog output through context merge, redaction and a single renderer."""

    level_no = logging.getLevelNamesMapping().get(level.upper())
    if level_no is None:
        raise ValueError(f"unknown log level: {level!r}")

    def add_service(_logger: WrappedLogger, _method: str, event_dict: EventDict) -> EventDict:
        event_dict["service"] = service
        return event_dict

    renderer: Processor = (
        structlog.dev.ConsoleRenderer(colors=False)
        if fmt == "console"
        else structlog.processors.JSONRenderer()
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            add_service,
            cast(
                Processor, redact_event
            ),  # last before the renderer so no field added above escapes it
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level_no),
        logger_factory=structlog.PrintLoggerFactory(),
    )


def log_invalid_headers(invalid: list[str]) -> None:
    """Warn about rejected context headers by name only; the value is never logged."""

    if invalid:
        structlog.get_logger().warning("invalid_context_header", headers=invalid)


__all__ = [
    "CONTEXT_FIELDS",
    "CONTEXT_HEADERS",
    "REQUEST_ID_HEADER",
    "bind_context",
    "clear_context",
    "configure_logging",
    "context_from_headers",
    "current_context",
    "is_valid_id",
    "log_invalid_headers",
]
