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

SCAN_LOCK_KEY = 0x7470_7363_616E  # "tpscan": one scan at a time across all workers
OPERATION_TIMEOUT_S = 30

ClientFactory = Callable[[Sequence[str]], RpcClient]


async def scan_in_flight(
    pool: asyncpg.Pool, *, client_factory: ClientFactory = build_rpc_client
) -> dict[str, int]:
    # Session-level lock: a scan that outlives its minute must not overlap the next one.
    async with pool.acquire() as lock_conn:
        if not await lock_conn.fetchval("SELECT pg_try_advisory_lock($1)", SCAN_LOCK_KEY):
            logger.info("in-flight scan already running; skipping")
            return {"scanned": 0, "blocked_treasuries": 0, "skipped": 1}
        try:
            return await _scan(pool, client_factory)
        finally:
            await lock_conn.execute("SELECT pg_advisory_unlock($1)", SCAN_LOCK_KEY)


async def _scan(pool: asyncpg.Pool, client_factory: ClientFactory) -> dict[str, int]:
    # NotSubmitted operations have no transaction yet; the executor owns them, not the scan.
    # No per-treasury advisory lock: resolve_operation's _close takes FOR UPDATE row locks and
    # re-checks state, which is what keeps it safe against the tracker and the executor.
    rows = await pool.fetch(
        "SELECT DISTINCT o.id, c.rpc_urls FROM operations o "
        "JOIN transactions t ON t.operation_id = o.id JOIN chains c ON c.chain_id = t.chain_id "
        "WHERE o.status = ANY($1::operation_status[]) ORDER BY o.id",
        TRACKED,
    )
    clients: dict[str, RpcClient] = {}
    for row in rows:
        key = str(row["rpc_urls"])
        if key not in clients:
            clients[key] = client_factory(decode_rpc_urls(row["rpc_urls"]))
        try:
            async with asyncio.timeout(OPERATION_TIMEOUT_S):
                await resolve_operation(pool, clients[key], row["id"])
        except Exception:
            # One bad or slow operation must not stall the others.
            logger.exception("resolving operation %s failed", row["id"])
    blocked = await pool.fetchval(
        "SELECT count(DISTINCT treasury_id) FROM operations WHERE status = 'Unknown'"
    )
    return {"scanned": len(rows), "blocked_treasuries": int(blocked), "skipped": 0}


def scan_in_flight_sync(database_url: str) -> dict[str, int]:
    async def run() -> dict[str, int]:
        pool = await create_worker_pool(database_url, min_size=1, max_size=2)
        try:
            return await scan_in_flight(pool)
        finally:
            await pool.close()

    return asyncio.run(run())
