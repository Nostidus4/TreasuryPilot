"""Resolve an in-flight operation from chain evidence (RCV-002, M12 §8.1, BR-060).

Never guesses: an operation is moved only by a chain fact. Callers (the startup scan, RCV-001)
invoke ``resolve_operation`` once per in-flight operation.

* A receipt for any of its transactions, on the primary or the secondary provider, belongs to the
  tracker (which confirms or reverts it once both providers agree, also for Unknown rows), so it is
  reported as ``Receipt`` and left alone. A provider that cannot answer is "unclear", never "none".
* ``stepUsed[stepId]``, or ``requestPaid[requestId]`` for a PAY step, on the module, read 3 blocks
  deep, means the step executed: ``Confirmed`` without resubmission (e.g. a replacement
  transaction we never recorded).
* A transaction nobody has seen and whose nonce is still unused was never broadcast: the operation
  returns to ``NotSubmitted`` so the executor replays the same step id. The signer replays the
  stored signed transaction (same hash, same nonce), so this cannot pay twice even if another node
  still holds it in its mempool.
* A consumed nonce is traced to the block that used it (bounded, ``TRACE_WINDOW`` blocks). If that
  transaction reverted the operation is ``Reverted``; if it succeeded without using the step, our
  signed transaction can never be mined and the operation is ``Abandoned`` (the executor also
  abandons a replay the signer refuses, e.g. ATTESTATION_EXPIRED: ``executor.outbox``).
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
# shortcut: the nonce trace binary-searches eth_getTransactionCount over the last TRACE_WINDOW
# blocks (~15 calls, needs historical state); older or unreadable history stays Unclear and
# escalates to a human. Raise it only for chains whose providers keep that much state.
TRACE_WINDOW: Final = 7200
_IN_FLIGHT: Final = frozenset(TRACKED)
_STEP_USED: Final = Web3.keccak(text="stepUsed(bytes32)")[:4]
_REQUEST_PAID: Final = Web3.keccak(text="requestPaid(bytes32)")[:4]

Resolution = Literal[
    "NotInFlight",
    "Receipt",
    "Confirmed",
    "Reverted",
    "Abandoned",
    "Pending",
    "NeverBroadcast",
    "Unclear",
    "Escalated",
]

logger = logging.getLogger(__name__)


async def resolve_operation(
    pool: asyncpg.Pool, rpc: RpcClient, operation_id: uuid.UUID, *, now: datetime | None = None
) -> Resolution:
    now = now or datetime.now(UTC)
    op = await pool.fetchrow(
        "SELECT o.id, o.step_id, o.kind, o.status, o.request_id, t.module_address, "
        "r.onchain_request_id FROM operations o JOIN treasuries t ON t.id = o.treasury_id "
        "LEFT JOIN payment_requests r ON r.id = o.request_id WHERE o.id = $1",
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
        verdict, detail = await _observe(rpc, op, txs, now)
    except (RpcError, ValueError, TypeError, KeyError, DecodingError):
        logger.warning("operation %s: chain evidence unavailable", operation_id, exc_info=True)
        return "Unclear"
    if verdict == "Confirmed":
        return await _close(pool, op, "Confirmed", None, txs) or "Confirmed"
    if verdict in ("Reverted", "Abandoned"):
        return await _close(pool, op, verdict, detail, txs) or verdict
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
) -> tuple[Resolution, str | None]:
    """The verdict and, for Reverted/Abandoned, the evidence recorded as ``last_error``."""

    for tx in txs:
        if await rpc.receipt_anywhere("0x" + bytes(tx["tx_hash"]).hex()):
            return "Receipt", None

    # shortcut: the module flags at head-2 are treated as final and, unlike the tracker's receipts,
    # are not re-watched for reorgs; upgrade to re-checking them for REORG_WINDOW blocks if a reorg
    # deeper than CONFIRMATIONS is ever seen on a supported chain.
    if await _executed(rpc, op):
        return "Confirmed", None

    for tx in txs:
        if await rpc.call("eth_getTransactionByHash", ["0x" + bytes(tx["tx_hash"]).hex()]):
            return "Pending", None

    # Same silence the tracker needs to call a transaction Unknown; before that it may be in transit.
    silent_since = max(tx["last_seen_pending_at"] or tx["submitted_at"] for tx in txs)
    if now - silent_since < UNKNOWN_AFTER:
        return "Unclear", None
    consumed: list[tuple[str, int]] = []
    for tx in txs:
        sender = "0x" + bytes(tx["from_address"]).hex()
        used = int(await rpc.call("eth_getTransactionCount", [sender, "latest"]), 16)
        if int(tx["nonce"]) < used:
            consumed.append((sender, int(tx["nonce"])))
    if not consumed:
        return "NeverBroadcast", None

    # Our nonce was used by a transaction that is not ours and the step is not used: classify it.
    for sender, nonce in dict.fromkeys(consumed):
        other = await _consuming_tx(rpc, sender, nonce)
        receipt = await rpc.receipt_anywhere(other) if other else None
        if receipt:
            detail = f"NONCE_CONSUMED_BY {other}"
            return ("Reverted" if receipt["status"] == "0x0" else "Abandoned"), detail
    return ("Unclear" if now - silent_since < ESCALATE_AFTER else "Escalated"), None


async def _consuming_tx(rpc: RpcClient, sender: str, nonce: int) -> str | None:
    """Hash of the transaction from ``sender`` with ``nonce``, once it is CONFIRMATIONS deep.

    Binary search over the sender's historical transaction count finds the one block that raised
    it past ``nonce``; None when that is too recent, older than TRACE_WINDOW, or not in the block.
    """

    head = int(await rpc.call("eth_blockNumber", []), 16)
    high = max(head - CONFIRMATIONS + 1, 0)
    low = max(high - TRACE_WINDOW, 0)

    async def count(block: int) -> int:
        return int(await rpc.call("eth_getTransactionCount", [sender, hex(block)]), 16)

    if await count(high) <= nonce or (low > 0 and await count(low) > nonce):
        return None
    while high - low > 1:
        mid = (low + high) // 2
        if await count(mid) > nonce:
            high = mid
        else:
            low = mid
    block = await rpc.call("eth_getBlockByNumber", [hex(high), True])
    for tx in block["transactions"]:
        if tx["from"].lower() == sender.lower() and int(tx["nonce"], 16) == nonce:
            return str(tx["hash"])
    return None


async def _executed(rpc: RpcClient, op: asyncpg.Record) -> bool:
    """stepUsed[stepId], or requestPaid[requestId] for a PAY step, CONFIRMATIONS blocks deep."""

    if op["module_address"] is None:
        return False
    head = int(await rpc.call("eth_blockNumber", []), 16)
    block = hex(max(head - CONFIRMATIONS + 1, 0))
    flags = [(_STEP_USED, bytes(op["step_id"]))]
    if op["kind"] == "PAY" and op["onchain_request_id"] is not None:
        flags.append((_REQUEST_PAID, bytes(op["onchain_request_id"])))
    for selector, key in flags:
        call = {
            "to": "0x" + bytes(op["module_address"]).hex(),
            "data": "0x" + (selector + encode(["bytes32"], [key])).hex(),
        }
        raw = await rpc.call("eth_call", [call, block])
        # An empty "0x" (no code at the module) raises a decode error instead of reading as false.
        if decode(["bool"], bytes.fromhex(str(raw).removeprefix("0x")))[0]:
            return True
    return False


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
