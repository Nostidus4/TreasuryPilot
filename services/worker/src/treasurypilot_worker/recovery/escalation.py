"""Escalate overdue open review items to an Owner exactly once."""

from __future__ import annotations

import asyncpg  # type: ignore[import-untyped]

_ESCALATE_OVERDUE = """
WITH due AS (
    SELECT id
    FROM review_items
    WHERE status = 'Open'
      AND assigned_role <> 'Owner'
      AND sla_due_at <= now()
    ORDER BY sla_due_at, id
    LIMIT $1
    FOR UPDATE SKIP LOCKED
), escalated AS (
    UPDATE review_items AS item
    SET assigned_role = 'Owner', version = item.version + 1, updated_at = now()
    FROM due
    WHERE item.id = due.id
    RETURNING item.id, item.org_id, item.treasury_id, item.request_id
), emitted AS (
    INSERT INTO domain_events
        (id, org_id, treasury_id, type, entity_type, entity_id, payload)
    SELECT gen_random_uuid(), org_id, treasury_id, 'NeedsReview:Owner', 'review_item', id,
           jsonb_build_object('requestId', request_id::text, 'reviewItemId', id::text)
    FROM escalated
    RETURNING id
)
SELECT count(*) FROM emitted
"""


async def escalate_overdue_review_items(
    connection: asyncpg.Connection, *, batch_size: int = 100
) -> int:
    """Claim overdue rows and route them to Owner in one transaction."""
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    async with connection.transaction():
        return int(await connection.fetchval(_ESCALATE_OVERDUE, batch_size) or 0)


async def escalate_from_pool(pool: asyncpg.Pool, *, batch_size: int = 100) -> int:
    async with pool.acquire() as connection:
        return await escalate_overdue_review_items(connection, batch_size=batch_size)
