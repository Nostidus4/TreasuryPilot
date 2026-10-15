"""Verification discrepancies and auto-match of Pending reconciliations (REC-003, M11 §7-§8.3).

Auto-match only runs for organizations that turned the setting on (default off, M11-D3) and
applies the same evidence rule as the manual match, plus the strict checks of §8.3.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

import asyncpg  # type: ignore[import-untyped]

from treasurypilot_core.reconciliation_evidence import (
    FACTS_SQL,
    ReconciliationFacts,
    is_finalized,
    missing_evidence,
)
from treasurypilot_worker.audit import append_audit

logger = logging.getLogger(__name__)

_RPC_TIMEOUT = 15.0  # seconds per finalized-block read
_FACTS = FACTS_SQL.replace(":rid", "$1")

# A DISCREPANCY verdict on any operation of the request makes the reconciliation a Discrepancy.
_FLAG_DISCREPANCIES = """
UPDATE reconciliations r SET status = 'Discrepancy', version = version + 1,
    note = 'Post-condition verification reported a DISCREPANCY'
WHERE r.id IN (
    SELECT r2.id FROM reconciliations r2 WHERE r2.status = 'Pending' AND EXISTS (
        SELECT 1 FROM verifications v JOIN operations o ON o.id = v.operation_id
        WHERE o.request_id = r2.request_id AND v.result = 'DISCREPANCY')
    FOR UPDATE SKIP LOCKED)
RETURNING r.id, r.org_id
"""

_CANDIDATES = """
SELECT r.id, r.org_id, q.chain_id FROM reconciliations r
JOIN organizations org ON org.id = r.org_id AND org.auto_match
JOIN payment_requests q ON q.id = r.request_id
WHERE r.status = 'Pending' ORDER BY r.created_at
"""

_MATCH = """
UPDATE reconciliations SET status = 'Matched', matched_by = 'AUTO', matched_at = now(),
    finalized_at = now(), version = version + 1
WHERE id = $1 AND status = 'Pending'
"""

FinalizedBlock = Callable[[int], Awaitable[int]]


async def auto_match_reconciliations(
    pool: asyncpg.Pool, finalized_block: FinalizedBlock
) -> dict[str, int]:
    async with pool.acquire() as connection, connection.transaction():
        flagged_rows = await connection.fetch(_FLAG_DISCREPANCIES)
        for flagged_row in flagged_rows:
            await append_audit(
                connection,
                flagged_row["org_id"],
                action="reconciliation.discrepancy_flagged",
                entity_type="reconciliation",
                entity_id=str(flagged_row["id"]),
                data={"source": "verification"},
            )
    flagged = len(flagged_rows)
    matched = 0
    finalized: dict[int, int | None] = {}
    for candidate in await pool.fetch(_CANDIDATES):
        chain_id = candidate["chain_id"]
        if chain_id not in finalized:
            try:
                finalized[chain_id] = await asyncio.wait_for(
                    finalized_block(chain_id), _RPC_TIMEOUT
                )
            except Exception:  # an unreadable chain only delays its matches
                logger.warning("finalized block unavailable for chain %s", chain_id, exc_info=True)
                finalized[chain_id] = None
        if (head := finalized[chain_id]) is None:
            continue
        async with pool.acquire() as connection, connection.transaction():
            locked = await connection.fetchval(
                "SELECT status FROM reconciliations WHERE id = $1 FOR UPDATE SKIP LOCKED",
                candidate["id"],
            )
            if locked != "Pending":
                continue
            facts = ReconciliationFacts(**dict(await connection.fetchrow(_FACTS, candidate["id"])))
            if missing_evidence(facts, strict=True) or not is_finalized(facts, head):
                continue
            await connection.execute(_MATCH, candidate["id"])
            await append_audit(
                connection,
                candidate["org_id"],
                action="reconciliation.matched",
                entity_type="reconciliation",
                entity_id=str(candidate["id"]),
                data={"matchedBy": "AUTO"},
            )
            matched += 1
    return {"discrepancies_flagged": flagged, "auto_matched": matched}
