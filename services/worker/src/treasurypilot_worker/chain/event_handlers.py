"""Subscriber registry for indexed events and the built-in state handlers (M06 §6).

Handlers run inside the transaction that stores the event, once per newly observed (or
re-mined) log, so a handler failure rolls the event back and the next run retries it.
"""

from __future__ import annotations

import json
import uuid
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Final
from uuid import UUID

import asyncpg  # type: ignore[import-untyped]

from treasurypilot_worker.chain.events import MODULE, SAFE_EXEC, TOKEN


@dataclass(frozen=True)
class IndexedEvent:
    treasury_id: UUID
    chain_id: int
    stream: str
    name: str
    address: bytes
    tx_hash: bytes
    log_index: int
    block_number: int
    payload: dict[str, Any]
    # True when the log left the canonical chain; handlers that opted in must undo its effect.
    removed: bool = False
    a_token_address: bytes | None = None
    aave_pool_address: bytes | None = None


Handler = Callable[[asyncpg.Connection, IndexedEvent], Awaitable[None]]


class HandlerRegistry:
    def __init__(self) -> None:
        self._handlers: dict[tuple[str, str], list[tuple[Handler, bool]]] = defaultdict(list)

    def on_event(
        self, stream: str, name: str, handler: Handler, *, include_removed: bool = False
    ) -> None:
        self._handlers[(stream, name)].append((handler, include_removed))

    async def dispatch(self, connection: asyncpg.Connection, event: IndexedEvent) -> None:
        for handler, include_removed in self._handlers[(event.stream, event.name)]:
            if include_removed or not event.removed:
                await handler(connection, event)


registry = HandlerRegistry()


def _bytes(value: str) -> bytes:
    return bytes.fromhex(value.removeprefix("0x"))


# Unmatched outflows younger than this are re-checked each pass: the executor stores the tx
# hash after submitting, so the Transfer can be indexed before its operation is linkable.
RECLASSIFY_WINDOW: Final = "1 day"
RECLASSIFY_LIMIT: Final = 200


@dataclass(frozen=True)
class _Classification:
    kind: str
    operation_id: UUID | None
    wallet: bytes
    direction: str
    counterparty: bytes


async def _classify(connection: asyncpg.Connection, event: IndexedEvent) -> _Classification:
    """Classify one asset Transfer from its on-chain evidence and our own operations."""

    sender = _bytes(event.payload["from"])
    recipient = _bytes(event.payload["to"])
    wallets = await connection.fetch(
        "SELECT safe_address, role::text AS role FROM treasury_wallets WHERE treasury_id = $1",
        event.treasury_id,
    )
    treasury_wallets = {bytes(row["safe_address"]) for row in wallets}
    source_wallet = next(
        (bytes(row["safe_address"]) for row in wallets if row["role"] == "SOURCE"), None
    )
    operational_wallets = {
        bytes(row["safe_address"]) for row in wallets if row["role"] == "OPERATIONAL"
    }
    operation = await connection.fetchrow(
        "SELECT o.id, o.kind::text AS kind FROM transactions tx "
        "JOIN operations o ON o.id = tx.operation_id "
        "WHERE tx.chain_id = $1 AND tx.tx_hash = $2 AND o.treasury_id = $3 "
        "ORDER BY tx.submitted_at DESC LIMIT 1",
        event.chain_id,
        event.tx_hash,
        event.treasury_id,
    )
    operation_id = operation["id"] if operation is not None else None
    operation_kind = operation["kind"] if operation is not None else None
    zero_address = bytes(20)
    is_a_token = event.a_token_address is not None and event.address == event.a_token_address
    is_lending = (
        is_a_token
        and (
            (sender == zero_address and recipient == source_wallet)
            or (sender == source_wallet and recipient == zero_address)
        )
    ) or (
        not is_a_token
        and event.aave_pool_address is not None
        and (
            (
                operation_kind == "SUPPLY"
                and sender == source_wallet
                and recipient == event.aave_pool_address
            )
            or (
                operation_kind == "WITHDRAW"
                and sender == event.aave_pool_address
                and recipient == source_wallet
            )
        )
    )
    is_agent_refill = (
        operation_kind == "REFILL" and source_wallet == sender and recipient in operational_wallets
    )
    # A matching tx hash alone proves nothing about this Transfer: other transfers in the same
    # tx must still fit the operation's shape, or they fall through to the boundary checks.
    is_agent_pay = (
        operation_kind == "PAY"
        and sender in operational_wallets
        and await connection.fetchval(
            "SELECT EXISTS (SELECT 1 FROM payees WHERE treasury_id = $1 AND address = $2)",
            event.treasury_id,
            recipient,
        )
    )
    is_agent_swap = operation_kind == "SWAP" and sender in treasury_wallets
    if is_lending:
        kind = "LENDING"
    elif is_agent_refill:
        kind = "INTERNAL_REFILL"
    elif is_agent_pay or is_agent_swap:
        kind = "AGENT"
    elif recipient in treasury_wallets or sender not in treasury_wallets:
        # Includes unmatched wallet-to-wallet transfers, which stay inside the treasury.
        kind = "INFLOW"
    else:
        kind = "UNEXPECTED_OUTFLOW"

    if kind in ("INTERNAL_REFILL", "INFLOW") or sender not in treasury_wallets:
        wallet, direction, counterparty = recipient, "IN", sender
    else:
        wallet, direction, counterparty = sender, "OUT", recipient
    return _Classification(kind, operation_id, wallet, direction, counterparty)


