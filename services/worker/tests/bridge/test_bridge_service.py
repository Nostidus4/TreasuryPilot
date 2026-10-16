"""Bridge service with an in-memory ledger and the deterministic fake provider (EXE-L03)."""

from __future__ import annotations

import asyncio
import functools
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest

from treasurypilot_worker.bridge.adapter import BridgeRoute, FakeBridgeAdapter
from treasurypilot_worker.bridge.policy import BridgePolicy, BridgeRejected, parse_routes
from treasurypilot_worker.bridge.service import (
    OPEN_STATUSES,
    BridgeRequest,
    BridgeService,
    Transfer,
    TreasuryInfo,
)

ORG = uuid4()
SOURCE = uuid4()
DESTINATION = uuid4()
ROUTE = BridgeRoute("fake", 1, 8453)
START = datetime(2026, 10, 16, tzinfo=UTC)


def sync(test: Callable[..., Any]) -> Callable[..., None]:
    """The worker suite has no async pytest plugin: run each coroutine test with asyncio.run."""

    @functools.wraps(test)
    def wrapper(*args: Any, **kwargs: Any) -> None:
        asyncio.run(test(*args, **kwargs))

    return wrapper


class MemoryRepository:
    def __init__(self) -> None:
        self.rows: dict[UUID, Transfer] = {}
        self.treasuries = {
            SOURCE: TreasuryInfo(ORG, 1, "0x" + "11" * 20),
            DESTINATION: TreasuryInfo(ORG, 8453, "0x" + "22" * 20),
        }

    async def treasury(self, treasury_id: UUID) -> TreasuryInfo | None:
        return self.treasuries.get(treasury_id)

    async def claim(
        self, transfer: Transfer, check_in_flight: Callable[[int], None]
    ) -> tuple[Transfer, bool]:
        for row in self.rows.values():
            if (row.source_treasury_id, row.idempotency_key) == (
                transfer.source_treasury_id,
                transfer.idempotency_key,
            ):
                return row, False
        check_in_flight(await self.in_flight_total(transfer.source_treasury_id))
        self.rows[transfer.id] = transfer
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
        row = self.rows[transfer_id]
        if row.status not in expected:
            return False
        self.rows[transfer_id] = replace(
            row,
            status=status,
            provider_ref=provider_ref or row.provider_ref,
            last_error=last_error,
        )
        return True

    async def open_transfers(self, source_treasury_id: UUID) -> list[Transfer]:
        return [r for r in self.rows.values() if r.status in OPEN_STATUSES]

    async def get(self, transfer_id: UUID) -> Transfer | None:
        return self.rows.get(transfer_id)

    async def in_flight_total(self, source_treasury_id: UUID) -> int:
        return sum(r.amount for r in self.rows.values() if r.status in OPEN_STATUSES)


class Clock:
    def __init__(self) -> None:
        self.now = START

    def __call__(self) -> datetime:
        return self.now


POLICY = BridgePolicy(
    allowed_routes=frozenset({ROUTE}),
    max_transfer_amount=1_000_000,
    max_in_flight_amount=1_500_000,
    timeout_seconds=3600,
)


def _request(key: str = "k1", amount: int = 1_000, min_out: int = 990) -> BridgeRequest:
    return BridgeRequest(SOURCE, DESTINATION, "fake", key, amount, min_out)


def _make(
    adapter: FakeBridgeAdapter | None = None, policy: BridgePolicy = POLICY
) -> tuple[BridgeService, MemoryRepository, FakeBridgeAdapter, Clock]:
    repo, clock = MemoryRepository(), Clock()
    adapter = adapter or FakeBridgeAdapter()
    return BridgeService(repo, adapter, policy, clock), repo, adapter, clock


@sync
async def test_happy_path_sends_once_and_verifies_arrival() -> None:
    service, _, adapter, _ = _make()
    transfer = await service.initiate(_request())
    assert transfer.status == "Sent"
    assert await service.in_flight(SOURCE) == 1_000
    adapter.arrive("k1", 995)
    settled = await service.settle(transfer.id)
    assert settled.status == "Completed"
    assert await service.in_flight(SOURCE) == 0
    assert adapter.send_calls == {"k1": 1}


@sync
async def test_timeout_after_accept_does_not_send_a_second_transfer() -> None:
    service, _, adapter, _ = _make(FakeBridgeAdapter(fail_send="timeout_after_accept"))
    first = await service.initiate(_request())
    assert first.status == "Unknown"
    # The caller retries after the timeout, and so does a settle pass.
    again = await service.initiate(_request())
    await service.settle(first.id)
    await service.settle(first.id)
    assert again.id == first.id
    assert adapter.send_calls == {"k1": 1}
    # Funds stay counted as in flight until the arrival is observed.
    assert await service.in_flight(SOURCE) == 1_000
    adapter.arrive("k1", 990)
    assert (await service.settle(first.id)).status == "Completed"
    assert adapter.send_calls == {"k1": 1}


@sync
async def test_timeout_before_accept_stays_unknown_and_is_never_resent() -> None:
    service, _, adapter, clock = _make(FakeBridgeAdapter(fail_send="timeout_before_accept"))
    transfer = await service.initiate(_request())
    clock.now += timedelta(hours=2)
    settled = await service.settle(transfer.id)
    assert settled.status == "Unknown"
    await service.initiate(_request())
    assert adapter.send_calls == {"k1": 1}


