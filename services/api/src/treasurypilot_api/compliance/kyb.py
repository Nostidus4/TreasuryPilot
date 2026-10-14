"""KYB (business verification) adapter; its status gates mainnet treasury activation (F-111)."""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from treasurypilot_api.compliance.models import KybVerification
from treasurypilot_api.compliance.screening import FIXTURE_ENVIRONMENTS
from treasurypilot_api.identity.models import uuid7

PROVIDER_TIMEOUT = timedelta(seconds=10)

logger = logging.getLogger(__name__)


class KybStatus(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


@dataclass(frozen=True, slots=True)
class KybOutcome:
    status: KybStatus
    provider_ref: str | None = None


@dataclass(frozen=True, slots=True)
class KybRecord:
    id: uuid.UUID
    organization_id: uuid.UUID
    provider: str
    status: KybStatus
    provider_ref: str | None
    checked_at: datetime


class KybProviderError(Exception):
    """The provider could not answer (outage, auth, quota, or none configured); fails closed."""


class KybRequired(Exception):
    """The organization has no APPROVED KYB result from the configured provider."""

    def __init__(self, status: KybStatus | None) -> None:
        super().__init__("KYB_REQUIRED")
        self.status = status


class KybProvider(Protocol):
    name: str

    async def verify(
        self, *, organization_id: uuid.UUID, legal_name: str, country: str | None
    ) -> KybOutcome:
        """Return the provider's verdict; raise ``KybProviderError`` when unable to answer."""
        ...


class KybRepository(Protocol):
    async def latest(self, *, organization_id: uuid.UUID, provider: str) -> KybRecord | None: ...

    async def record(
        self,
        *,
        organization_id: uuid.UUID,
        provider: str,
        status: KybStatus,
        provider_ref: str | None,
        checked_at: datetime,
    ) -> KybRecord: ...


class SqlAlchemyKybRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def latest(self, *, organization_id: uuid.UUID, provider: str) -> KybRecord | None:
        async with self._sessions() as session:
            row = await session.scalar(
                select(KybVerification)
                .where(
                    KybVerification.org_id == organization_id, KybVerification.provider == provider
                )
                .order_by(KybVerification.checked_at.desc(), KybVerification.id.desc())
                .limit(1)
            )
            return _record(row) if row is not None else None

    async def record(
        self,
        *,
        organization_id: uuid.UUID,
        provider: str,
        status: KybStatus,
        provider_ref: str | None,
        checked_at: datetime,
    ) -> KybRecord:
        async with self._sessions() as session, session.begin():
            row = KybVerification(
                id=uuid7(),
                org_id=organization_id,
                provider=provider,
                status=status.value,
                provider_ref=provider_ref,
                checked_at=checked_at,
            )
            session.add(row)
            await session.flush()
            return _record(row)


class FixtureKybProvider:
    """Deterministic TEST DATA: approves every business unless its legal name is listed."""

    name = "fixture-test"

    def __init__(self, outcomes: Mapping[str, KybStatus]) -> None:
        self._outcomes = {name.casefold(): status for name, status in outcomes.items()}

    async def verify(
        self, *, organization_id: uuid.UUID, legal_name: str, country: str | None
    ) -> KybOutcome:
        status = self._outcomes.get(legal_name.strip().casefold(), KybStatus.APPROVED)
        return KybOutcome(status, f"TEST DATA fixture {status.value}")


class UnconfiguredKybProvider:
    """Stands in when no real vendor is configured outside dev/test: always fails closed."""

    name = "unconfigured"

    async def verify(
        self, *, organization_id: uuid.UUID, legal_name: str, country: str | None
    ) -> KybOutcome:
        raise KybProviderError("no KYB provider is configured")


class KybService:
    def __init__(
        self,
        repository: KybRepository,
        provider: KybProvider,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        timeout: timedelta = PROVIDER_TIMEOUT,
    ) -> None:
        self._repository = repository
        self._provider = provider
        self._clock = clock
        self._timeout = timeout

    async def verify(
        self, *, organization_id: uuid.UUID, legal_name: str, country: str | None
    ) -> KybRecord:
        """Ask the provider and record its verdict; a provider failure records nothing."""
        try:
            async with asyncio.timeout(self._timeout.total_seconds()):
                outcome = await self._provider.verify(
                    organization_id=organization_id, legal_name=legal_name, country=country
                )
        except KybProviderError:
            raise
        except Exception as error:
            logger.warning(
                "kyb_provider_failed",
                extra={"provider": self._provider.name, "error": type(error).__name__},
                exc_info=True,
            )
            raise KybProviderError("KYB provider failed") from error
        return await self._repository.record(
            organization_id=organization_id,
            provider=self._provider.name,
            status=KybStatus(outcome.status),
            provider_ref=outcome.provider_ref,
            checked_at=self._clock(),
        )

    async def require_approved(self, organization_id: uuid.UUID) -> KybRecord:
        """The latest result from the configured provider must be APPROVED."""
        record = await self._repository.latest(
            organization_id=organization_id, provider=self._provider.name
        )
        if record is None or record.status != KybStatus.APPROVED:
            raise KybRequired(record.status if record is not None else None)
        return record


def build_kyb_service(environment: str, sessions: async_sessionmaker[AsyncSession]) -> KybService:
    """The fixture provider is only allowed in dev/test/demo; elsewhere KYB fails closed."""
    provider: KybProvider
    if environment.casefold() in FIXTURE_ENVIRONMENTS:
        provider = FixtureKybProvider({})
    else:
        logger.error("kyb_provider_unconfigured", extra={"environment": environment})
        provider = UnconfiguredKybProvider()
    return KybService(SqlAlchemyKybRepository(sessions), provider)


def _record(row: KybVerification) -> KybRecord:
    return KybRecord(
        id=row.id,
        organization_id=row.org_id,
        provider=row.provider,
        status=KybStatus(row.status),
        provider_ref=row.provider_ref,
        checked_at=row.checked_at,
    )
