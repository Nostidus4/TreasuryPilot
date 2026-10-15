"""Cursor-based ``eth_getLogs`` indexer with reorg re-scan (M06 §8.3, PH-6).

One cursor per (treasury, stream). Every run re-reads the last 64 blocks, upserts logs by
(chain, tx hash, log index), marks stored logs that vanished from the window as ``removed``,
and hands new or changed logs to the subscriber registry in the same transaction.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import Sequence
from typing import Any, Final

import asyncpg  # type: ignore[import-untyped]

from treasurypilot_worker.chain.event_handlers import HandlerRegistry, IndexedEvent, registry
from treasurypilot_worker.chain.events import (
    EVENTS,
    MODULE,
    SAFE_CONFIG,
    SAFE_EXEC,
    TOKEN,
    decode_log,
)
from treasurypilot_worker.chain.rpc import RpcClient, build_rpc_client, decode_rpc_urls
from treasurypilot_worker.chain.safe_config import SafeConfigReader, refresh_safe_config_snapshots
from treasurypilot_worker.locks import create_worker_pool

REORG_WINDOW: Final = 64
CHUNK_BLOCKS: Final = 2000
# Bounds one run's memory and RPC time while a new treasury catches up.
MAX_CHUNKS_PER_RUN: Final = 50

logger = logging.getLogger(__name__)


async def index_events(
    database_url: str,
    *,
    client_factory: SafeConfigReader = build_rpc_client,
    handlers: HandlerRegistry = registry,
) -> dict[str, int]:
    """Index every treasury's streams once; returns how many logs changed state."""

    pool = await create_worker_pool(database_url, min_size=1, max_size=2)
    try:
        treasuries = await pool.fetch(
            "SELECT t.id, t.chain_id, t.module_address, asset.address AS asset_address, c.rpc_urls, "
            "COALESCE(array_agg(w.safe_address) FILTER (WHERE w.id IS NOT NULL), '{}') AS safes "
            "FROM treasuries t JOIN chains c USING (chain_id) "
            "JOIN assets AS asset ON asset.id = t.asset_id "
            "LEFT JOIN treasury_wallets w ON w.treasury_id = t.id "
            "WHERE c.enabled AND t.module_address IS NOT NULL AND t.status <> 'Revoked' "
            "GROUP BY t.id, c.rpc_urls, asset.address ORDER BY t.id"
        )
        changed = 0
        for treasury in treasuries:
            urls = treasury["rpc_urls"]
            rpc = client_factory(decode_rpc_urls(urls))
            addresses = {
                MODULE: [bytes(treasury["module_address"])],
                SAFE_CONFIG: [bytes(safe) for safe in treasury["safes"]],
                SAFE_EXEC: [bytes(safe) for safe in treasury["safes"]],
                TOKEN: [bytes(treasury["asset_address"])]
                if treasury["asset_address"] is not None
                else [],
            }
            for stream, stream_addresses in addresses.items():
                if not stream_addresses:
                    continue
                try:
                    count = await _index_stream(
                        pool, rpc, treasury, stream, stream_addresses, handlers
                    )
                    if stream == SAFE_CONFIG and count:
                        # Re-read the Safes so coverage reflects the new guard/modules/owners.
                        await refresh_safe_config_snapshots(
                            database_url,
                            reader_factory=client_factory,
                            treasury_id=treasury["id"],
                        )
                    changed += count
                except Exception:
                    # One failing stream or provider answer must not stall the others.
                    logger.exception("indexing %s of treasury %s failed", stream, treasury["id"])
        return {"changed": changed}
    finally:
        await pool.close()


def index_events_sync(database_url: str) -> dict[str, int]:
    return asyncio.run(index_events(database_url))


