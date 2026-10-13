"""Structured JSON logging and correlation context shared by api, worker and signer.

Framework-free on purpose: the ASGI middleware is in ``observability_asgi`` and the Celery hooks
live in the worker.
"""

from __future__ import annotations

import logging
import re
import sys
from collections.abc import Mapping
from typing import Literal, cast
from uuid import uuid4

import structlog
from structlog.contextvars import bind_contextvars, clear_contextvars, get_contextvars
from structlog.typing import EventDict, Processor, WrappedLogger

from treasurypilot_core.privacy import redact_event
from treasurypilot_core.privacy.redaction import _redact_string

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


def is_valid_id(value: object) -> bool:
    """Accept ids that are safe to log and survive redaction."""

    return (
        isinstance(value, str)
        and _VALID_ID.fullmatch(value) is not None
        # e.g. a bare 64-hex string or ``token:12345678`` would be logged redacted, unsearchable.
        and _redact_string(value) == value
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


class _StdoutHandler(logging.StreamHandler):
    """Write to the current ``sys.stdout`` (like structlog's print logger), not the one at setup.

    Safe under Celery: with a ``setup_logging`` receiver it does not redirect stdout to logging.
    """

    def emit(self, record: logging.LogRecord) -> None:
        self.stream = sys.stdout
        super().emit(record)


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
    shared: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        add_service,
    ]
    structlog.configure(
        processors=[*shared, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        wrapper_class=structlog.make_filtering_bound_logger(level_no),
        logger_factory=structlog.stdlib.LoggerFactory(),
    )
    # One root handler so stdlib loggers (Celery, uvicorn, libraries) get the same context,
    # redaction and renderer as structlog events.
    handler = _StdoutHandler()
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=shared,
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                cast(Processor, redact_event),  # last before the renderer so nothing escapes it
                renderer,
            ],
        )
    )
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level_no)
    # uvicorn installs its own non-propagating handlers before the app is imported.
    for name in ("uvicorn", "uvicorn.access"):
        server_logger = logging.getLogger(name)
        server_logger.handlers = []
        server_logger.propagate = True


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
