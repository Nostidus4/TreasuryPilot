"""Hands RETRY/CANCEL of a PartiallyCompleted plan to the worker's recovery tasks (RCV-003)."""

from __future__ import annotations

import uuid
from typing import Any, Protocol

from celery import Celery

from treasurypilot_api.config import Settings

RESUME_TASK = "treasurypilot.recovery.resume_partial"
CANCEL_TASK = "treasurypilot.recovery.cancel_partial"


class PartialRecoveryQueue(Protocol):
    def enqueue(self, action: str, request_id: uuid.UUID, actor_id: uuid.UUID) -> None: ...


class CeleryPartialRecoveryQueue:
    def __init__(self, broker_url: str, *, client: Any = None) -> None:
        self.client = client or Celery("treasurypilot-api", broker=broker_url)

    def enqueue(self, action: str, request_id: uuid.UUID, actor_id: uuid.UUID) -> None:
        task = RESUME_TASK if action == "RETRY" else CANCEL_TASK
        self.client.send_task(task, args=[str(request_id), str(actor_id)], queue="core")


def build_partial_recovery_queue(settings: Settings) -> CeleryPartialRecoveryQueue | None:
    if settings.redis_url is None:
        return None
    return CeleryPartialRecoveryQueue(settings.redis_url.get_secret_value())
