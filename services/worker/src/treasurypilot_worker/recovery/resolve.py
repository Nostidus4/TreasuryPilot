"""Resolve an in-flight operation from chain evidence (RCV-002, M12 §8.1, BR-060).

Never guesses: an operation is moved only by a chain fact. Callers (the startup scan, RCV-001)
invoke ``resolve_operation`` once per in-flight operation.

* A receipt for any of its transactions belongs to the tracker (primary + secondary cross-check),
  so it is reported as ``Receipt`` and left alone.
* ``stepUsed[stepId]`` on the module, read 3 blocks deep, means the step executed: ``Confirmed``
  without resubmission (e.g. a replacement transaction we never recorded).
* A transaction nobody has seen and whose nonce is still unused was never broadcast: the operation
  returns to ``NotSubmitted`` so the executor replays the same step id. The signer replays the
  stored signed transaction (same hash, same nonce), so this cannot pay twice even if another node
  still holds it in its mempool.
* Anything else stays unresolved; after 30 minutes of silence an UNCERTAIN_TX review item is
  opened and the operation stays Unknown, which keeps the treasury's execution cycles blocked.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Final, Literal

import asyncpg  # type: ignore[import-untyped]
from eth_abi import decode, encode
from eth_abi.exceptions import DecodingError
from web3 import Web3

from treasurypilot_worker.chain.rpc import RpcClient, RpcError
from treasurypilot_worker.tracker.track import CONFIRMATIONS, TRACKED, UNKNOWN_AFTER

ESCALATE_AFTER: Final = timedelta(minutes=30)
UNCERTAIN_SLA: Final = timedelta(hours=1)
_IN_FLIGHT: Final = frozenset(TRACKED)
_STEP_USED: Final = Web3.keccak(text="stepUsed(bytes32)")[:4]

Resolution = Literal[
    "NotInFlight", "Receipt", "Confirmed", "Pending", "NeverBroadcast", "Unclear", "Escalated"
]

logger = logging.getLogger(__name__)


async def resolve_operation(
    pool: asyncpg.Pool, rpc: RpcClient, operation_id: uuid.UUID, *, now: datetime | None = None
) -> Resolution:
    now = now or datetime.now(UTC)
    op = await pool.fetchrow(
        "SELECT o.id, o.step_id, o.status, o.request_id, t.module_address FROM operations o "
        "JOIN treasuries t ON t.id = o.treasury_id WHERE o.id = $1",
        operation_id,
    )
    if op is None or op["status"] not in _IN_FLIGHT:
        return "NotInFlight"
    txs = await pool.fetch(
        "SELECT tx_hash, nonce, from_address, submitted_at, last_seen_pending_at "
        "FROM transactions WHERE operation_id = $1",
        operation_id,
    )
    if not txs:
        return "NotInFlight"

    # Silence is not evidence: any failed or undecodable read leaves the operation untouched.
    try:
        verdict = await _observe(rpc, op, txs, now)
    except (RpcError, ValueError, TypeError, KeyError, DecodingError):
        logger.warning("operation %s: chain evidence unavailable", operation_id, exc_info=True)
        return "Unclear"
    if verdict == "Confirmed":
        return await _close(pool, op, "Confirmed", None, txs) or "Confirmed"
    if verdict == "NeverBroadcast":
        return (
            await _close(pool, op, "NotSubmitted", "NEVER_BROADCAST", txs, restart=now)
            or "NeverBroadcast"
        )
    if verdict == "Escalated":
        await _escalate(pool, op, now)
    return verdict


async def _observe(
    rpc: RpcClient, op: asyncpg.Record, txs: Sequence[asyncpg.Record], now: datetime
) -> Resolution:
    hashes = ["0x" + bytes(tx["tx_hash"]).hex() for tx in txs]
    for tx_hash in hashes:
        if await rpc.call("eth_getTransactionReceipt", [tx_hash]):
            return "Receipt"

    # shortcut: stepUsed at head-2 is treated as final and, unlike the tracker's receipts, is not
    # re-watched for reorgs; upgrade to re-checking it for REORG_WINDOW blocks if a reorg deeper
    # than CONFIRMATIONS is ever seen on a supported chain.
    if await _step_used(rpc, op):
        return "Confirmed"

    for tx_hash in hashes:
        if await rpc.call("eth_getTransactionByHash", [tx_hash]):
            return "Pending"

    # Same silence the tracker needs to call a transaction Unknown; before that it may be in transit.
    silent_since = max(tx["last_seen_pending_at"] or tx["submitted_at"] for tx in txs)
    if now - silent_since < UNKNOWN_AFTER:
        return "Unclear"
    consumed = False
    for tx in txs:
        sender = "0x" + bytes(tx["from_address"]).hex()
        used = int(await rpc.call("eth_getTransactionCount", [sender, "latest"]), 16)
        consumed = consumed or int(tx["nonce"]) < used
    if not consumed:
        return "NeverBroadcast"

    # shortcut: a consumed nonce with no receipt is not traced to its block (nonce scan of recent
    # blocks, M12 §8.1 step 2); it waits for the tracker or a human, upgrade if that is common.
    return "Unclear" if now - silent_since < ESCALATE_AFTER else "Escalated"


async def _step_used(rpc: RpcClient, op: asyncpg.Record) -> bool:
    if op["module_address"] is None:
        return False
    head = int(await rpc.call("eth_blockNumber", []), 16)
    call = {
        "to": "0x" + bytes(op["module_address"]).hex(),
        "data": "0x" + (_STEP_USED + encode(["bytes32"], [bytes(op["step_id"])])).hex(),
    }
    raw = await rpc.call("eth_call", [call, hex(max(head - CONFIRMATIONS + 1, 0))])
    # An empty "0x" (no code at the module) raises a decode error instead of reading as false.
    return bool(decode(["bool"], bytes.fromhex(str(raw).removeprefix("0x")))[0])


async def _close(
    pool: asyncpg.Pool,
    op: asyncpg.Record,
    status: str,
    error: str | None,
    seen: Sequence[asyncpg.Record],
    *,
    restart: datetime | None = None,
) -> Resolution | None:
    """Move the operation; None when done, else why the tracker's newer facts won."""

    async with pool.acquire() as connection, connection.transaction():
        # Same order as the tracker (transactions, then operations) so the two cannot deadlock.
        txs = await connection.fetch(
            "SELECT tx_hash, status, block_hash, last_seen_pending_at FROM transactions "
            "WHERE operation_id = $1 FOR UPDATE",
            op["id"],
        )
        current = await connection.fetchval(
            "SELECT status FROM operations WHERE id = $1 FOR UPDATE", op["id"]
        )
        if current not in _IN_FLIGHT:
            return "Unclear"
        before = {bytes(t["tx_hash"]): t["last_seen_pending_at"] for t in seen}
        for tx in txs:
            if tx["block_hash"] is not None or tx["status"] in ("Confirmed", "Reverted"):
                return "Receipt"
            # The tracker saw it in the mempool after we looked: it is not unbroadcast.
            if restart and before.get(bytes(tx["tx_hash"]), None) != tx["last_seen_pending_at"]:
                return "Unclear"
        await connection.execute(
            "UPDATE operations SET status = $2::operation_status, last_error = $3 WHERE id = $1",
            op["id"],
            status,
            error,
        )
        if restart is None:
            # Confirmed by the module flag: our hashes lost to an unrecorded one. Dropped keeps the
            # tracker from flipping the operation back to Unknown (none has a receipt, checked).
            await connection.execute(
                "UPDATE transactions SET status = 'Dropped' WHERE operation_id = $1 "
                "AND block_hash IS NULL AND status = ANY($2::transaction_status[])",
                op["id"],
                TRACKED,
            )
        else:
            # The replay hands back the same signed tx (same hash), so the outbox inserts no new
            # row (ON CONFLICT DO NOTHING): these rows are what the tracker follows, and they
            # need a fresh Unknown clock or it would expire them at once.
            await connection.execute(
                "UPDATE transactions SET status = 'Submitted', submitted_at = $2, "
                "last_seen_pending_at = NULL WHERE operation_id = $1 "
                "AND status = ANY($3::transaction_status[])",
                op["id"],
                restart,
                TRACKED,
            )
        await connection.execute(
            "UPDATE review_items SET evidence_resolved = true WHERE request_id = $1 "
            "AND type = 'UNCERTAIN_TX' AND status = 'Open'",
            op["request_id"],
        )
        await connection.execute(
            "INSERT INTO domain_events (id, org_id, treasury_id, type, entity_type, entity_id, "
            "payload) SELECT gen_random_uuid(), tr.org_id, tr.id, 'OperationUpdated', "
            "'operation', o.id, jsonb_build_object('operationId', o.id::text) "
            "FROM operations o JOIN treasuries tr ON tr.id = o.treasury_id WHERE o.id = $1",
            op["id"],
        )
    logger.info("operation %s resolved from chain evidence: %s", op["id"], status)
    return None


async def _escalate(pool: asyncpg.Pool, op: asyncpg.Record, now: datetime) -> None:
    async with pool.acquire() as connection, connection.transaction():
        await connection.execute(
            "UPDATE operations SET status = 'Unknown' WHERE id = $1 "
            "AND status IN ('Submitted', 'Pending')",
            op["id"],
        )
        await connection.execute(
            "INSERT INTO review_items (id, org_id, treasury_id, request_id, request_version, "
            "type, primary_code, reason_codes, completed_steps, assigned_roles, status, "
            "sla_due_at, evidence_resolved) SELECT gen_random_uuid(), r.org_id, r.treasury_id, "
            "r.id, r.version, 'UNCERTAIN_TX', 'TX_UNKNOWN', ARRAY['TX_UNKNOWN'], '[]'::jsonb, "
            "ARRAY['Operator', 'Owner'], 'Open', $2, false FROM payment_requests r WHERE r.id = $1 "
            "ON CONFLICT (request_id, type) WHERE status = 'Open' DO NOTHING",
            op["request_id"],
            now + UNCERTAIN_SLA,
        )
    logger.warning("operation %s unresolved after %s: UNCERTAIN_TX", op["id"], ESCALATE_AFTER)
