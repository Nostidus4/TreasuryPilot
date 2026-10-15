"""Executor low-gas sweep (EXE-010): emit a LowGas domain event below the balance threshold."""

from __future__ import annotations

import json
from typing import Any

import asyncpg  # type: ignore[import-untyped]

# Executors seen sending in the last 30 days, with the chain's RPC URLs.
_EXECUTORS = """
SELECT DISTINCT t.id AS treasury_id, t.org_id, tx.from_address, c.rpc_urls
FROM transactions AS tx
JOIN operations AS o ON o.id = tx.operation_id
JOIN treasuries AS t ON t.id = o.treasury_id
JOIN chains AS c ON c.chain_id = t.chain_id
WHERE tx.submitted_at > now() - interval '30 days'
"""

# One alert per executor per 24 h while it stays low.
_EMIT = """
INSERT INTO domain_events (id, org_id, treasury_id, type, entity_type, entity_id, payload)
SELECT gen_random_uuid(), $1, $2, 'LowGas', 'treasury', $2, $3::jsonb
WHERE NOT EXISTS (
    SELECT 1 FROM domain_events
    WHERE treasury_id = $2 AND type = 'LowGas' AND payload ->> 'address' = $4
      AND created_at > now() - interval '24 hours'
)
RETURNING id
"""


async def check_low_gas(
    connection: asyncpg.Connection, rpc_for: Any, threshold_wei: int
) -> dict[str, int]:
    """``rpc_for(rpc_urls)`` returns an RpcClient; balances are read with ``eth_getBalance``."""

    emitted = checked = 0
    for row in await connection.fetch(_EXECUTORS):
        address = "0x" + bytes(row["from_address"]).hex()
        balance = int(
            await rpc_for(row["rpc_urls"]).call("eth_getBalance", [address, "latest"]), 16
        )
        checked += 1
        if balance >= threshold_wei:
            continue
        payload = {
            "role": "executor",
            "address": address,
            "balanceWei": str(balance),
            "thresholdWei": str(threshold_wei),
        }
        emitted += len(
            await connection.fetch(
                _EMIT, row["org_id"], row["treasury_id"], json.dumps(payload), address
            )
        )
    return {"checked": checked, "emitted": emitted}
