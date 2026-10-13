from __future__ import annotations

import re
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from treasurypilot_api.mandate.models import Screening, ScreeningResult, uuid7

SCREENING_TTL = timedelta(hours=24)
_ADDRESS = re.compile(r"^(?:0x)?[0-9a-fA-F]{40}$")


@dataclass(frozen=True, slots=True)
class ProviderResult:
    result: ScreeningResult
    source_ref: str | None = None


@dataclass(frozen=True, slots=True)
class ScreeningRecord:
    id: uuid.UUID
    payee_id: uuid.UUID | None
    address: bytes
    provider: str
    result: ScreeningResult
    source_ref: str | None
    checked_at: datetime
    ttl_until: datetime | None


class ScreeningProvider(Protocol):
    name: str

    async def screen(self, *, address: bytes, chain_id: int) -> ProviderResult: ...


class ScreeningRepository(Protocol):
    async def latest(self, *, address: bytes) -> ScreeningRecord | None: ...

    async def record(
        self,
        *,
        payee_id: uuid.UUID | None,
        address: bytes,
        provider: str,
        result: ScreeningResult,
        source_ref: str | None,
        checked_at: datetime,
        ttl_until: datetime | None,
    ) -> ScreeningRecord: ...


class SqlAlchemyScreeningRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def latest(self, *, address: bytes) -> ScreeningRecord | None:
        async with self._sessions() as session:
            row = await session.scalar(
                select(Screening)
                .where(Screening.address == address)
                .order_by(Screening.checked_at.desc(), Screening.id.desc())
                .limit(1)
            )
            return _record(row) if row is not None else None

    async def record(
        self,
        *,
        payee_id: uuid.UUID | None,
        address: bytes,
        provider: str,
        result: ScreeningResult,
        source_ref: str | None,
        checked_at: datetime,
        ttl_until: datetime | None,
    ) -> ScreeningRecord:
        async with self._sessions() as session, session.begin():
            row = Screening(
                id=uuid7(),
                payee_id=payee_id,
                address=address,
                provider=provider,
                result=result.value,
                source_ref=source_ref,
                checked_at=checked_at,
                ttl_until=ttl_until,
            )
            session.add(row)
            await session.flush()
            return _record(row)


class FixtureScreeningProvider:
    """Deterministic EVM fixture data; this provider is not a sanctions service."""

    name = "fixture-test"

    def __init__(self, entries: Mapping[bytes, str] | None = None) -> None:
        self._entries = dict(entries or _FIXTURE_ENTRIES)

    async def screen(self, *, address: bytes, chain_id: int) -> ProviderResult:
        if chain_id <= 0:
            raise ValueError("chain_id must be positive")
        source_ref = self._entries.get(address)
        if source_ref is None:
            return ProviderResult(ScreeningResult.CLEAR)
        return ProviderResult(ScreeningResult.HIT, source_ref)


class ScreeningBlocked(Exception):
    """Screening did not produce a usable CLEAR result."""

    def __init__(self, *, code: str, record: ScreeningRecord) -> None:
        super().__init__(code)
        self.code = code
        self.record = record


class ScreeningService:
    def __init__(
        self,
        repository: ScreeningRepository,
        provider: ScreeningProvider,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._repository = repository
        self._provider = provider
        self._clock = clock

    async def screen(
        self,
        *,
        address: str | bytes,
        chain_id: int,
        payee_id: uuid.UUID | None = None,
    ) -> ScreeningRecord:
        normalized = normalize_address(address)
        now = self._clock()
        cached = await self._repository.latest(address=normalized)
        if (
            cached is not None
            and cached.result != ScreeningResult.ERROR
            and cached.ttl_until is not None
            and now < cached.ttl_until
        ):
            return cached

        try:
            outcome = await self._provider.screen(address=normalized, chain_id=chain_id)
            result = ScreeningResult(outcome.result)
            source_ref = outcome.source_ref
        except Exception:
            result = ScreeningResult.ERROR
            source_ref = None
        ttl_until = now + SCREENING_TTL if result != ScreeningResult.ERROR else None
        return await self._repository.record(
            payee_id=payee_id,
            address=normalized,
            provider=self._provider.name,
            result=result,
            source_ref=source_ref,
            checked_at=now,
            ttl_until=ttl_until,
        )

    async def require_clear(
        self,
        *,
        address: str | bytes,
        chain_id: int,
        payee_id: uuid.UUID | None = None,
    ) -> ScreeningRecord:
        record = await self.screen(address=address, chain_id=chain_id, payee_id=payee_id)
        if record.result == ScreeningResult.HIT:
            raise ScreeningBlocked(code="SCREENING_HIT", record=record)
        if record.result != ScreeningResult.CLEAR:
            raise ScreeningBlocked(code="DATA_MISSING", record=record)
        return record


def normalize_address(address: str | bytes) -> bytes:
    if isinstance(address, bytes):
        if len(address) == 20:
            return address
        raise ValueError("EVM addresses must be 20 bytes")
    value = address.strip()
    if not _ADDRESS.fullmatch(value):
        raise ValueError("invalid EVM address")
    return bytes.fromhex(value.removeprefix("0x").removeprefix("0X"))


def _record(row: Screening) -> ScreeningRecord:
    return ScreeningRecord(
        id=row.id,
        payee_id=row.payee_id,
        address=row.address,
        provider=row.provider,
        result=ScreeningResult(row.result),
        source_ref=row.source_ref,
        checked_at=row.checked_at,
        ttl_until=row.ttl_until,
    )


# TEST DATA only. The public-list sample is a static address from the OFAC
# 2026-03-12 SDN-list update; this is not a live or legally sufficient check.
_FIXTURE_ENTRIES: dict[bytes, str] = {
    bytes.fromhex("cb74874f1e06fcf80a306e06e5379a44b488ba2d"): (
        "TEST DATA — OFAC SDN action 2026-03-12"
    ),
    bytes.fromhex("0330070fd38ec3bb94f58fa55d40368271e9e54a"): (
        "TEST DATA — OFAC SDN action 2026-03-12"
    ),
    bytes.fromhex("000000000000000000000000000000000000dead"): "TEST DATA — TreasuryPilot fixture",
}