async def _retract_outflow_alert(
    connection: asyncpg.Connection, movement_id: UUID, reason: str
) -> None:
    await connection.execute(
        "UPDATE chain_safety_signals SET invalidated_at = COALESCE(invalidated_at, now()) "
        "WHERE token_movement_id = $1",
        movement_id,
    )
    await connection.execute(
        "UPDATE domain_events SET failed_at = now(), last_error = $2 "
        "WHERE entity_type = 'token_movement' AND entity_id = $1 "
        "AND type = 'UnexpectedOutflow' AND published_at IS NULL AND failed_at IS NULL",
        movement_id,
        reason,
    )


async def _transfer(connection: asyncpg.Connection, event: IndexedEvent) -> None:
    """Persist and classify a treasury asset movement from its on-chain evidence."""

    observed_event_id = await connection.fetchval(
        "SELECT id FROM observed_events WHERE chain_id = $1 AND tx_hash = $2 AND log_index = $3",
        event.chain_id,
        event.tx_hash,
        event.log_index,
    )
    if observed_event_id is None:
        raise RuntimeError("token transfer event was not persisted before dispatch")

    if event.removed:
        movement_id = await connection.fetchval(
            "UPDATE token_movements SET removed = true WHERE event_id = $1 RETURNING id",
            observed_event_id,
        )
        if movement_id is not None:
            await _retract_outflow_alert(
                connection, movement_id, "source token transfer was removed by chain reorg"
            )
        return

    result = await _classify(connection, event)
    movement_id = uuid.uuid5(uuid.NAMESPACE_URL, f"token-movement:{observed_event_id}")
    await connection.execute(
        "INSERT INTO token_movements "
        '(id, treasury_id, event_id, wallet, direction, counterparty, amount, "class", operation_id) '
        "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9) "
        "ON CONFLICT (event_id) DO UPDATE SET wallet = EXCLUDED.wallet, "
        "direction = EXCLUDED.direction, counterparty = EXCLUDED.counterparty, "
        'amount = EXCLUDED.amount, "class" = EXCLUDED."class", '
        "operation_id = EXCLUDED.operation_id, removed = false, "
        # A re-added log is a new occurrence (signals reset to pending): an old ack must not carry.
        "acknowledged_by = NULL, acknowledged_at = NULL, acknowledgement_reason = NULL",
        movement_id,
        event.treasury_id,
        observed_event_id,
        result.wallet,
        result.direction,
        result.counterparty,
        int(event.payload["value"]),
        result.kind,
        result.operation_id,
    )
    if result.kind != "UNEXPECTED_OUTFLOW":
        return

    await connection.execute(
        "INSERT INTO chain_safety_signals (id, treasury_id, observed_event_id, "
        "token_movement_id, signal_type, payload) VALUES ($1, $2, $3, $4, "
        "'PRE_STEP_REVALIDATION', $5::jsonb), ($6, $2, $3, $4, 'CIRCUIT_BREAKER', $5::jsonb) "
        "ON CONFLICT (token_movement_id, signal_type) DO UPDATE SET "
        "consumed_at = NULL, invalidated_at = NULL, created_at = now()",
        uuid.uuid5(uuid.NAMESPACE_URL, f"pre-step-revalidation:{movement_id}"),
        event.treasury_id,
        observed_event_id,
        movement_id,
        '{"source":"UNEXPECTED_OUTFLOW"}',
        uuid.uuid5(uuid.NAMESPACE_URL, f"circuit-breaker:{movement_id}"),
    )
    treasury = await connection.fetchrow(
        "SELECT org_id FROM treasuries WHERE id = $1", event.treasury_id
    )
    if treasury is None:
        raise RuntimeError("unexpected outflow treasury disappeared")
    notification_id = uuid.uuid5(uuid.NAMESPACE_URL, f"unexpected-outflow:{movement_id}")
    await connection.execute(
        "INSERT INTO domain_events "
        "(id, org_id, treasury_id, type, entity_type, entity_id, payload) "
        "VALUES ($1, $2, $3, 'UnexpectedOutflow', 'token_movement', $4, $5::jsonb) "
        "ON CONFLICT (id) DO UPDATE SET failed_at = NULL, last_error = NULL "
        "WHERE domain_events.published_at IS NULL",
        notification_id,
        treasury["org_id"],
        event.treasury_id,
        movement_id,
        '{"tokenMovementId":"' + str(movement_id) + '"}',
    )


