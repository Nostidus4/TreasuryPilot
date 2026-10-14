from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from treasurypilot_api.events.models import DomainEvent


def append_domain_event(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    event_type: str,
    entity_type: str,
    entity_id: uuid.UUID,
    treasury_id: uuid.UUID | None = None,
    payload_ids: Mapping[str, uuid.UUID | Sequence[uuid.UUID]] | None = None,
) -> DomainEvent:
    """Add an ids-only outbox row to the caller's current database transaction."""

    payload: dict[str, str | list[str]] = {}
    for key, value in (payload_ids or {}).items():
        if isinstance(value, uuid.UUID):
            payload[key] = str(value)
        elif isinstance(value, Sequence) and not isinstance(value, str | bytes):
            payload[key] = [str(item) for item in value]
        else:
            raise TypeError(f"payload id {key!r} must be a UUID or sequence of UUIDs")

    event = DomainEvent(
        org_id=organization_id,
        treasury_id=treasury_id,
        event_type=event_type,
        entity_type=entity_type,
        entity_id=entity_id,
        payload=payload,
    )
    session.add(event)
    return event
