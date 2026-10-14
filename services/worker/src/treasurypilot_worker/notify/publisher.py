"""PostgreSQL outbox publisher and notification materializer."""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Mapping
from typing import Any

import asyncpg  # type: ignore[import-untyped]

from treasurypilot_worker.notify.routing import NotificationPolicy, policy_for_event

logger = logging.getLogger(__name__)

_CLAIM_EVENTS = """
SELECT id, org_id, treasury_id, type, entity_type, entity_id, payload
FROM domain_events
WHERE published_at IS NULL AND failed_at IS NULL
ORDER BY created_at, id
LIMIT $1
FOR UPDATE SKIP LOCKED
"""

# One statement per event: resolve recipients and insert their notifications together.
_INSERT_NOTIFICATIONS = """
INSERT INTO notifications
    (id, org_id, user_id, event_id, type, title, body, link, severity)
SELECT gen_random_uuid(), $1, recipients.user_id, $2, $3, $4, $5, $6, $7
FROM (
    SELECT DISTINCT m.user_id
    FROM memberships AS m
    JOIN users AS u ON u.id = m.user_id
    WHERE m.org_id = $1
      AND m.status = 'active'
      AND u.status = 'active'
      AND (m.roles && $8::text[] OR m.user_id = ANY($9::uuid[]) OR m.user_id = $10)
      AND NOT (m.user_id = ANY($11::uuid[]))
) AS recipients
ON CONFLICT (user_id, event_id) DO NOTHING
"""

_MARK_PUBLISHED = """
UPDATE domain_events
SET published_at = now()
WHERE id = $1 AND published_at IS NULL
"""

_MARK_FAILED = """
UPDATE domain_events
SET failed_at = now(), last_error = $2
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


def _user_ids(payload: Mapping[str, Any], key: str | None) -> tuple[uuid.UUID, ...]:
    if key is None:
        return ()
    value = payload.get(key)
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ValueError(f"{key} must be an array of UUIDs")
    try:
        return tuple(dict.fromkeys(uuid.UUID(str(item)) for item in value))
    except ValueError as exc:
        raise ValueError(f"{key} must contain UUIDs") from exc


def _link(entity_type: str, entity_id: uuid.UUID, treasury_id: uuid.UUID | None) -> str:
    if entity_type == "payment_request":
        return f"/requests/{entity_id}"
    if treasury_id is not None:
        return f"/treasuries/{treasury_id}"
    return "/"


async def _route(connection: asyncpg.Connection, event: asyncpg.Record) -> None:
    policy = policy_for_event(event["type"])
    payload = _event_payload(event["payload"])
    roles = list(policy.roles)
    specific_user_ids = _user_ids(payload, policy.specific_user_ids_key)
    if policy.specific_user_ids_key is not None and not specific_user_ids:
        # e.g. a Safe signature with no named owners: never let it reach nobody.
        logger.warning(
            "notification_recipients_missing",
            extra={"event_id": str(event["id"]), "type": event["type"]},
        )
        roles = list(policy.fallback_roles)
    status = await connection.execute(
        _INSERT_NOTIFICATIONS,
        event["org_id"],
        event["id"],
        event["type"],
        policy.title,
        policy.body,
        _link(event["entity_type"], event["entity_id"], event["treasury_id"]),
        policy.severity,
        roles,
        list(specific_user_ids),
        _creator_id(policy, payload),
        # Maker-checker: people who cannot act on the event (e.g. the request's creator)
        list(_user_ids(payload, "excludeUserIds")),
    )
    if status.endswith(" 0"):
        logger.warning(
            "notification_without_recipients",
            extra={"event_id": str(event["id"]), "type": event["type"]},
        )
    await connection.execute(_MARK_PUBLISHED, event["id"])


async def publish_pending_events(connection: asyncpg.Connection, *, batch_size: int = 100) -> int:
    """Route a locked batch; concurrent publishers skip the locked rows.

    Each event runs in its own savepoint. One that cannot be routed is parked with
    ``failed_at``/``last_error`` (dead letter) and logged, so it can never block the
    events queued behind it.
    """

    if batch_size < 1:
        raise ValueError("batch_size must be positive")

    async with connection.transaction():
        events = await connection.fetch(_CLAIM_EVENTS, batch_size)
        for event in events:
            try:
                async with connection.transaction():
                    await _route(connection, event)
            except (ValueError, asyncpg.PostgresError) as error:
                logger.error(
                    "domain_event_dead_lettered",
                    extra={"event_id": str(event["id"]), "type": event["type"]},
                    exc_info=True,
                )
                await connection.execute(
                    _MARK_FAILED, event["id"], f"{type(error).__name__}: {error}"[:500]
                )
    return len(events)


async def publish_from_pool(pool: asyncpg.Pool, *, batch_size: int = 100) -> int:
    async with pool.acquire() as connection:
        return await publish_pending_events(connection, batch_size=batch_size)
