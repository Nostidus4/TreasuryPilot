"""Build the classified reconciliation of a Paid request (REC-002, M11 §8.2, BR-096).

Lines come only from Confirmed operations, so a refill whose PAY never succeeded yields no
EXTERNAL_EXPENSE (and, as the request is not Paid, no reconciliation at all). Every final
transaction's gas (``gas_ledger``, including reverted attempts) becomes a FEE line. Idempotent:
the sequencer calls it in the transaction that moves the request to Paid.
"""

from __future__ import annotations

from uuid import UUID

import asyncpg  # type: ignore[import-untyped]

_OPERATION_LINES = """
INSERT INTO reconciliation_lines (id, reconciliation_id, classification, operation_id,
    transaction_id, tx_hash, from_address, to_address, asset_address, amount, block_number, day)
SELECT gen_random_uuid(), $1,
    CASE o.kind WHEN 'REFILL' THEN 'INTERNAL_TRANSFER' WHEN 'SWAP' THEN 'CONVERSION'
        WHEN 'PAY' THEN 'EXTERNAL_EXPENSE' ELSE 'LENDING_TRANSFER' END,
    o.id, t.id, t.tx_hash, ps.from_address, ps.to_address, ps.asset_address, ps.amount,
    t.block_number, (t.confirmed_at AT TIME ZONE 'UTC')::date
FROM operations o
JOIN plan_steps ps ON ps.id = o.plan_step_id
JOIN transactions t ON t.operation_id = o.id AND t.status = 'Confirmed'
WHERE o.request_id = $2 AND o.status = 'Confirmed'
ON CONFLICT DO NOTHING
"""

_FEE_LINES = """
INSERT INTO reconciliation_lines (id, reconciliation_id, classification, operation_id,
    transaction_id, tx_hash, from_address, to_address, asset_address, amount, block_number, day)
SELECT gen_random_uuid(), $1, 'FEE', o.id, t.id, t.tx_hash, t.from_address, NULL, NULL,
    g.fee_wei, t.block_number, g.day
FROM operations o
JOIN transactions t ON t.operation_id = o.id
JOIN gas_ledger g ON g.transaction_id = t.id
WHERE o.request_id = $2
ON CONFLICT DO NOTHING
"""


async def build_reconciliation(connection: asyncpg.Connection, request_id: UUID) -> UUID | None:
    """The request's reconciliation id, or None while the request is not Paid."""

    await connection.execute(
        "INSERT INTO reconciliations (id, org_id, treasury_id, request_id, status) "
        "SELECT gen_random_uuid(), org_id, treasury_id, id, 'Pending' FROM payment_requests "
        "WHERE id = $1 AND status = 'Paid' ON CONFLICT (request_id) DO NOTHING",
        request_id,
    )
    reconciliation_id: UUID | None = await connection.fetchval(
        "SELECT id FROM reconciliations WHERE request_id = $1", request_id
    )
    if reconciliation_id is not None:
        await connection.execute(_OPERATION_LINES, reconciliation_id, request_id)
        await connection.execute(_FEE_LINES, reconciliation_id, request_id)
    return reconciliation_id
