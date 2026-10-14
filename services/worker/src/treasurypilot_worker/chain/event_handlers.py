"""Subscriber registry for indexed events and the built-in state handlers (M06 §6).

Handlers run inside the transaction that stores the event, once per newly observed (or
re-mined) log, so a handler failure rolls the event back and the next run retries it.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

import asyncpg  # type: ignore[import-untyped]

from treasurypilot_worker.chain.events import MODULE, SAFE_EXEC


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
