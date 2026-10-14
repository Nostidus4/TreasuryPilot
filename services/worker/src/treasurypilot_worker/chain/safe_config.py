"""Periodic persistence of block-pinned Safe configuration snapshots."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

import asyncpg  # type: ignore[import-untyped]

from treasurypilot_worker.chain.rpc import (
    RpcClient,
    SafeConfig,
    build_rpc_client,
    safe_config_changed,
)
from treasurypilot_worker.locks import create_worker_pool

logger = logging.getLogger(__name__)

SafeConfigReader = Callable[[Sequence[str]], RpcClient]
EventPublisher = Callable[[asyncpg.Connection, Mapping[str, Any]], Awaitable[None]]


def _decode_rpc_urls(value: object) -> list[str]:
    """Normalize asyncpg's JSONB text result and validate configured provider URLs."""

    if isinstance(value, str):
        value = json.loads(value)
    if (
        not isinstance(value, list | tuple)
        or not value
        or any(not isinstance(url, str) or not url.strip() for url in value)
    ):
        raise ValueError("chain rpc_urls must be a non-empty list of URL strings")
    return list(value)


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
    treasury_id: uuid.UUID | None = None,
) -> int:
    """Read every configured Safe, persist snapshots, and publish configuration changes.

    ``treasury_id`` limits the run to one treasury (the event indexer's recompute).

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
                  AND ($1::uuid IS NULL OR w.treasury_id = $1)
                ORDER BY w.id
                """,
                treasury_id,
            )

        snapshots_written = 0
        failed_treasuries: set[uuid.UUID] = set()
        for wallet in wallets:
            try:
                rpc = reader_factory(_decode_rpc_urls(wallet["rpc_urls"]))
                safe_address = "0x" + bytes(wallet["safe_address"]).hex()
                safe_config = await rpc.safe_config(safe_address)
                snapshots_written += await _store_snapshot(
                    pool, wallet, safe_config, event_publisher=event_publisher
                )
            except Exception:
                # Malformed provider data (KeyError/TypeError) must also close the gate.
                logger.exception("safe config refresh failed for wallet %s", wallet["wallet_id"])
                await _mark_coverage_unknown(pool, wallet["treasury_id"])
                failed_treasuries.add(wallet["treasury_id"])
                continue
        # A later Safe can refresh after an earlier RPC failure and recompute from its
        # prior successful snapshot. Re-apply UNKNOWN at the end of the polling cycle.
        for treasury_id in failed_treasuries:
            await _mark_coverage_unknown(pool, treasury_id)
        return snapshots_written
    finally:
        await pool.close()


async def _mark_coverage_unknown(pool: asyncpg.Pool, treasury_id: uuid.UUID) -> None:
    """Close the execution gate immediately when any registered Safe cannot be read."""

    async with pool.acquire() as connection, connection.transaction():
        await connection.execute(
            """
            UPDATE treasuries
            SET coverage = 'UNKNOWN'::treasury_coverage,
                coverage_details = $2::jsonb,
                coverage_ack_by = NULL, coverage_ack_at = NULL, coverage_ack_reason = NULL,
                updated_at = now(), version = version + 1
            WHERE id = $1 AND (coverage IS DISTINCT FROM 'UNKNOWN'::treasury_coverage
              OR coverage_details IS DISTINCT FROM $2::jsonb OR coverage_ack_by IS NOT NULL)
            """,
            treasury_id,
            json.dumps(["Coverage is UNKNOWN: a Safe configuration RPC read failed."]),
        )


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
            SELECT owners, threshold, modules, guard, fallback_handler,
                   module_implementations, block_number, block_hash
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
                 modules, guard, fallback_handler, module_implementations)
            VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7, $8, $9, $10, $11::jsonb)
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
            bytes.fromhex(config.fallback_handler.removeprefix("0x"))
            if config.fallback_handler
            else None,
            json.dumps(
                {
                    module: implementation
                    for module, implementation in zip(
                        config.modules, config.module_implementations, strict=True
                    )
                }
            ),
        )
        if result.endswith(" 0"):
            # Same block re-delivered: no new snapshot, but staleness must still be re-evaluated.
            await _refresh_coverage(connection, wallet["treasury_id"])
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
        await _refresh_coverage(connection, wallet["treasury_id"])
        return 1


