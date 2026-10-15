"""Executor low-gas sweep (EXE-010): emit a LowGas domain event below the balance threshold."""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

import asyncpg  # type: ignore[import-untyped]

logger = logging.getLogger(__name__)

# Per treasury: the chain's RPC URLs and every address that sent a tx in the last 30 days.
_TREASURIES = """
SELECT t.id AS treasury_id, t.org_id, c.rpc_urls,
       COALESCE(array_agg(DISTINCT tx.from_address) FILTER (WHERE tx.id IS NOT NULL), '{}')
           AS senders
FROM treasuries AS t
JOIN chains AS c ON c.chain_id = t.chain_id
LEFT JOIN operations AS o ON o.treasury_id = t.id
LEFT JOIN transactions AS tx ON tx.operation_id = o.id AND tx.submitted_at > now() - interval '30 days'
GROUP BY t.id, t.org_id, c.chain_id
"""

# One alert per treasury and address per 24 h while it stays low. The advisory lock makes the
# check-then-insert atomic across overlapping sweeps.
_LOCK = "SELECT pg_advisory_xact_lock(hashtextextended('low_gas:' || $1::uuid::text || $2, 0))"
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
    connection: asyncpg.Connection,
    rpc_for: Callable[[Any], Any],
    threshold_wei: int,
    configured: Sequence[tuple[str, str | None]] = (),
) -> dict[str, int]:
    """``rpc_for(rpc_urls)`` returns an RpcClient; balances are read with ``eth_getBalance``.

    ``configured`` is ``(role, address)`` pairs checked for every treasury even if they never sent
    a tx (cold start); senders seen in the last 30 days are checked as role "executor".
    """

    emitted = checked = failed = 0
    for row in await connection.fetch(_TREASURIES):
        roles: dict[str, str] = {a.lower(): role for role, a in configured if a}
        for sender in row["senders"]:
            roles.setdefault("0x" + bytes(sender).hex(), "executor")
        for address, role in roles.items():
            try:
                call: Awaitable[Any] = rpc_for(row["rpc_urls"]).call(
                    "eth_getBalance", [address, "latest"]
                )
                balance = int(await call, 16)
            except Exception as error:  # one bad address or RPC must not hide the others
                failed += 1
                logger.warning("low-gas balance check failed for %s: %s", address, error)
                continue
            checked += 1
            if balance >= threshold_wei:
                continue
            payload = {
                "role": role,
                "address": address,
                "balanceWei": str(balance),
                "thresholdWei": str(threshold_wei),
            }
            async with connection.transaction():
                await connection.execute(_LOCK, row["treasury_id"], address)
                emitted += len(
                    await connection.fetch(
                        _EMIT, row["org_id"], row["treasury_id"], json.dumps(payload), address
                    )
                )
    return {"checked": checked, "emitted": emitted, "failed": failed}
