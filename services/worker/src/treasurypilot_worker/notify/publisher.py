"""PostgreSQL outbox publisher and notification materializer."""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from typing import Any

import asyncpg  # type: ignore[import-untyped]

from treasurypilot_worker.notify.routing import NotificationPolicy, policy_for_event

_CLAIM_EVENTS = """
SELECT id, org_id, treasury_id, type, entity_type, entity_id, payload
FROM domain_events
WHERE published_at IS NULL
ORDER BY created_at, id
LIMIT $1
FOR UPDATE SKIP LOCKED
"""

_ROLE_RECIPIENTS = """
SELECT DISTINCT m.user_id
FROM memberships AS m
JOIN users AS u ON u.id = m.user_id
WHERE m.org_id = $1
  AND m.status = 'active'
  AND u.status = 'active'
  AND (m.roles && $2::text[] OR m.user_id = ANY($3::uuid[]) OR m.user_id = $4)
ORDER BY m.user_id
"""

_INSERT_NOTIFICATION = """
INSERT INTO notifications
    (id, org_id, user_id, event_id, type, title, body, link, severity)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
ON CONFLICT (user_id, event_id) DO NOTHING
"""

_MARK_PUBLISHED = """
UPDATE domain_events
SET published_at = now()
WHERE id = $1 AND published_at IS NULL
"""


def _event_payload(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, Mapping):
        raise ValueError("domain event payload must be a JSON object")
    return dict(value)


def _creator_id(policy: NotificationPolicy, payload: Mapping[str, Any]) -> uuid.UUID | None:
    value = payload.get("creatorId") if policy.include_creator else None
    if value is None:
        return None
    try:
        return uuid.UUID(str(value))
    except ValueError as exc:
        raise ValueError("PaymentDone creatorId must be a UUID") from exc


def _specific_user_ids(
    policy: NotificationPolicy, payload: Mapping[str, Any]
) -> tuple[uuid.UUID, ...]:
    if policy.specific_user_ids_key is None:
        return ()
    value = payload.get(policy.specific_user_ids_key)
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ValueError(f"{policy.specific_user_ids_key} must be an array of UUIDs")
    try:
        return tuple(dict.fromkeys(uuid.UUID(str(item)) for item in value))
    except ValueError as exc:
        raise ValueError(f"{policy.specific_user_ids_key} must contain UUIDs") from exc


def _link(entity_type: str, entity_id: uuid.UUID, treasury_id: uuid.UUID | None) -> str:
    if entity_type == "payment_request":
        return f"/requests/{entity_id}"
    if entity_type == "review_item":
        return f"/review-items/{entity_id}"
    if treasury_id is not None:
        return f"/treasuries/{treasury_id}"
    return "/"


async def publish_pending_events(connection: asyncpg.Connection, *, batch_size: int = 100) -> int:
    """Route a locked batch atomically; concurrent publishers skip the locked rows."""

    if batch_size < 1:
        raise ValueError("batch_size must be positive")

    async with connection.transaction():
        events = await connection.fetch(_CLAIM_EVENTS, batch_size)
        for event in events:
            policy = policy_for_event(event["type"])
            payload = _event_payload(event["payload"])
            creator_id = _creator_id(policy, payload)
            specific_user_ids = _specific_user_ids(policy, payload)
            recipients = await connection.fetch(
                _ROLE_RECIPIENTS,
                event["org_id"],
                list(policy.roles),
                list(specific_user_ids),
                creator_id,
            )
            link = _link(event["entity_type"], event["entity_id"], event["treasury_id"])
            for recipient in recipients:
                await connection.execute(
                    _INSERT_NOTIFICATION,
                    uuid.uuid4(),
                    event["org_id"],
                    recipient["user_id"],
                    event["id"],
                    event["type"],
                    policy.title,
                    policy.body,
                    link,
                    policy.severity,
                )
            await connection.execute(_MARK_PUBLISHED, event["id"])
    return len(events)


async def publish_from_pool(pool: asyncpg.Pool, *, batch_size: int = 100) -> int:
    async with pool.acquire() as connection:
        return await publish_pending_events(connection, batch_size=batch_size)