async def reclassify_unmatched_outflows(
    pool: asyncpg.Pool,
    treasury_id: UUID,
    *,
    a_token_address: bytes | None,
    aave_pool_address: bytes | None,
) -> int:
    """Re-check recent unacknowledged outflows; returns how many stopped being outflows."""

    async with pool.acquire() as connection, connection.transaction():
        rows = await connection.fetch(
            "SELECT m.id AS movement_id, e.chain_id, e.address, e.tx_hash, e.log_index, "
            "e.block_number, e.payload FROM token_movements m "
            "JOIN observed_events e ON e.id = m.event_id "
            "WHERE m.treasury_id = $1 AND m.\"class\" = 'UNEXPECTED_OUTFLOW' AND NOT m.removed "
            "AND m.acknowledged_at IS NULL "
            f"AND e.observed_at > now() - interval '{RECLASSIFY_WINDOW}' "
            "ORDER BY e.observed_at DESC LIMIT $2 FOR UPDATE OF m",
            treasury_id,
            RECLASSIFY_LIMIT,
        )
        changed = 0
        for row in rows:
            payload = row["payload"]
            result = await _classify(
                connection,
                IndexedEvent(
                    treasury_id,
                    row["chain_id"],
                    TOKEN,
                    "Transfer",
                    bytes(row["address"]),
                    bytes(row["tx_hash"]),
                    row["log_index"],
                    row["block_number"],
                    json.loads(payload) if isinstance(payload, str) else payload,
                    a_token_address=a_token_address,
                    aave_pool_address=aave_pool_address,
                ),
            )
            if result.kind == "UNEXPECTED_OUTFLOW":
                continue
            await connection.execute(
                'UPDATE token_movements SET "class" = $2, operation_id = $3, wallet = $4, '
                "direction = $5, counterparty = $6 WHERE id = $1",
                row["movement_id"],
                result.kind,
                result.operation_id,
                result.wallet,
                result.direction,
                result.counterparty,
            )
            await _retract_outflow_alert(
                connection, row["movement_id"], "transfer was later matched to an agent operation"
            )
            changed += 1
        return changed