async def _index_stream(
    pool: asyncpg.Pool,
    rpc: RpcClient,
    treasury: asyncpg.Record,
    stream: str,
    addresses: Sequence[bytes],
    handlers: HandlerRegistry,
) -> int:
    treasury_id: uuid.UUID = treasury["id"]
    chain_id: int = treasury["chain_id"]
    abis = EVENTS[stream]
    async with pool.acquire() as connection, connection.transaction():
        # Overlapping runs would double-dispatch; the next beat simply retries.
        if not await connection.fetchval(
            "SELECT pg_try_advisory_xact_lock(hashtextextended($1, 0))",
            f"index:{treasury_id}:{stream}",
        ):
            return 0
        head = int(await rpc.call("eth_blockNumber", []), 16)
        cursor = await connection.fetchval(
            "SELECT last_block FROM index_cursors WHERE treasury_id = $1 AND stream = $2::index_stream",
            treasury_id,
            stream,
        )
        if cursor is None:
            start = await _first_code_block(rpc, bytes(treasury["module_address"]), head)
        else:
            start = max(cursor - REORG_WINDOW, 0)
        end = min(head, start + MAX_CHUNKS_PER_RUN * CHUNK_BLOCKS - 1)
        if start > end:
            return 0

        # The node's address filter is exact; the re-check below guards a misbehaving provider.
        wanted = {"0x" + address.hex() for address in addresses}
        topic_filter: list[Any] = [list(abis)]
        recipients: set[str] = set()
        if stream == TOKEN:
            # Token Transfers are unbounded; only those into the treasury's Safes matter.
            recipients = {"0x" + bytes(safe).hex().rjust(64, "0") for safe in treasury["safes"]}
            if not recipients:
                return 0
            topic_filter += [None, sorted(recipients)]
        logs: list[dict[str, Any]] = []
        for low in range(start, end + 1, CHUNK_BLOCKS):
            logs += await rpc.call(
                "eth_getLogs",
                [
                    {
                        "fromBlock": hex(low),
                        "toBlock": hex(min(low + CHUNK_BLOCKS - 1, end)),
                        "address": sorted(wanted),
                        "topics": topic_filter,
                    }
                ],
            )

        events: list[IndexedEvent] = []
        seen: set[tuple[bytes, int]] = set()
        for log in logs:
            topics = [str(topic).lower() for topic in log["topics"]]
            if (
                log.get("removed")
                or str(log["address"]).lower() not in wanted
                or not topics
                or topics[0] not in abis
                or (recipients and (len(topics) < 3 or topics[2] not in recipients))
            ):
                continue
            abi = abis[topics[0]]
            tx_hash = bytes.fromhex(log["transactionHash"][2:])
            log_index = int(log["logIndex"], 16)
            seen.add((tx_hash, log_index))
            payload = decode_log(abi, log)
            changed = await connection.fetchval(
                "INSERT INTO observed_events (id, treasury_id, chain_id, stream, block_number, "
                "block_hash, tx_hash, log_index, address, event_name, payload) "
                "VALUES ($1, $2, $3, $4::index_stream, $5, $6, $7, $8, $9, $10, $11::jsonb) "
                "ON CONFLICT (chain_id, tx_hash, log_index) DO UPDATE SET "
                "block_number = EXCLUDED.block_number, block_hash = EXCLUDED.block_hash, "
                "removed = false WHERE observed_events.removed "
                "OR observed_events.block_hash <> EXCLUDED.block_hash RETURNING true",
                uuid.uuid4(),
                treasury_id,
                chain_id,
                stream,
                int(log["blockNumber"], 16),
                bytes.fromhex(log["blockHash"][2:]),
                tx_hash,
                log_index,
                bytes.fromhex(log["address"][2:]),
                abi.name,
                json.dumps(payload),
            )
            if changed:
                events.append(
                    IndexedEvent(
                        treasury_id,
                        chain_id,
                        stream,
                        abi.name,
                        bytes.fromhex(log["address"][2:]),
                        tx_hash,
                        log_index,
                        int(log["blockNumber"], 16),
                        payload,
                    )
                )

        vanished = await connection.fetch(
            "SELECT tx_hash, log_index, address, event_name, payload, block_number "
            "FROM observed_events WHERE treasury_id = $1 AND stream = $2::index_stream "
            "AND block_number BETWEEN $3 AND $4 AND NOT removed",
            treasury_id,
            stream,
            start,
            end,
        )
        for row in vanished:
            if (bytes(row["tx_hash"]), row["log_index"]) in seen:
                continue
            await connection.execute(
                "UPDATE observed_events SET removed = true "
                "WHERE chain_id = $1 AND tx_hash = $2 AND log_index = $3",
                chain_id,
                row["tx_hash"],
                row["log_index"],
            )
            payload = row["payload"]
            events.append(
                IndexedEvent(
                    treasury_id,
                    chain_id,
                    stream,
                    row["event_name"],
                    bytes(row["address"]),
                    bytes(row["tx_hash"]),
                    row["log_index"],
                    row["block_number"],
                    json.loads(payload) if isinstance(payload, str) else payload,
                    removed=True,
                )
            )

        for event in events:
            await handlers.dispatch(connection, event)

        block = await rpc.call("eth_getBlockByNumber", [hex(end), False])
        await connection.execute(
            "INSERT INTO index_cursors (treasury_id, stream, last_block, last_block_hash) "
            "VALUES ($1, $2::index_stream, $3, $4) ON CONFLICT (treasury_id, stream) DO UPDATE "
            "SET last_block = EXCLUDED.last_block, last_block_hash = EXCLUDED.last_block_hash, "
            "updated_at = now()",
            treasury_id,
            stream,
            end,
            bytes.fromhex(block["hash"][2:]) if block else None,
        )
        return len(events)


async def _first_code_block(rpc: RpcClient, address: bytes, head: int) -> int:
    """First block where the module has code; earlier blocks cannot hold its events.

    shortcut: needs archive state for old blocks, so a pruned provider fails the run (retried).
    """

    hex_address = "0x" + address.hex()
    if await rpc.call("eth_getCode", [hex_address, hex(head)]) in ("0x", None):
        raise ValueError(f"no code at {hex_address} yet")
    low, high = 0, head
    while low < high:
        middle = (low + high) // 2
        if await rpc.call("eth_getCode", [hex_address, hex(middle)]) in ("0x", None):
            low = middle + 1
        else:
            high = middle
    return low
