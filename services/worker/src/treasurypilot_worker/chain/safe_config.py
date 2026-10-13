"""Periodic persistence of block-pinned Safe configuration snapshots."""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any

import asyncpg  # type: ignore[import-untyped]

from treasurypilot_worker.chain.rpc import (
    RpcClient,
    SafeConfig,
    build_rpc_client,
    safe_config_changed,
)
from treasurypilot_worker.locks import create_worker_pool

SafeConfigReader = Callable[[Sequence[str]], RpcClient]
EventPublisher = Callable[[asyncpg.Connection, Mapping[str, Any]], Awaitable[None]]


async def publish_safe_config_changed(
    connection: asyncpg.Connection, payload: Mapping[str, Any]
) -> None:
    """Publish a transaction-scoped notification for the domain-event outbox adapter.

    The notifications service can consume this boundary and persist its canonical
    ``domain_events`` row. PostgreSQL delivers the notification only on commit.
    """

    await connection.execute(
        "SELECT pg_notify('safe_config_changed', $1)", json.dumps(dict(payload), sort_keys=True)
    )


async def refresh_safe_config_snapshots(
    database_url: str,
    *,
    reader_factory: SafeConfigReader = build_rpc_client,
    event_publisher: EventPublisher = publish_safe_config_changed,
) -> int:
    """Read every configured Safe, persist snapshots, and publish configuration changes.

    Returns the number of new block snapshots. Re-deliveries at the same block are
    idempotent, and per-wallet advisory locks serialize overlapping beat/task runs.
    """

    pool = await create_worker_pool(database_url)
    try:
        async with pool.acquire() as connection:
            wallets = await connection.fetch(
                """
                SELECT w.id AS wallet_id, w.org_id, w.treasury_id, w.safe_address,
                       c.rpc_urls
                FROM treasury_wallets AS w
                JOIN chains AS c ON c.chain_id = w.chain_id
                JOIN treasuries AS t ON t.id = w.treasury_id
                WHERE c.enabled AND t.status <> 'Revoked'
                ORDER BY w.id
                """
            )

        snapshots_written = 0
        for wallet in wallets:
            rpc = reader_factory(wallet["rpc_urls"])
            safe_address = "0x" + bytes(wallet["safe_address"]).hex()
            safe_config = await rpc.safe_config(safe_address)
            snapshots_written += await _store_snapshot(
                pool, wallet, safe_config, event_publisher=event_publisher
            )
        return snapshots_written
    finally:
        await pool.close()


async def _store_snapshot(
    pool: asyncpg.Pool,
    wallet: Mapping[str, Any],
    config: SafeConfig,
    *,
    event_publisher: EventPublisher,
) -> int:
    wallet_id = wallet["wallet_id"]
    org_id = wallet["org_id"]
    async with pool.acquire() as connection, connection.transaction():
        await connection.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended($1, 0))", f"safe-config:{wallet_id}"
        )
        previous = await connection.fetchrow(
            """
            SELECT owners, threshold, modules, guard, block_number, block_hash
            FROM safe_config_snapshots
            WHERE wallet_id = $1 AND org_id = $2
            ORDER BY block_number DESC, observed_at DESC
            LIMIT 1
            """,
            wallet_id,
            org_id,
        )
        result = await connection.execute(
            """
            INSERT INTO safe_config_snapshots
                (id, org_id, wallet_id, block_number, block_hash, owners, threshold,
                 modules, guard)
            VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7, $8, $9)
            ON CONFLICT (wallet_id, block_number, block_hash) DO NOTHING
            """,
            uuid.uuid4(),
            org_id,
            wallet_id,
            config.block_number,
            bytes.fromhex(config.block_hash.removeprefix("0x")),
            json.dumps(list(config.owners)),
            config.threshold,
            [bytes.fromhex(module.removeprefix("0x")) for module in config.modules],
            bytes.fromhex(config.guard.removeprefix("0x")) if config.guard else None,
        )
        if result.endswith(" 0"):
            return 0

        if previous is not None and safe_config_changed(previous, config):
            await event_publisher(
                connection,
                {
                    "type": "SafeConfigChanged",
                    "orgId": str(org_id),
                    "treasuryId": str(wallet["treasury_id"]),
                    "walletId": str(wallet_id),
                    "blockNumber": config.block_number,
                },
            )
        return 1


def refresh_safe_config_snapshots_sync(database_url: str) -> int:
    """Synchronous entrypoint for Celery's prefork worker."""

    return asyncio.run(refresh_safe_config_snapshots(database_url))
