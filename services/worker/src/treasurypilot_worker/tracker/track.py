"""Transaction status machine (M06 §5, §7.1, §8.2).

Only chain facts move a transaction. A transaction is ``Confirmed``/``Reverted`` at 3
confirmations once the secondary provider agrees; silence for 10 minutes makes it ``Unknown``
(never a failure, BR-060). Reorg demotion is CHR-004.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, Final

import asyncpg  # type: ignore[import-untyped]

from treasurypilot_core.policy import decode_revert
from treasurypilot_worker.chain.rpc import (
    CrossCheck,
    RpcClient,
    RpcResponseError,
    build_rpc_client,
)
from treasurypilot_worker.locks import create_worker_pool

CONFIRMATIONS: Final = 3
UNKNOWN_AFTER: Final = timedelta(minutes=10)
# Unknown stays tracked so a later sighting can move it back to Pending.
TRACKED: Final = ["Submitted", "Pending", "Unknown"]

logger = logging.getLogger(__name__)

ClientFactory = Callable[[Sequence[str]], RpcClient]


async def track_transactions(
    database_url: str,
    *,
    client_factory: ClientFactory = build_rpc_client,
    now: datetime | None = None,
) -> dict[str, int]:
    """Poll every unfinished transaction once; returns how many changed state."""

    now = now or datetime.now(UTC)
    pool = await create_worker_pool(database_url, min_size=1, max_size=2)
    try:
        rows = await pool.fetch(
            "SELECT t.*, c.rpc_urls FROM transactions t JOIN chains c USING (chain_id) "
            "WHERE t.status = ANY($1::transaction_status[]) ORDER BY t.submitted_at",
            TRACKED,
        )
        clients: dict[str, RpcClient] = {}
        changed = 0
        for row in rows:
            urls = row["rpc_urls"]
            client = clients.setdefault(str(urls), client_factory(_urls(urls)))
            try:
                changed += await _track_one(pool, client, row, now)
            except Exception:
                # One bad transaction or provider answer must not stall the others.
                logger.exception("tracking transaction %s failed", row["id"])
        return {"changed": changed}
    finally:
        await pool.close()


def track_transactions_sync(database_url: str) -> dict[str, int]:
    return asyncio.run(track_transactions(database_url))


def _urls(value: Any) -> list[str]:
    return list(json.loads(value) if isinstance(value, str) else value)


async def _track_one(pool: asyncpg.Pool, rpc: RpcClient, row: asyncpg.Record, now: datetime) -> int:
    tx_hash = "0x" + bytes(row["tx_hash"]).hex()
    new: dict[str, Any] = {
        "status": row["status"],
        "block_number": row["block_number"],
        "block_hash": row["block_hash"],
        "confirmations": row["confirmations"],
        "revert_selector": row["revert_selector"],
        "gas_used": row["gas_used"],
        "effective_gas_price": row["effective_gas_price"],
        "fee_wei": row["fee_wei"],
        "last_seen_pending_at": row["last_seen_pending_at"],
        "confirmed_at": row["confirmed_at"],
        "crosscheck": row["crosscheck"],
        "replaced_by_tx_id": row["replaced_by_tx_id"],
    }
    last_error: str | None = None
    # The clock runs from the last time the transaction was legitimately still in flight.
    expired = now - (row["last_seen_pending_at"] or row["submitted_at"]) >= UNKNOWN_AFTER
    receipt = await rpc.call("eth_getTransactionReceipt", [tx_hash])
    if receipt:
        number = int(receipt["blockNumber"], 16)
        head = int(await rpc.call("eth_blockNumber", []), 16)
        confirmations = max(head - number + 1, 1)
        gas_used = int(receipt["gasUsed"], 16)
        price = int(receipt["effectiveGasPrice"], 16)
        new |= {
            "status": "Pending",
            "block_number": number,
            "block_hash": bytes.fromhex(receipt["blockHash"][2:]),
            "confirmations": confirmations,
            "gas_used": gas_used,
            "effective_gas_price": price,
            "fee_wei": gas_used * price,
        }
        if confirmations < CONFIRMATIONS:
            new["last_seen_pending_at"] = now
        else:
            check = await rpc.crosscheck_receipt(tx_hash)
            # The enum has no "Unavailable": a side that cannot answer has not checked.
            new["crosscheck"] = "NotRun" if check is CrossCheck.UNAVAILABLE else check.value
            if check is CrossCheck.MATCH:
                block = await rpc.call("eth_getBlockByNumber", [receipt["blockNumber"], False])
                # BR-026: the attribution day is the UTC day of the mined block.
                new["confirmed_at"] = datetime.fromtimestamp(int(block["timestamp"], 16), UTC)
                if receipt["status"] == "0x1":
                    new["status"] = "Confirmed"
                else:
                    selector = await _revert_selector(rpc, tx_hash, number)
                    new["status"] = "Reverted"
                    new["revert_selector"] = selector
                    codes = decode_revert(selector or b"")
                    last_error = "transaction reverted: " + ", ".join(codes)
            elif expired:
                new["status"] = "Unknown"
    else:
        replacement = await _mined_replacement(pool, rpc, row)
        if replacement is not None:
            new["status"] = "Dropped"
            new["replaced_by_tx_id"] = replacement
        elif await rpc.call("eth_getTransactionByHash", [tx_hash]):
            new |= {"status": "Pending", "last_seen_pending_at": now}
        elif expired:
            new["status"] = "Unknown"

    async with pool.acquire() as connection, connection.transaction():
        # The status guard keeps overlapping runs from overwriting each other's progress.
        result = await connection.execute(
            "UPDATE transactions SET status = $3::transaction_status, block_number = $4, "
            "block_hash = $5, confirmations = $6, revert_selector = $7, gas_used = $8, "
            "effective_gas_price = $9, fee_wei = $10, last_seen_pending_at = $11, "
            "confirmed_at = $12, crosscheck = $13::transaction_crosscheck, "
            "replaced_by_tx_id = $14 WHERE id = $1 AND status = $2::transaction_status",
            row["id"],
            row["status"],
            *new.values(),
        )
        if result.endswith(" 0"):
            return 0
        # The operation follows the newest transaction that was not replaced.
        await connection.execute(
            "UPDATE operations o SET status = t.status::text::operation_status, "
            "last_error = COALESCE($2, o.last_error) FROM (SELECT status FROM transactions "
            "WHERE operation_id = $1 AND status <> 'Dropped' "
            "ORDER BY submitted_at DESC, id DESC LIMIT 1) t "
            "WHERE o.id = $1 AND o.status IN ('Submitted', 'Pending', 'Unknown')",
            row["operation_id"],
            last_error,
        )
    return int(new["status"] != row["status"])


async def _mined_replacement(pool: asyncpg.Pool, rpc: RpcClient, row: asyncpg.Record) -> Any:
    """Id of a sibling with the same (from, nonce) that has been mined, if any."""

    siblings = await pool.fetch(
        "SELECT id, tx_hash FROM transactions WHERE operation_id = $1 AND chain_id = $2 "
        "AND from_address = $3 AND nonce = $4 AND id <> $5",
        row["operation_id"],
        row["chain_id"],
        row["from_address"],
        row["nonce"],
        row["id"],
    )
    for sibling in siblings:
        if await rpc.call("eth_getTransactionReceipt", ["0x" + bytes(sibling["tx_hash"]).hex()]):
            return sibling["id"]
    return None


async def _revert_selector(rpc: RpcClient, tx_hash: str, block_number: int) -> bytes | None:
    """Replay the call on the parent block to read the revert data (receipts carry none)."""

    tx = await rpc.call("eth_getTransactionByHash", [tx_hash])
    if not tx or not tx.get("to"):
        return None
    call = {"from": tx["from"], "to": tx["to"], "data": tx["input"], "value": tx["value"]}
    try:
        await rpc.call("eth_call", [call, hex(block_number - 1)])
    except RpcResponseError as revert:
        data = bytes.fromhex(str(revert.data or "0x").removeprefix("0x"))
        return data[:4] if len(data) >= 4 else None
    return None  # the replay succeeded, so state differed in-block; no data to decode