async def _payee_added(connection: asyncpg.Connection, event: IndexedEvent) -> None:
    # Cooling until the on-chain activation time, which the module enforces on payments.
    active_from = datetime.fromtimestamp(int(event.payload["activeFrom"]), UTC)
    row = await connection.fetchrow(
        "UPDATE payees SET status = CASE WHEN $3 <= now() THEN 'Active' ELSE 'Cooling' "
        "END::payee_status, active_from = $3, version = version + 1, updated_at = now() "
        "WHERE treasury_id = $1 AND address = $2 AND status = 'AwaitingOwner' "
        "AND oob_verified_at IS NOT NULL RETURNING status",
        event.treasury_id,
        _bytes(event.payload["payee"]),
        active_from,
    )
    if row is not None and row["status"] == "Active":
        await _enqueue_execution_cycle(connection, event.treasury_id)


async def _payee_deactivated(connection: asyncpg.Connection, event: IndexedEvent) -> None:
    await connection.execute(
        "UPDATE payees SET status = 'Deactivated', deactivated_at = now(), "
        "version = version + 1, updated_at = now() "
        "WHERE treasury_id = $1 AND address = $2 AND status IN ('Cooling', 'Active')",
        event.treasury_id,
        _bytes(event.payload["payee"]),
    )


async def _paused(connection: asyncpg.Connection, event: IndexedEvent) -> None:
    await connection.execute(
        "INSERT INTO backend_pause (treasury_id, org_id, paused, reason, onchain_status) "
        "SELECT id, org_id, true, 'Paused on-chain by ' || $2::text, "
        "'Effective'::onchain_pause_status FROM treasuries WHERE id = $1 "
        "ON CONFLICT (treasury_id) DO UPDATE SET paused = true, "
        "onchain_status = 'Effective', reason = COALESCE(NULLIF(btrim(backend_pause.reason), ''), "
        "EXCLUDED.reason), version = backend_pause.version + 1, updated_at = now()",
        event.treasury_id,
        event.payload["by"],
    )


async def _resumed(connection: asyncpg.Connection, event: IndexedEvent) -> None:
    # The Owner's resume acknowledges the circuit-breaker trips (RCV-006): consume the signals the
    # circuit evaluator already turned into an event, or the planner gate would stay blocked.
    await connection.execute(
        "UPDATE chain_safety_signals s SET consumed_at = now() WHERE s.treasury_id = $1 "
        "AND s.signal_type = 'CIRCUIT_BREAKER' AND s.consumed_at IS NULL "
        "AND s.invalidated_at IS NULL AND EXISTS (SELECT 1 FROM circuit_events e "
        "WHERE e.treasury_id = s.treasury_id AND e.dedupe_key = 'signal:' || s.id::text)",
        event.treasury_id,
    )
    row = await connection.fetchrow(
        "UPDATE backend_pause SET paused = false, onchain_status = 'NotRequested', "
        "version = version + 1, updated_at = now() WHERE treasury_id = $1 "
        "AND (paused OR onchain_status <> 'NotRequested') RETURNING treasury_id",
        event.treasury_id,
    )
    if row is not None:
        await _enqueue_execution_cycle(connection, event.treasury_id)


async def _revoked(connection: asyncpg.Connection, event: IndexedEvent) -> None:
    # Terminal: the module never acts again; every worker gate requires a Ready treasury.
    await connection.execute(
        "UPDATE treasuries SET status = 'Revoked', version = version + 1, updated_at = now() "
        "WHERE id = $1 AND status <> 'Revoked'",
        event.treasury_id,
    )
    await connection.execute(
        "WITH revoked AS (UPDATE mandate_versions SET status = 'Revoked' "
        "WHERE treasury_id = $1 AND status = 'Active' RETURNING id, org_id) "
        "INSERT INTO mandate_status_events (id, org_id, mandate_version_id, from_status, "
        "to_status, tx_hash, by_user_id) SELECT gen_random_uuid(), org_id, id, 'Active', "
        "'Revoked', $2, NULL FROM revoked",
        event.treasury_id,
        event.tx_hash,
    )


