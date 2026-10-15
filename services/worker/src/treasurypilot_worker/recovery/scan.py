"""Scan in-flight operations and resolve them from chain evidence (RCV-001, M12 §7.1, BR-060).

Runs on every worker start and every 60 s. A treasury with an Unknown operation is blocked
without any flag of its own: the execution cycle skips it while ``operations.status`` is Unknown
(``trigger.cycles``), and this scan is what moves such operations on or escalates them.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Sequence

import asyncpg  # type: ignore[import-untyped]

from treasurypilot_worker.chain.rpc import RpcClient, build_rpc_client, decode_rpc_urls
from treasurypilot_worker.locks import create_worker_pool
from treasurypilot_worker.recovery.resolve import resolve_operation
from treasurypilot_worker.tracker.track import TRACKED

logger = logging.getLogger(__name__)

ClientFactory = Callable[[Sequence[str]], RpcClient]


async def scan_in_flight(
    pool: asyncpg.Pool, *, client_factory: ClientFactory = build_rpc_client
) -> dict[str, int]:
    # NotSubmitted operations have no transaction yet; the executor owns them, not the scan.
    rows = await pool.fetch(
        "SELECT DISTINCT o.id, c.rpc_urls FROM operations o "
        "JOIN transactions t ON t.operation_id = o.id JOIN chains c ON c.chain_id = t.chain_id "
        "WHERE o.status = ANY($1::operation_status[]) ORDER BY o.id",
        TRACKED,
    )
    clients: dict[str, RpcClient] = {}
    for row in rows:
        client = clients.setdefault(
            str(row["rpc_urls"]), client_factory(decode_rpc_urls(row["rpc_urls"]))
        )
        try:
            await resolve_operation(pool, client, row["id"])
        except Exception:
            # One bad operation must not stall the others.
            logger.exception("resolving operation %s failed", row["id"])
    blocked = await pool.fetchval(
        "SELECT count(DISTINCT treasury_id) FROM operations WHERE status = 'Unknown'"
    )
    return {"scanned": len(rows), "blocked_treasuries": int(blocked)}


def scan_in_flight_sync(database_url: str) -> dict[str, int]:
    async def run() -> dict[str, int]:
        pool = await create_worker_pool(database_url, min_size=1, max_size=2)
        try:
            return await scan_in_flight(pool)
        finally:
            await pool.close()

    return asyncio.run(run())
