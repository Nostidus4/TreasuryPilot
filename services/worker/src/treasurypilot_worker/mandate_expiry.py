"""Mandate lifecycle expiry sweep (MDT-008)."""

from __future__ import annotations

import asyncpg  # type: ignore[import-untyped]

_LOCK_KEY = 0x4D44545F455850  # "MDT_EXP"
_LIMITS = "SET LOCAL lock_timeout = '5s'; SET LOCAL statement_timeout = '30s'"

_WARN_EXPIRING = """
WITH due AS (
    SELECT m.id AS mandate_version_id, m.org_id, m.treasury_id,
           w.warning_hours
    FROM mandate_versions AS m
    CROSS JOIN (VALUES (168::smallint), (48::smallint), (1::smallint)) AS w(warning_hours)
    WHERE m.status = 'Active'
      AND m.expires_at > now()
      AND m.expires_at <= now() + make_interval(hours => w.warning_hours)
    GROUP BY m.id, m.org_id, m.treasury_id, w.warning_hours
), claimed AS (
    INSERT INTO mandate_expiry_notifications (mandate_version_id, org_id, warning_hours)
    SELECT mandate_version_id, org_id, warning_hours FROM due
    ON CONFLICT (mandate_version_id, warning_hours) DO NOTHING
    RETURNING mandate_version_id, org_id, warning_hours
)
INSERT INTO domain_events (id, org_id, treasury_id, type, entity_type, entity_id, payload)
SELECT gen_random_uuid(), c.org_id, m.treasury_id, 'MandateExpiring', 'treasury', m.treasury_id,
       jsonb_build_object(
           'mandateVersionId', c.mandate_version_id::text, 'warningHours', c.warning_hours
       )
FROM (
    SELECT DISTINCT ON (mandate_version_id) mandate_version_id, org_id, warning_hours
    FROM claimed
    ORDER BY mandate_version_id, warning_hours
) AS c
JOIN mandate_versions AS m ON m.id = c.mandate_version_id AND m.org_id = c.org_id
RETURNING id
"""

_EXPIRE = """
WITH expired AS (
    UPDATE mandate_versions
    SET status = 'Expired'
    WHERE status = 'Active' AND expires_at <= now()
    RETURNING id, org_id, treasury_id
), history AS (
    INSERT INTO mandate_status_events
        (id, org_id, mandate_version_id, from_status, to_status, tx_hash, by_user_id)
    SELECT gen_random_uuid(), org_id, id, 'Active', 'Expired', NULL, NULL
    FROM expired
    RETURNING mandate_version_id, org_id
)
INSERT INTO domain_events (id, org_id, treasury_id, type, entity_type, entity_id, payload)
SELECT gen_random_uuid(), h.org_id, m.treasury_id, 'MandateExpired', 'treasury', m.treasury_id,
       jsonb_build_object('mandateVersionId', h.mandate_version_id::text)
FROM history AS h
JOIN mandate_versions AS m ON m.id = h.mandate_version_id AND m.org_id = h.org_id
RETURNING id
"""


async def _phase(connection: asyncpg.Connection, sql: str) -> int:
    async with connection.transaction():
        await connection.execute(_LIMITS)
        if not await connection.fetchval("SELECT pg_try_advisory_xact_lock($1)", _LOCK_KEY):
            return 0  # an overlapping sweep holds the lock; the next tick retries
        return len(await connection.fetch(sql))


async def expire_mandates(connection: asyncpg.Connection) -> dict[str, int]:
    """Emit the tightest due warning once per mandate, then expire lapsed active mandates.

    The phases run in separate transactions so a warning failure never blocks expiry.
    """

    warnings = await _phase(connection, _WARN_EXPIRING)
    expired = await _phase(connection, _EXPIRE)
    return {"warnings_emitted": warnings, "mandates_expired": expired}
