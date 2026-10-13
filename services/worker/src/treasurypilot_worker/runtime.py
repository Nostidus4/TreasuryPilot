"""Safe defaults and request metadata shared by all Celery tasks."""

from __future__ import annotations

import contextvars
import hashlib
import json
from typing import Any
from uuid import uuid4

import structlog
from celery import Task
from structlog.contextvars import bind_contextvars, get_contextvars

from treasurypilot_core.observability import CONTEXT_IDS

# Prefixed because Celery reserves ``correlation_id`` for the task id on every delivery.
TASK_HEADERS = {key: f"x_{key}" for key in CONTEXT_IDS}
CORRELATION_ID_HEADER = TASK_HEADERS["correlation_id"]
MAX_TASK_RETRIES = 5

logger = structlog.get_logger(__name__)


class RetryableTaskError(Exception):
    """An infrastructure failure that is safe to retry without changing task identity."""


def current_correlation_id() -> str | None:
    """Return the correlation id bound to the task currently being executed."""

    correlation_id = get_contextvars().get("correlation_id")
    return None if correlation_id is None else str(correlation_id)


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
        """Publish a task with the bound correlation ids, or a new correlation id at the boundary."""

        headers = dict(options.pop("headers", None) or {})
        bound = get_contextvars()
        for key, header in TASK_HEADERS.items():
            if bound.get(key):
                headers.setdefault(header, str(bound[key]))
        headers.setdefault(CORRELATION_ID_HEADER, str(uuid4()))
        return super().apply_async(args=args, kwargs=kwargs, headers=headers, **options)

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        """Bind a delivery's correlation ids for logs and child task publication."""

        headers = getattr(self.request, "headers", None) or {}
        ids = {
            key: str(headers[header]) for key, header in TASK_HEADERS.items() if headers.get(header)
        }
        ids.setdefault("correlation_id", str(uuid4()))
        # A fresh context copy so ids bound by this task never leak into the next
        # task run on the same pool thread.
        return contextvars.copy_context().run(self._run_bound, ids, args, kwargs)

    def _run_bound(self, ids: dict[str, str], args: tuple[Any, ...], kwargs: dict[str, Any]) -> Any:
        bind_contextvars(**ids)
        logger.info("task.started", task=self.name)
        return super().__call__(*args, **kwargs)

    def idempotency_key(self, *identifiers: object) -> str:
        """Create a key namespaced to this task from durable entity ids only."""

        return make_idempotency_key(self.name or type(self).__name__, *identifiers)
