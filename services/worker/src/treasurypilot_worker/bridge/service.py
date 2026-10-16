"""Bridge transfer lifecycle: send once, account in-flight funds, never re-send (EXE-L03).

States: ``PendingSend -> Sent -> Completed | Failed``; any ambiguity (provider timeout, a crash
between claim and send, a deadline passing with no arrival, an arrival below ``min_amount_out``)
ends in ``Unknown``. ``send`` is called only by the call that inserted the transfer row, so a
retry, a timeout or a crash can never produce a second bridge transfer. Unknown is resolved only
by observing the provider's status (arrival or definitive failure), never by sending again.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID, uuid4

import asyncpg  # type: ignore[import-untyped]

from treasurypilot_worker.bridge.adapter import (
    BridgeAdapter,
    BridgeRefused,
    BridgeRoute,
    BridgeSendRequest,
    ProviderState,
)
from treasurypilot_worker.bridge.policy import BridgePolicy, BridgeRejected

logger = logging.getLogger(__name__)

OPEN_STATUSES = ("PendingSend", "Sent", "Unknown")


@dataclass(frozen=True)
class Transfer:
    id: UUID
    source_treasury_id: UUID
    destination_treasury_id: UUID
    provider: str
    idempotency_key: str
    amount: int
    min_amount_out: int
    status: str
    provider_ref: str | None
    last_error: str | None
    deadline_at: datetime


@dataclass(frozen=True)
class TreasuryInfo:
    org_id: UUID
    chain_id: int
    safe_address: str  # 0x-hex of the treasury's source Safe (the bridge recipient)


class BridgeRepository(Protocol):
    async def treasury(self, treasury_id: UUID) -> TreasuryInfo | None: ...

    async def claim(
        self, transfer: Transfer, check_in_flight: Callable[[int], None]
    ) -> tuple[Transfer, bool]:
        """Insert the transfer unless its idempotency key exists; return (row, created).

        ``check_in_flight(total)`` runs under a per-treasury lock with the open total and may raise.
        """
        ...

    async def transition(
        self,
        transfer_id: UUID,
        expected: tuple[str, ...],
        status: str,
        *,
        provider_ref: str | None = None,
        last_error: str | None = None,
    ) -> bool: ...

    async def open_transfers(self, source_treasury_id: UUID) -> list[Transfer]: ...

    async def get(self, transfer_id: UUID) -> Transfer | None: ...

    async def in_flight_total(self, source_treasury_id: UUID) -> int: ...


@dataclass(frozen=True)
class BridgeRequest:
    source_treasury_id: UUID
    destination_treasury_id: UUID
    provider: str
    idempotency_key: str
    amount: int
    min_amount_out: int


class BridgeService:
    def __init__(
        self,
        repository: BridgeRepository,
        adapter: BridgeAdapter,
        policy: BridgePolicy,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._repo = repository
        self._adapter = adapter
        self._policy = policy
        self._clock = clock

    async def initiate(self, request: BridgeRequest) -> Transfer:
        """Validate, claim and send once. Re-calling with the same key never sends again."""

        source = await self._repo.treasury(request.source_treasury_id)
        destination = await self._repo.treasury(request.destination_treasury_id)
        if source is None or destination is None:
            raise BridgeRejected("TREASURY_NOT_FOUND")
        if source.org_id != destination.org_id:
            raise BridgeRejected("TREASURIES_NOT_SAME_ORG")
        if source.chain_id == destination.chain_id:
            raise BridgeRejected("SAME_CHAIN")
        route = BridgeRoute(request.provider, source.chain_id, destination.chain_id)

        def check(in_flight: int) -> None:
            self._policy.check(route, request.amount, request.min_amount_out, in_flight)

        candidate = Transfer(
            id=uuid4(),
            source_treasury_id=request.source_treasury_id,
            destination_treasury_id=request.destination_treasury_id,
            provider=request.provider,
            idempotency_key=request.idempotency_key,
            amount=request.amount,
            min_amount_out=request.min_amount_out,
            status="PendingSend",
            provider_ref=None,
            last_error=None,
            deadline_at=self._clock() + timedelta(seconds=self._policy.timeout_seconds),
        )
        transfer, created = await self._repo.claim(candidate, check)
        if not created:
            return transfer  # an existing transfer: never send again, whatever its state
        return await self._send(transfer, route, destination.safe_address)

    async def _send(self, transfer: Transfer, route: BridgeRoute, recipient: str) -> Transfer:
        send = BridgeSendRequest(
            transfer.id,
            transfer.idempotency_key,
            route,
            transfer.amount,
            transfer.min_amount_out,
            recipient,
        )
        try:
            ref = await self._adapter.send(send)
        except BridgeRefused as refused:
            await self._repo.transition(
                transfer.id, ("PendingSend",), "Failed", last_error=refused.code
            )
        except Exception as error:  # ambiguous: the provider may have accepted it
            logger.warning("bridge_send_ambiguous", extra={"transfer_id": str(transfer.id)})
            await self._repo.transition(
                transfer.id, ("PendingSend",), "Unknown", last_error=type(error).__name__
            )
        else:
            await self._repo.transition(transfer.id, ("PendingSend",), "Sent", provider_ref=ref)
        return await self._require(transfer.id)

    async def settle(self, transfer_id: UUID) -> Transfer:
        """Observe the provider for an open transfer; never sends."""

        transfer = await self._require(transfer_id)
        if transfer.status not in OPEN_STATUSES:
            return transfer
        now = self._clock()
        try:
            status = await self._adapter.status(transfer.idempotency_key)
        except Exception:  # status unreadable: keep state, but a passed deadline is Unknown
            status = None
        if status is not None and status.state is ProviderState.ARRIVED:
            if (status.amount_out or 0) >= transfer.min_amount_out:
                await self._repo.transition(transfer.id, OPEN_STATUSES, "Completed")
            else:
                await self._repo.transition(
                    transfer.id, OPEN_STATUSES, "Unknown", last_error="ARRIVAL_AMOUNT_MISMATCH"
                )
        elif status is not None and status.state is ProviderState.FAILED:
            await self._repo.transition(
                transfer.id, OPEN_STATUSES, "Failed", last_error="PROVIDER_FAILED"
            )
        elif transfer.status == "PendingSend" or now > transfer.deadline_at:
            # Not found / in transit past the deadline / crashed before the send was recorded.
            error = "TIMED_OUT" if now > transfer.deadline_at else "SEND_NOT_CONFIRMED"
            await self._repo.transition(
                transfer.id, ("PendingSend", "Sent"), "Unknown", last_error=error
            )
        return await self._require(transfer.id)

    async def settle_open(self, source_treasury_id: UUID) -> list[Transfer]:
        open_rows = await self._repo.open_transfers(source_treasury_id)
        return [await self.settle(row.id) for row in open_rows]

    async def in_flight(self, source_treasury_id: UUID) -> int:
        """Funds that left the source but are not yet verified at the destination.

        Reported separately: balances come from chain reads, so these funds are in neither
        treasury's balance until the arrival is verified (Completed).
        """

        return await self._repo.in_flight_total(source_treasury_id)

    async def _require(self, transfer_id: UUID) -> Transfer:
        transfer = await self._repo.get(transfer_id)
        if transfer is None:
            raise LookupError(str(transfer_id))
        return transfer


class PgBridgeRepository:
    """asyncpg implementation over ``bridge_transfers``."""

    _COLUMNS = (
        "id, source_treasury_id, destination_treasury_id, provider, idempotency_key, "
        "amount::text AS amount, min_amount_out::text AS min_amount_out, status, provider_ref, "
        "last_error, deadline_at"
    )

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    @staticmethod
    def _row(row: asyncpg.Record) -> Transfer:
        return Transfer(
            id=row["id"],
            source_treasury_id=row["source_treasury_id"],
            destination_treasury_id=row["destination_treasury_id"],
            provider=row["provider"],
            idempotency_key=row["idempotency_key"],
            amount=int(row["amount"]),
            min_amount_out=int(row["min_amount_out"]),
            status=row["status"],
            provider_ref=row["provider_ref"],
            last_error=row["last_error"],
            deadline_at=row["deadline_at"],
        )

    async def treasury(self, treasury_id: UUID) -> TreasuryInfo | None:
        row = await self._pool.fetchrow(
            "SELECT t.org_id, t.chain_id, w.safe_address FROM treasuries AS t "
            "JOIN treasury_wallets AS w ON w.treasury_id = t.id AND w.role = 'SOURCE' "
            "WHERE t.id = $1",
            treasury_id,
        )
        if row is None:
            return None
        return TreasuryInfo(row["org_id"], row["chain_id"], "0x" + bytes(row["safe_address"]).hex())

    async def claim(
        self, transfer: Transfer, check_in_flight: Callable[[int], None]
    ) -> tuple[Transfer, bool]:
        async with self._pool.acquire() as connection, connection.transaction():
            await connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended('bridge:' || $1::text, 0))",
                str(transfer.source_treasury_id),
            )
            existing = await connection.fetchrow(
                f"SELECT {self._COLUMNS} FROM bridge_transfers "
                "WHERE source_treasury_id = $1 AND idempotency_key = $2",
                transfer.source_treasury_id,
                transfer.idempotency_key,
            )
            if existing is not None:
                return self._row(existing), False
            total = await connection.fetchval(
                "SELECT COALESCE(sum(amount), 0)::text FROM bridge_transfers "
                "WHERE source_treasury_id = $1 AND status = ANY($2::text[])",
                transfer.source_treasury_id,
                list(OPEN_STATUSES),
            )
            check_in_flight(int(total))
            await connection.execute(
                "INSERT INTO bridge_transfers (id, source_treasury_id, destination_treasury_id, "
                "provider, idempotency_key, amount, min_amount_out, status, deadline_at) "
                "VALUES ($1, $2, $3, $4, $5, $6::numeric, $7::numeric, 'PendingSend', $8)",
                transfer.id,
                transfer.source_treasury_id,
                transfer.destination_treasury_id,
                transfer.provider,
                transfer.idempotency_key,
                str(transfer.amount),
                str(transfer.min_amount_out),
                transfer.deadline_at,
            )
            return transfer, True

    async def transition(
        self,
        transfer_id: UUID,
        expected: tuple[str, ...],
        status: str,
        *,
        provider_ref: str | None = None,
        last_error: str | None = None,
    ) -> bool:
        result = await self._pool.execute(
            "UPDATE bridge_transfers SET status = $3::text, "
            "provider_ref = COALESCE($4, provider_ref), last_error = $5, "
            "sent_at = CASE WHEN $3::text = 'Sent' THEN now() ELSE sent_at END, "
            "settled_at = CASE WHEN $3::text IN ('Completed', 'Failed') THEN now() ELSE settled_at END "
            "WHERE id = $1 AND status = ANY($2::text[])",
            transfer_id,
            list(expected),
            status,
            provider_ref,
            last_error,
        )
        return bool(result == "UPDATE 1")

    async def open_transfers(self, source_treasury_id: UUID) -> list[Transfer]:
        rows = await self._pool.fetch(
            f"SELECT {self._COLUMNS} FROM bridge_transfers "
            "WHERE source_treasury_id = $1 AND status = ANY($2::text[]) ORDER BY created_at",
            source_treasury_id,
            list(OPEN_STATUSES),
        )
        return [self._row(row) for row in rows]

    async def get(self, transfer_id: UUID) -> Transfer | None:
        row = await self._pool.fetchrow(
            f"SELECT {self._COLUMNS} FROM bridge_transfers WHERE id = $1", transfer_id
        )
        return None if row is None else self._row(row)

    async def in_flight_total(self, source_treasury_id: UUID) -> int:
        total = await self._pool.fetchval(
            "SELECT COALESCE(sum(amount), 0)::text FROM bridge_transfers "
            "WHERE source_treasury_id = $1 AND status = ANY($2::text[])",
            source_treasury_id,
            list(OPEN_STATUSES),
        )
        return int(total)
