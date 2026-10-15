"""Subscriber registry for indexed events and the built-in state handlers (M06 §6).

Handlers run inside the transaction that stores the event, once per newly observed (or
re-mined) log, so a handler failure rolls the event back and the next run retries it.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
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
            await connection.execute(
                "UPDATE chain_safety_signals SET invalidated_at = COALESCE(invalidated_at, now()) "
                "WHERE token_movement_id = $1",
                movement_id,
            )
            await connection.execute(
                "UPDATE domain_events SET failed_at = now(), "
                "last_error = 'source token transfer was removed by chain reorg' "
                "WHERE entity_type = 'token_movement' AND entity_id = $1 "
                "AND type = 'UnexpectedOutflow' AND published_at IS NULL AND failed_at IS NULL",
                movement_id,
            )
        return

    sender = _bytes(event.payload["from"])
    recipient = _bytes(event.payload["to"])
    amount = int(event.payload["value"])
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
    if is_lending:
        classification = "LENDING"
    elif is_agent_refill:
        classification = "INTERNAL_REFILL"
    elif operation is not None:
        classification = "AGENT"
    elif recipient in treasury_wallets:
        # Treasury-to-treasury transfers do not leave the treasury boundary.
        classification = "INFLOW"
    elif sender not in treasury_wallets:
        classification = "INFLOW"
    else:
        classification = "UNEXPECTED_OUTFLOW"

    if classification == "INTERNAL_REFILL":
        wallet, direction, counterparty = recipient, "IN", sender
    elif classification == "INFLOW":
        wallet, direction, counterparty = recipient, "IN", sender
    elif sender in treasury_wallets:
        wallet, direction, counterparty = sender, "OUT", recipient
    else:
        wallet, direction, counterparty = recipient, "IN", sender

    movement_id = uuid.uuid5(uuid.NAMESPACE_URL, f"token-movement:{observed_event_id}")
    await connection.execute(
        "INSERT INTO token_movements "
        '(id, treasury_id, event_id, wallet, direction, counterparty, amount, "class", operation_id) '
        "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9) "
        "ON CONFLICT (event_id) DO UPDATE SET wallet = EXCLUDED.wallet, "
        "direction = EXCLUDED.direction, counterparty = EXCLUDED.counterparty, "
        'amount = EXCLUDED.amount, "class" = EXCLUDED."class", '
        "operation_id = EXCLUDED.operation_id, "
        "removed = false",
        movement_id,
        event.treasury_id,
        observed_event_id,
        wallet,
        direction,
        counterparty,
        amount,
        classification,
        operation_id,
    )
    if classification != "UNEXPECTED_OUTFLOW":
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


async def _payee_added(connection: asyncpg.Connection, event: IndexedEvent) -> None:
    # Cooling until the on-chain activation time, which the module enforces on payments.
    active_from = datetime.fromtimestamp(int(event.payload["activeFrom"]), UTC)
    await connection.execute(
        "UPDATE payees SET status = CASE WHEN $3 <= now() THEN 'Active' ELSE 'Cooling' "
        "END::payee_status, active_from = $3, version = version + 1, updated_at = now() "
        "WHERE treasury_id = $1 AND address = $2 AND status = 'AwaitingOwner' "
        "AND oob_verified_at IS NOT NULL",
        event.treasury_id,
        _bytes(event.payload["payee"]),
        active_from,
    )


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
    await connection.execute(
        "UPDATE backend_pause SET paused = false, onchain_status = 'NotRequested', "
        "version = version + 1, updated_at = now() WHERE treasury_id = $1",
        event.treasury_id,
    )


async def _exception_granted(connection: asyncpg.Connection, event: IndexedEvent) -> None:
    # Amount and payee must equal the proposal: a different grant is not the one owners reviewed.
    await connection.execute(
        "UPDATE exceptions e SET status = 'Granted', version = e.version + 1, updated_at = now() "
        "FROM payment_requests r WHERE r.id = e.request_id AND r.treasury_id = $1 "
        "AND r.onchain_request_id = $2 AND e.status = 'Proposed' AND e.payee = $3 "
        "AND e.amount = $4",
        event.treasury_id,
        _bytes(event.payload["requestId"]),
        _bytes(event.payload["payee"]),
        Decimal(event.payload["amount"]),
    )


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
registry.on_event(MODULE, "ExceptionGranted", _exception_granted)
registry.on_event(MODULE, "RequestCancelled", _request_cancelled)
registry.on_event(SAFE_EXEC, "ExecutionSuccess", _governance_outcome("Executed"))
registry.on_event(SAFE_EXEC, "ExecutionFailure", _governance_outcome("Failed"))
registry.on_event(TOKEN, "Transfer", _transfer, include_removed=True)