@sync
async def test_provider_refusal_is_failed_and_releases_in_flight() -> None:
    service, _, _, _ = _make(FakeBridgeAdapter(fail_send="refuse"))
    transfer = await service.initiate(_request())
    assert (transfer.status, transfer.last_error) == ("Failed", "ROUTE_UNAVAILABLE")
    assert await service.in_flight(SOURCE) == 0


@sync
async def test_deadline_without_arrival_becomes_unknown_not_failed() -> None:
    service, _, adapter, clock = _make()
    transfer = await service.initiate(_request())
    assert (await service.settle(transfer.id)).status == "Sent"
    clock.now += timedelta(seconds=3601)
    settled = await service.settle(transfer.id)
    assert (settled.status, settled.last_error) == ("Unknown", "TIMED_OUT")
    assert await service.in_flight(SOURCE) == 1_000
    assert adapter.send_calls == {"k1": 1}


@sync
async def test_status_outage_keeps_state_until_deadline() -> None:
    service, _, adapter, clock = _make()
    transfer = await service.initiate(_request())
    adapter.status_error = True
    assert (await service.settle(transfer.id)).status == "Sent"
    clock.now += timedelta(hours=2)
    assert (await service.settle(transfer.id)).status == "Unknown"


@sync
async def test_arrival_below_minimum_is_unknown_for_review() -> None:
    service, _, adapter, _ = _make()
    transfer = await service.initiate(_request())
    adapter.arrive("k1", 500)
    settled = await service.settle(transfer.id)
    assert (settled.status, settled.last_error) == ("Unknown", "ARRIVAL_AMOUNT_MISMATCH")


@sync
async def test_provider_failure_marks_failed() -> None:
    service, _, adapter, _ = _make()
    transfer = await service.initiate(_request())
    adapter.fail("k1")
    assert (await service.settle(transfer.id)).status == "Failed"
    assert await service.in_flight(SOURCE) == 0


@sync
async def test_crash_between_claim_and_send_is_unknown_not_resent() -> None:
    service, repo, adapter, _ = _make()
    pending = Transfer(
        uuid4(), SOURCE, DESTINATION, "fake", "k1", 1_000, 990, "PendingSend", None, None,
        START + timedelta(hours=1),
    )  # fmt: skip
    repo.rows[pending.id] = pending
    assert (await service.initiate(_request())).id == pending.id
    assert (await service.settle(pending.id)).status == "Unknown"
    assert adapter.send_calls == {}


@pytest.mark.parametrize(
    ("request_", "code"),
    [
        (BridgeRequest(SOURCE, DESTINATION, "other", "k", 1_000, 990), "ROUTE_NOT_ALLOWLISTED"),
        (_request(amount=2_000_000, min_out=1_000), "TRANSFER_LIMIT_EXCEEDED"),
        (_request(min_out=2_000), "INVALID_AMOUNT"),
        (_request(amount=0, min_out=0), "INVALID_AMOUNT"),
        (BridgeRequest(SOURCE, SOURCE, "fake", "k", 1_000, 990), "SAME_CHAIN"),
        (BridgeRequest(SOURCE, uuid4(), "fake", "k", 1_000, 990), "TREASURY_NOT_FOUND"),
    ],
)
@sync
async def test_policy_rejections_send_nothing(request_: BridgeRequest, code: str) -> None:
    service, repo, adapter, _ = _make()
    with pytest.raises(BridgeRejected) as raised:
        await service.initiate(request_)
    assert raised.value.code == code
    assert adapter.send_calls == {} and repo.rows == {}


@sync
async def test_treasuries_of_different_orgs_are_rejected() -> None:
    service, repo, adapter, _ = _make()
    repo.treasuries[DESTINATION] = TreasuryInfo(uuid4(), 8453, "0x" + "22" * 20)
    with pytest.raises(BridgeRejected, match="TREASURIES_NOT_SAME_ORG"):
        await service.initiate(_request())
    assert adapter.send_calls == {}


@sync
async def test_in_flight_limit_counts_open_transfers() -> None:
    service, _, adapter, _ = _make()
    await service.initiate(_request("a", 1_000_000, 990_000))
    with pytest.raises(BridgeRejected, match="IN_FLIGHT_LIMIT_EXCEEDED"):
        await service.initiate(_request("b", 600_000, 590_000))
    adapter.arrive("a", 1_000_000)
    await service.settle_open(SOURCE)
    assert (await service.initiate(_request("b", 600_000, 590_000))).status == "Sent"


@sync
async def test_disabled_by_default() -> None:
    service, _, adapter, _ = _make(policy=BridgePolicy())
    with pytest.raises(BridgeRejected, match="BRIDGING_DISABLED"):
        await service.initiate(_request())
    assert adapter.send_calls == {}


def test_parse_routes() -> None:
    assert parse_routes("fake:1:8453, other:10:1") == frozenset(
        {BridgeRoute("fake", 1, 8453), BridgeRoute("other", 10, 1)}
    )
    assert parse_routes("") == frozenset()