async def _refresh_coverage(connection: asyncpg.Connection, treasury_id: uuid.UUID) -> None:
    """Recompute a treasury after each successful snapshot (including 10-minute polling)."""

    rows = await connection.fetch(
        """
        SELECT t.module_address, implementation.address AS module_implementation,
               fallback.address AS fallback_handler, w.id AS wallet_id, w.label,
               s.modules, s.guard, s.fallback_handler AS observed_fallback,
               s.module_implementations, s.observed_at
        FROM treasuries AS t
        -- Newest registration wins so several versions of one deployment name never fan out rows.
        LEFT JOIN LATERAL (
            SELECT address FROM deployments
            WHERE chain_id = t.chain_id AND name = 'TREASURY_MODULE_IMPLEMENTATION'
            ORDER BY id DESC LIMIT 1
        ) AS implementation ON TRUE
        LEFT JOIN LATERAL (
            SELECT address FROM deployments
            WHERE chain_id = t.chain_id AND name = 'SAFE_FALLBACK_HANDLER'
            ORDER BY id DESC LIMIT 1
        ) AS fallback ON TRUE
        LEFT JOIN treasury_wallets AS w ON w.treasury_id = t.id
        LEFT JOIN LATERAL (
            SELECT modules, guard, fallback_handler, module_implementations, observed_at
            FROM safe_config_snapshots
            WHERE wallet_id = w.id AND org_id = w.org_id
            ORDER BY block_number DESC, observed_at DESC
            LIMIT 1
        ) AS s ON TRUE
        WHERE t.id = $1
        ORDER BY w.id
        """,
        treasury_id,
    )
    if not rows:
        return
    module_address = rows[0]["module_address"]
    expected_module = bytes(module_address) if module_address else None
    wallet_rows = [row for row in rows if row["wallet_id"] is not None]
    expected_implementation = (
        bytes(rows[0]["module_implementation"]) if rows[0]["module_implementation"] else None
    )
    expected_fallback = bytes(rows[0]["fallback_handler"]) if rows[0]["fallback_handler"] else None
    details: list[str] = []
    all_complete = expected_module is not None
    any_unknown = not wallet_rows or expected_module is None
    if not wallet_rows:
        details.append("Coverage is UNKNOWN: the treasury has no registered Safes.")
    if expected_module is None:
        details.append("Coverage is UNKNOWN: the treasury module is not deployed yet.")
    if expected_implementation is None or expected_fallback is None:
        any_unknown = True
        missing = (
            "TREASURY_MODULE_IMPLEMENTATION"
            if expected_implementation is None
            else "SAFE_FALLBACK_HANDLER"
        )
        details.append(f"Coverage is UNKNOWN: {missing} is not configured for this chain.")
    now = datetime.now(UTC)
    max_age = timedelta(minutes=12)
    for row in wallet_rows:
        modules = row["modules"]
        if modules is None or row["observed_at"] is None or now - row["observed_at"] > max_age:
            any_unknown = True
            all_complete = False
            details.append(f"{row['label']}: no recent Safe configuration snapshot.")
            continue
        modules = [bytes(module) for module in modules]
        implementations = row["module_implementations"] or {}
        if isinstance(implementations, str):
            implementations = json.loads(implementations)
        module_key = "0x" + expected_module.hex() if expected_module else ""
        clone_target = implementations.get(module_key)
        if expected_module is None or modules != [expected_module]:
            all_complete = False
            details.append(f"{row['label']}: enabled modules do not equal the treasury module.")
        elif (
            expected_implementation is not None
            and clone_target != "0x" + expected_implementation.hex()
        ):
            all_complete = False
            details.append(
                f"{row['label']}: treasury module is not an EIP-1167 clone of the configured "
                "implementation."
            )
        if row["guard"] is not None:
            all_complete = False
            details.append(f"{row['label']}: an unexpected guard is enabled.")
        if expected_fallback is not None and row["observed_fallback"] != expected_fallback:
            all_complete = False
            details.append(
                f"{row['label']}: fallback handler is not the configured canonical handler."
            )

    if any_unknown:
        status = "UNKNOWN"
    elif all_complete:
        status = "COMPLETE"
        details.append("All registered Safes match the configured TreasuryPilot module policy.")
    else:
        status = "PARTIAL"
        if not details:
            details.append("Safe configuration does not satisfy the coverage policy.")
    await connection.execute(
        """
        UPDATE treasuries
        SET coverage = $2::treasury_coverage, coverage_details = $3::jsonb,
            -- An acknowledgment covers exactly the reviewed deviations: any change clears it.
            coverage_ack_by = CASE WHEN $2 = 'PARTIAL' AND coverage_details = $3::jsonb
                                   THEN coverage_ack_by ELSE NULL END,
            coverage_ack_at = CASE WHEN $2 = 'PARTIAL' AND coverage_details = $3::jsonb
                                   THEN coverage_ack_at ELSE NULL END,
            coverage_ack_reason = CASE WHEN $2 = 'PARTIAL' AND coverage_details = $3::jsonb
                                       THEN coverage_ack_reason ELSE NULL END,
            updated_at = now(), version = version + 1
        WHERE id = $1 AND (coverage IS DISTINCT FROM $2::treasury_coverage
          OR coverage_details IS DISTINCT FROM $3::jsonb)
        """,
        treasury_id,
        status,
        json.dumps(details),
    )


def refresh_safe_config_snapshots_sync(database_url: str) -> int:
    """Synchronous entrypoint for Celery's prefork worker."""

    return asyncio.run(refresh_safe_config_snapshots(database_url))