async def _exception_granted(connection: asyncpg.Connection, event: IndexedEvent) -> None:
    # Amount and payee must equal the proposal: a different grant is not the one owners reviewed.
    row = await connection.fetchrow(
        "UPDATE exceptions e SET status = 'Granted', version = e.version + 1, updated_at = now() "
        "FROM payment_requests r WHERE r.id = e.request_id AND r.treasury_id = $1 "
        "AND r.onchain_request_id = $2 AND e.status = 'Proposed' AND e.payee = $3 "
        "AND e.amount = $4 AND e.mandate_onchain_version = $5 "
        "AND date_trunc('second', e.expiry) = to_timestamp($6) RETURNING e.request_id",
        event.treasury_id,
        _bytes(event.payload["requestId"]),
        _bytes(event.payload["payee"]),
        Decimal(event.payload["amount"]),
        int(event.payload["version"]),
        int(event.payload["expiry"]),
    )
    if row is not None:
        await _enqueue_execution_cycle(
            connection,
            event.treasury_id,
            entity_type="payment_request",
            entity_id=row["request_id"],
        )


async def _exception_revoked(connection: asyncpg.Connection, event: IndexedEvent) -> None:
    await connection.execute(
        "UPDATE exceptions e SET status = 'Revoked', version = e.version + 1, updated_at = now() "
        "FROM payment_requests r WHERE r.id = e.request_id AND r.treasury_id = $1 "
        "AND r.onchain_request_id = $2 AND e.status = 'Granted'",
        event.treasury_id,
        _bytes(event.payload["requestId"]),
    )


async def _exception_consumed(connection: asyncpg.Connection, event: IndexedEvent) -> None:
    if event.payload.get("usedException") is not True:
        return
    await connection.execute(
        "UPDATE exceptions e SET status = 'Consumed', version = e.version + 1, updated_at = now() "
        "FROM payment_requests r WHERE r.id = e.request_id AND r.treasury_id = $1 "
        "AND r.onchain_request_id = $2 AND e.status = 'Granted'",
        event.treasury_id,
        _bytes(event.payload["requestId"]),
    )


async def _mandate_configured(connection: asyncpg.Connection, event: IndexedEvent) -> None:
    await connection.execute(
        "UPDATE exceptions SET status = 'Invalidated', version = version + 1, updated_at = now() "
        "WHERE treasury_id = $1 AND mandate_onchain_version < $2 "
        "AND status IN ('Requested', 'Proposed', 'Granted')",
        event.treasury_id,
        int(event.payload["version"]),
    )


async def _token_transfer(connection: asyncpg.Connection, event: IndexedEvent) -> None:
    if int(event.payload["value"]) == 0:
        return
    sender = _bytes(event.payload["from"])
    recipient = _bytes(event.payload["to"])
    matches = await connection.fetchval(
        "SELECT EXISTS (SELECT 1 FROM treasury_wallets WHERE treasury_id = $1 "
        "AND safe_address = $2) AND NOT EXISTS (SELECT 1 FROM treasury_wallets "
        "WHERE treasury_id = $1 AND safe_address = $3)",
        event.treasury_id,
        recipient,
        sender,
    )
    if matches:
        await _enqueue_execution_cycle(connection, event.treasury_id)


async def _enqueue_execution_cycle(
    connection: asyncpg.Connection,
    treasury_id: UUID,
    *,
    entity_type: str = "treasury",
    entity_id: UUID | None = None,
) -> None:
    await connection.execute(
        "INSERT INTO domain_events "
        "(id, org_id, treasury_id, type, entity_type, entity_id, payload) "
        "SELECT gen_random_uuid(), t.org_id, t.id, 'ExecutionCycleRequested', $2, $3, '{}'::jsonb "
        "FROM treasuries t WHERE t.id = $1",
        treasury_id,
        entity_type,
        entity_id or treasury_id,
    )


