"""Safe defaults and request metadata shared by all Celery tasks."""

from __future__ import annotations

import hashlib
import json
from typing import Any
from uuid import uuid4

from celery import Task
from structlog.contextvars import bound_contextvars

from treasurypilot_core.observability import CONTEXT_FIELDS, current_context

CORRELATION_ID_HEADER = "x_correlation_id"
# All log context ids as one dict header; ``correlation_id`` alone would be overwritten by Celery.
LOG_CONTEXT_HEADER = "x_log_context"
MAX_TASK_RETRIES = 5


class RetryableTaskError(Exception):
    """An infrastructure failure that is safe to retry without changing task identity."""


def current_correlation_id() -> str | None:
    """Return the correlation id bound to the task currently being executed."""

    return current_context().get("correlation_id")


def make_idempotency_key(namespace: str, *identifiers: object) -> str:
    """Build a stable, opaque key from durable business identifiers.

    The helper does not perform de-duplication itself. Callers persist this key beside
    their Postgres outbox/state row and re-read that row on every delivery.
    """

    clean_namespace = namespace.strip()
    if not clean_namespace:
        raise ValueError("idempotency key namespace must not be empty")
    if not identifiers:
        raise ValueError("at least one durable identifier is required")
    if any(identifier is None or str(identifier).strip() == "" for identifier in identifiers):
        raise ValueError("idempotency key identifiers must not be empty")

    encoded = json.dumps(
        [clean_namespace, *(str(identifier) for identifier in identifiers)],
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode()
    digest = hashlib.sha256(encoded).hexdigest()
    return f"{clean_namespace}:{digest}"


class SafeTask(Task):
    """Celery task base for at-least-once, idempotent job execution."""

    abstract = True
    acks_late = True
    reject_on_worker_lost = True
    autoretry_for = (RetryableTaskError,)
    retry_backoff = True
    retry_backoff_max = 60
    retry_jitter = True
    retry_kwargs = {"max_retries": MAX_TASK_RETRIES}

    def apply_async(
        self,
        args: tuple[Any, ...] | None = None,
        kwargs: dict[str, Any] | None = None,
        **options: Any,
    ) -> Any:
        """Publish a task with the current log context, or create a correlation id at the boundary.

        Ids passed explicitly in ``x_log_context`` override the publisher's own.
        """

        headers = dict(options.pop("headers", None) or {})
        context = {**current_context(), **(headers.get(LOG_CONTEXT_HEADER) or {})}
        correlation_id = (
            headers.get(CORRELATION_ID_HEADER) or context.get("correlation_id") or str(uuid4())
        )
        headers[CORRELATION_ID_HEADER] = correlation_id
        headers[LOG_CONTEXT_HEADER] = {**context, "correlation_id": correlation_id}
        return super().apply_async(args=args, kwargs=kwargs, headers=headers, **options)

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        """Bind a delivery's log context for logs and child task publication."""

        headers = getattr(self.request, "headers", None) or {}
        sent = headers.get(LOG_CONTEXT_HEADER) or {}
        context = {name: str(sent[name]) for name in CONTEXT_FIELDS if sent.get(name)}
        context["correlation_id"] = str(
            context.get("correlation_id") or headers.get(CORRELATION_ID_HEADER) or uuid4()
        )
        with bound_contextvars(**context):
            return super().__call__(*args, **kwargs)

    def idempotency_key(self, *identifiers: object) -> str:
        """Create a key namespaced to this task from durable entity ids only."""

        return make_idempotency_key(self.name or type(self).__name__, *identifiers)
