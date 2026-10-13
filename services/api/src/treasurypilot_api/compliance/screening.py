from __future__ import annotations

import asyncio
import logging
import re
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from treasurypilot_api.compliance.models import ScreeningListEntry
from treasurypilot_api.mandate.models import Screening, ScreeningResult, uuid7

SCREENING_TTL = timedelta(hours=24)
# M14-D7: a refresh before PAY waits at most this long, then fails closed.
PROVIDER_TIMEOUT = timedelta(seconds=5)
# Environments where the fixture list may stand in for a sanctions provider.
FIXTURE_ENVIRONMENTS = frozenset({"local", "test", "demo"})
_ADDRESS = re.compile(r"^(?:0[xX])?[0-9a-fA-F]{40}$")

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ProviderResult:
    result: ScreeningResult
    source_ref: str | None = None


@dataclass(frozen=True, slots=True)
class ScreeningRecord:
    id: uuid.UUID
    payee_id: uuid.UUID | None
    address: bytes
    chain_id: int | None
    provider: str
    result: ScreeningResult
    source_ref: str | None
    checked_at: datetime
    ttl_until: datetime | None


class ScreeningProviderError(Exception):
    """The provider could not answer (outage, auth or quota); screening fails closed."""


class ScreeningProvider(Protocol):
    name: str

    async def screen(self, *, address: bytes, chain_id: int) -> ProviderResult:
        """Return CLEAR or HIT; raise ``ScreeningProviderError`` when unable to answer."""
        ...


class ScreeningRepository(Protocol):
    async def latest(
        self, *, address: bytes, chain_id: int, provider: str
    ) -> ScreeningRecord | None: ...

    async def record(
        self,
        *,
        payee_id: uuid.UUID | None,
        address: bytes,
        chain_id: int,
        provider: str,
        result: ScreeningResult,
        source_ref: str | None,
        checked_at: datetime,
        ttl_until: datetime | None,
    ) -> ScreeningRecord: ...


class SqlAlchemyScreeningRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def latest(
        self, *, address: bytes, chain_id: int, provider: str
    ) -> ScreeningRecord | None:
        async with self._sessions() as session:
            row = await session.scalar(
                select(Screening)
                .where(
                    Screening.address == address,
                    Screening.chain_id == chain_id,
                    Screening.provider == provider,
                )
                .order_by(Screening.checked_at.desc(), Screening.id.desc())
                .limit(1)
            )
            return _record(row) if row is not None else None

    async def record(
        self,
        *,
        payee_id: uuid.UUID | None,
        address: bytes,
        chain_id: int,
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
                chain_id=chain_id,
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

    def __init__(self, entries: Mapping[bytes, str]) -> None:
        self._entries = dict(entries)

    async def screen(self, *, address: bytes, chain_id: int) -> ProviderResult:
        source_ref = self._entries.get(address)
        if source_ref is None:
            return ProviderResult(ScreeningResult.CLEAR)
        return ProviderResult(ScreeningResult.HIT, source_ref)


class DatabaseFixtureScreeningProvider:
    """Fixture provider backed by the ``screening_lists`` table (TEST DATA)."""

    name = FixtureScreeningProvider.name

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def screen(self, *, address: bytes, chain_id: int) -> ProviderResult:
        try:
            async with self._sessions() as session:
                label = await session.scalar(
                    select(ScreeningListEntry.source_label)
                    .where(ScreeningListEntry.address == address)
                    .order_by(ScreeningListEntry.added_at)
                    .limit(1)
                )
        except (SQLAlchemyError, OSError) as exc:
            raise ScreeningProviderError("screening list unavailable") from exc
        if label is None:
            return ProviderResult(ScreeningResult.CLEAR)
        return ProviderResult(ScreeningResult.HIT, label)


class UnconfiguredScreeningProvider:
    """Stands in when no real provider is configured outside dev/test: always fails closed."""

    name = "unconfigured"

    async def screen(self, *, address: bytes, chain_id: int) -> ProviderResult:
        raise ScreeningProviderError("no sanctions screening provider is configured")


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
        timeout: timedelta = PROVIDER_TIMEOUT,
    ) -> None:
        self._repository = repository
        self._provider = provider
        self._clock = clock
        self._timeout = timeout

    async def screen(
        self,
        *,
        address: str | bytes,
        chain_id: int,
        payee_id: uuid.UUID | None = None,
    ) -> ScreeningRecord:
        # Caller mistakes are raised, never recorded as a provider ERROR.
        normalized = normalize_address(address)
        if isinstance(chain_id, bool) or not isinstance(chain_id, int) or chain_id <= 0:
            raise ValueError("chain_id must be a positive integer")
        now = self._clock()
        if now.utcoffset() is None:
            raise ValueError("the screening clock must return timezone-aware datetimes")

        provider = self._provider.name
        cached = await self._repository.latest(
            address=normalized, chain_id=chain_id, provider=provider
        )
        if (
            cached is not None
            and cached.result != ScreeningResult.ERROR
            and cached.ttl_until is not None
            and now < cached.ttl_until
        ):
            if payee_id is None or cached.payee_id == payee_id:
                return cached
            # Record the reused result against this payee so its history shows the check.
            return await self._repository.record(
                payee_id=payee_id,
                address=normalized,
                chain_id=chain_id,
                provider=provider,
                result=cached.result,
                source_ref=cached.source_ref,
                checked_at=cached.checked_at,
                ttl_until=cached.ttl_until,
            )

        try:
            async with asyncio.timeout(self._timeout.total_seconds()):
                outcome = await self._provider.screen(address=normalized, chain_id=chain_id)
            result = ScreeningResult(outcome.result)
            source_ref = outcome.source_ref
        except (ScreeningProviderError, TimeoutError, OSError) as error:
            # Fail closed (BR-085), but leave a trace: ops must see why payments block.
            logger.warning(
                "screening_provider_failed",
                extra={"provider": provider, "error": type(error).__name__},
                exc_info=True,
            )
            result = ScreeningResult.ERROR
            source_ref = None
        ttl_until = now + SCREENING_TTL if result != ScreeningResult.ERROR else None
        return await self._repository.record(
            payee_id=payee_id,
            address=normalized,
            chain_id=chain_id,
            provider=provider,
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


def build_screening_service(
    environment: str, sessions: async_sessionmaker[AsyncSession]
) -> ScreeningService:
    """The fixture list is only allowed in dev/test/demo; elsewhere screening fails closed."""

    provider: ScreeningProvider
    if environment.casefold() in FIXTURE_ENVIRONMENTS:
        provider = DatabaseFixtureScreeningProvider(sessions)
    else:
        logger.error("screening_provider_unconfigured", extra={"environment": environment})
        provider = UnconfiguredScreeningProvider()
    return ScreeningService(SqlAlchemyScreeningRepository(sessions), provider)


def normalize_address(address: str | bytes) -> bytes:
    """Return the 20 address bytes; hex input matches regardless of case or checksum."""

    if isinstance(address, bytes):
        if len(address) == 20:
            return address
        raise ValueError("EVM addresses must be 20 bytes")
    value = address.strip()
    if not _ADDRESS.fullmatch(value):
        raise ValueError("invalid EVM address")
    return bytes.fromhex(value[2:] if value[:2] in ("0x", "0X") else value)


def _record(row: Screening) -> ScreeningRecord:
    return ScreeningRecord(
        id=row.id,
        payee_id=row.payee_id,
        address=row.address,
        chain_id=row.chain_id,
        provider=row.provider,
        result=ScreeningResult(row.result),
        source_ref=row.source_ref,
        checked_at=row.checked_at,
        ttl_until=row.ttl_until,
    )
