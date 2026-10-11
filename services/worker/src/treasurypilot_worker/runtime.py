"""Safe defaults and request metadata shared by all Celery tasks."""

from __future__ import annotations

import hashlib
import json
from contextvars import ContextVar
from typing import Any
from uuid import uuid4

from celery import Task

CORRELATION_ID_HEADER = "correlation_id"
MAX_TASK_RETRIES = 5

_correlation_id: ContextVar[str | None] = ContextVar("correlation_id", default=None)


class RetryableTaskError(Exception):
    """An infrastructure failure that is safe to retry without changing task identity."""


def current_correlation_id() -> str | None:
    """Return the correlation id bound to the task currently being executed."""

    return _correlation_id.get()


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
        """Publish a task with the current correlation id, or create one at the boundary."""

        headers = dict(options.pop("headers", None) or {})
        headers.setdefault(CORRELATION_ID_HEADER, current_correlation_id() or str(uuid4()))
        return super().apply_async(args=args, kwargs=kwargs, headers=headers, **options)

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        """Bind a delivery's correlation id for logs and child task publication."""

        headers = getattr(self.request, "headers", None) or {}
        correlation_id = str(headers.get(CORRELATION_ID_HEADER) or uuid4())
        token = _correlation_id.set(correlation_id)
        try:
            return super().__call__(*args, **kwargs)
        finally:
            _correlation_id.reset(token)

    def idempotency_key(self, *identifiers: object) -> str:
        """Create a key namespaced to this task from durable entity ids only."""

        return make_idempotency_key(self.name or type(self).__name__, *identifiers)
