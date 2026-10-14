"""Audit events raised by authority-affecting actions.

The hash-chained ``audit_log`` writer (AUD-001) is not part of this branch stack.
Callers build an :class:`AuditEvent` shaped like that writer's arguments and hand it
to the repository, which passes it to an :data:`AuditWriter` inside the same database
transaction as the change. Until the chain writer lands the default only logs.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class AuditEvent:
    org_id: uuid.UUID
    actor_id: uuid.UUID
    action: str
    entity_type: str
    entity_id: uuid.UUID
    # Never put secrets or PII in here; amounts would be integer base-unit strings.
    data: Mapping[str, object] = field(default_factory=dict)


AuditWriter = Callable[[AsyncSession, AuditEvent], Awaitable[None]]


async def log_audit_event(session: AsyncSession, event: AuditEvent) -> None:
    logger.info(
        "audit_event",
        extra={
            "org_id": str(event.org_id),
            "actor_id": str(event.actor_id),
            "audit_action": event.action,
            "entity_type": event.entity_type,
            "entity_id": str(event.entity_id),
        },
    )