async def activate_due_payees(pool: asyncpg.Pool) -> int:
    """Activate Cooling payees whose on-chain delay elapsed and enqueue a cycle."""
    async with pool.acquire() as connection, connection.transaction():
        rows = await connection.fetch(
            "WITH active AS (UPDATE payees SET status = 'Active'::payee_status, "
            "version = version + 1, updated_at = now() WHERE status = 'Cooling' "
            "AND active_from <= now() "
            # A reorged-out PayeeAdded must not activate (removed events do not reset the row).
            "AND EXISTS (SELECT 1 FROM observed_events o WHERE o.treasury_id = payees.treasury_id "
            "AND o.stream = 'MODULE'::index_stream AND o.event_name = 'PayeeAdded' AND NOT o.removed "
            "AND o.payload->>'payee' = '0x' || encode(payees.address, 'hex')) "
            "RETURNING id, treasury_id) "
            "INSERT INTO domain_events "
            "(id, org_id, treasury_id, type, entity_type, entity_id, payload) "
            "SELECT gen_random_uuid(), t.org_id, t.id, 'ExecutionCycleRequested', 'payee', "
            "active.id, '{}'::jsonb FROM active JOIN treasuries t ON t.id = active.treasury_id "
            "RETURNING id"
        )
        return len(rows)


async def _request_cancelled(connection: asyncpg.Connection, event: IndexedEvent) -> None:
    # Worker-side equivalent of the API's confirm_onchain_cancel (#130), which the worker cannot
    # import; scoped by the emitting module so another treasury's request id cannot match.
    await connection.execute(
        "UPDATE payment_requests r SET cancel_onchain = 'Confirmed', cancel_tx_hash = $3, "
        "version = r.version + 1, updated_at = now() FROM treasuries t "
        "WHERE t.id = r.treasury_id AND t.module_address = $1 AND r.onchain_request_id = $2 "
        "AND r.cancel_onchain = 'Pending'",
        event.address,
        _bytes(event.payload["requestId"]),
        event.tx_hash,
    )


def _governance_outcome(status: str) -> Handler:
    async def handler(connection: asyncpg.Connection, event: IndexedEvent) -> None:
        # Also catches Safe txs executed outside the app (signatures collected elsewhere).
        await connection.execute(
            "UPDATE governance_txs SET status = $4::governance_tx_status, exec_tx_hash = $3, "
            "version = version + 1, updated_at = now() WHERE chain_id = $5 AND safe_address = $1 "
            "AND safe_tx_hash = $2 AND status IN ('Collecting', 'Ready', 'Submitted')",
            event.address,
            _bytes(event.payload["txHash"]),
            event.tx_hash,
            status,
            event.chain_id,
        )

    return handler


registry.on_event(MODULE, "PayeeAdded", _payee_added)
registry.on_event(MODULE, "PayeeDeactivated", _payee_deactivated)
registry.on_event(MODULE, "Paused", _paused)
registry.on_event(MODULE, "Resumed", _resumed)
registry.on_event(MODULE, "Revoked", _revoked)
registry.on_event(MODULE, "ExceptionGranted", _exception_granted)
registry.on_event(MODULE, "ExceptionRevoked", _exception_revoked)
registry.on_event(MODULE, "PaymentExecuted", _exception_consumed)
registry.on_event(MODULE, "MandateConfigured", _mandate_configured)
registry.on_event(MODULE, "RequestCancelled", _request_cancelled)
registry.on_event(SAFE_EXEC, "ExecutionSuccess", _governance_outcome("Executed"))
registry.on_event(SAFE_EXEC, "ExecutionFailure", _governance_outcome("Failed"))
registry.on_event(TOKEN, "Transfer", _token_transfer)
registry.on_event(TOKEN, "Transfer", _transfer, include_removed=True)
