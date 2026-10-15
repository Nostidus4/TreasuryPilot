"""Append one record to an organization's hash-chained ``audit_log`` from the worker.

The worker cannot import the API (services are independent), so this repeats the API writer's
hashing (``treasurypilot_api.audit.chain.compute_hash``): sha256 of the canonical JSON of the
record, with ``prev_hash`` as lowercase hex. A test verifies worker-written rows with the API's
``verify_chain``. ``data`` must already be JSON-native (str, int, bool, None, lists, dicts): no
floats, no Decimals. Call it last in the transaction; it locks the org's audit head until commit.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any

import asyncpg  # type: ignore[import-untyped]


async def append_audit(
    connection: asyncpg.Connection,
    org_id: uuid.UUID,
    *,
    action: str,
    entity_type: str,
    entity_id: str,
    data: dict[str, Any],
) -> None:
    head = await connection.fetchrow(
        "SELECT last_hash FROM audit_heads WHERE org_id = $1 FOR UPDATE", org_id
    )
    if head is None:
        raise RuntimeError(f"organization {org_id} has no audit head")
    seq = await connection.fetchval("SELECT nextval(pg_get_serial_sequence('audit_log', 'seq'))")
    prev_hash = bytes(head["last_hash"])
    at = datetime.now(UTC)
    record = {
        "seq": seq,
        "org_id": str(org_id),
        "at": at.isoformat().replace("+00:00", "Z"),
        "actor_type": "SYSTEM",
        "actor_id": None,
        "action": action,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "data": data,
        "prev_hash": prev_hash.hex(),
    }
    digest = hashlib.sha256(
        json.dumps(
            record, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode()
    ).digest()
    await connection.execute(
        "INSERT INTO audit_log (seq, org_id, at, actor_type, actor_id, action, entity_type, "
        "entity_id, data, prev_hash, hash) OVERRIDING SYSTEM VALUE "
        "VALUES ($1, $2, $3, 'SYSTEM', NULL, $4, $5, $6, $7::jsonb, $8, $9)",
        seq,
        org_id,
        at,
        action,
        entity_type,
        entity_id,
        json.dumps(data),
        prev_hash,
        digest,
    )
    await connection.execute(
        "UPDATE audit_heads SET last_seq = $2, last_hash = $3 WHERE org_id = $1",
        org_id,
        seq,
        digest,
    )
