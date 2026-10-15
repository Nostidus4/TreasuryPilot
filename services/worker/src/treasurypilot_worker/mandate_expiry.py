"""Mandate lifecycle expiry sweep (MDT-008)."""

from __future__ import annotations

import asyncpg  # type: ignore[import-untyped]

_WARN_EXPIRING = """
WITH due AS (
    SELECT m.id AS mandate_version_id, m.org_id, m.treasury_id,
           min(w.warning_hours) AS warning_hours
    FROM mandate_versions AS m
    CROSS JOIN (VALUES (168::smallint), (48::smallint), (1::smallint)) AS w(warning_hours)
    WHERE m.status = 'Active'
      AND m.expires_at > now()
      AND m.expires_at <= now() + make_interval(hours => w.warning_hours)
    GROUP BY m.id, m.org_id, m.treasury_id
), claimed AS (
    INSERT INTO mandate_expiry_notifications (mandate_version_id, org_id, warning_hours)
    SELECT mandate_version_id, org_id, warning_hours FROM due
    ON CONFLICT (mandate_version_id, warning_hours) DO NOTHING
    RETURNING mandate_version_id, org_id, warning_hours
)
INSERT INTO domain_events (id, org_id, treasury_id, type, entity_type, entity_id, payload)
SELECT gen_random_uuid(), c.org_id, m.treasury_id, 'MandateExpiring', 'treasury', m.treasury_id,
       jsonb_build_object('mandateVersionId', c.mandate_version_id::text)
FROM claimed AS c
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
        (id, org_id, mandate_version_id, "from", "to", tx_hash, by_user_id)
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


async def expire_mandates(connection: asyncpg.Connection) -> dict[str, int]:
    """Emit each configured warning once, then expire active mandates atomically."""

    async with connection.transaction():
        warnings = await connection.fetch(_WARN_EXPIRING)
        expired = await connection.fetch(_EXPIRE)
    return {"warnings_emitted": len(warnings), "mandates_expired": len(expired)}
