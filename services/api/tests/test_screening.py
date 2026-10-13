from __future__ import annotations

import asyncio
import os
import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from treasurypilot_api.compliance.screening import (
    FixtureScreeningProvider,
    ProviderResult,
    ScreeningBlocked,
    ScreeningProviderError,
    ScreeningRecord,
    ScreeningService,
    UnconfiguredScreeningProvider,
    build_screening_service,
    normalize_address,
)
from treasurypilot_api.identity.models import Organization
from treasurypilot_api.mandate.models import ScreeningResult

API_ROOT = Path(__file__).parents[1]
NOW = datetime(2026, 10, 13, tzinfo=UTC)
ORG_ID = uuid.UUID("00000000-0000-7000-8000-000000000010")
CLEAN = "0x" + "ab" * 20
LISTED = "0x000000000000000000000000000000000000dEaD"


class MemoryRepository:
    def __init__(self) -> None:
        self.rows: list[ScreeningRecord] = []

    async def latest(
        self, *, organization_id: uuid.UUID, address: bytes, chain_id: int, provider: str
    ) -> ScreeningRecord | None:
        matches = [
            row
            for row in self.rows
            if (row.organization_id, row.address, row.chain_id, row.provider)
            == (organization_id, address, chain_id, provider)
        ]
        return matches[-1] if matches else None

    async def record(self, **fields: object) -> ScreeningRecord:
        row = ScreeningRecord(id=uuid.uuid4(), **fields)  # type: ignore[arg-type]
        self.rows.append(row)
        return row


class CountingProvider(FixtureScreeningProvider):
    def __init__(self, name: str = "fixture-test") -> None:
        super().__init__({normalize_address(LISTED): "TEST DATA"})
        self.name = name
        self.calls = 0

    async def screen(self, *, address: bytes, chain_id: int) -> ProviderResult:
        self.calls += 1
        return await super().screen(address=address, chain_id=chain_id)


class HangingProvider:
    name = "slow"

    async def screen(self, *, address: bytes, chain_id: int) -> ProviderResult:
        await asyncio.sleep(60)
        raise AssertionError("unreachable")


def service(
    provider: object, repo: MemoryRepository | None = None, **kw: object
) -> ScreeningService:
    return ScreeningService(repo or MemoryRepository(), provider, clock=lambda: NOW, **kw)  # type: ignore[arg-type]


def test_hit_maps_to_screening_hit_and_error_to_data_missing() -> None:
    with pytest.raises(ScreeningBlocked, match="SCREENING_HIT"):
        asyncio.run(
            service(CountingProvider()).require_clear(
                organization_id=ORG_ID, address=LISTED, chain_id=1
            )
        )
    with pytest.raises(ScreeningBlocked, match="DATA_MISSING") as blocked:
        asyncio.run(
            service(UnconfiguredScreeningProvider()).require_clear(
                organization_id=ORG_ID, address=CLEAN, chain_id=1
            )
        )
    assert blocked.value.record.ttl_until is None  # an ERROR is never cached


def test_provider_timeout_fails_closed() -> None:
    slow = service(HangingProvider(), timeout=timedelta(milliseconds=20))
    with pytest.raises(ScreeningBlocked, match="DATA_MISSING"):
        asyncio.run(slow.require_clear(organization_id=ORG_ID, address=CLEAN, chain_id=1))


def test_cache_is_scoped_to_chain_and_provider() -> None:
    repo = MemoryRepository()
    fixture = CountingProvider()
    asyncio.run(service(fixture, repo).screen(organization_id=ORG_ID, address=CLEAN, chain_id=1))
    asyncio.run(service(fixture, repo).screen(organization_id=ORG_ID, address=CLEAN, chain_id=1))
    assert fixture.calls == 1
    asyncio.run(service(fixture, repo).screen(organization_id=ORG_ID, address=CLEAN, chain_id=137))
    assert fixture.calls == 2
    other_org = uuid.uuid4()
    asyncio.run(service(fixture, repo).screen(organization_id=other_org, address=CLEAN, chain_id=1))
    assert fixture.calls == 3  # one tenant's result is never reused by another
    commercial = CountingProvider(name="commercial")
    asyncio.run(service(commercial, repo).screen(organization_id=ORG_ID, address=CLEAN, chain_id=1))
    assert commercial.calls == 1  # fixture CLEAR rows never clear for another provider


def test_cached_result_is_recorded_for_the_requesting_payee() -> None:
    repo = MemoryRepository()
    fixture = CountingProvider()
    payee_a, payee_b = uuid.uuid4(), uuid.uuid4()
    asyncio.run(
        service(fixture, repo).screen(
            organization_id=ORG_ID, address=CLEAN, chain_id=1, payee_id=payee_a
        )
    )
    reused = asyncio.run(
        service(fixture, repo).screen(
            organization_id=ORG_ID, address=CLEAN, chain_id=1, payee_id=payee_b
        )
    )
    assert fixture.calls == 1
    assert reused.payee_id == payee_b
    assert reused.checked_at == repo.rows[0].checked_at


def test_expired_cache_is_refreshed() -> None:
    repo = MemoryRepository()
    fixture = CountingProvider()
    asyncio.run(service(fixture, repo).screen(organization_id=ORG_ID, address=CLEAN, chain_id=1))
    repo.rows[0] = replace(repo.rows[0], ttl_until=NOW - timedelta(seconds=1))
    asyncio.run(service(fixture, repo).screen(organization_id=ORG_ID, address=CLEAN, chain_id=1))
    assert fixture.calls == 2


@pytest.mark.parametrize(("address", "chain_id"), [("0x123", 1), (CLEAN, 0), (CLEAN, -1)])
def test_caller_mistakes_raise_instead_of_recording_an_error(address: str, chain_id: int) -> None:
    repo = MemoryRepository()
    with pytest.raises(ValueError):
        asyncio.run(
            service(CountingProvider(), repo).screen(
                organization_id=ORG_ID, address=address, chain_id=chain_id
            )
        )
    assert repo.rows == []


def test_naive_clock_is_rejected() -> None:
    naive = ScreeningService(
        MemoryRepository(), CountingProvider(), clock=lambda: datetime(2026, 1, 1)
    )
    with pytest.raises(ValueError, match="timezone"):
        asyncio.run(naive.screen(organization_id=ORG_ID, address=CLEAN, chain_id=1))


def test_addresses_match_regardless_of_case_or_prefix() -> None:
    expected = bytes.fromhex("000000000000000000000000000000000000dead")
    for value in (LISTED, LISTED.lower(), "0X000000000000000000000000000000000000DEAD", LISTED[2:]):
        assert normalize_address(value) == expected


def test_production_never_uses_the_fixture_list() -> None:
    sessions = async_sessionmaker(create_async_engine("postgresql+asyncpg://offline/offline"))
    prod = build_screening_service("production", sessions)
    assert isinstance(prod._provider, UnconfiguredScreeningProvider)
    with pytest.raises(ScreeningProviderError):
        asyncio.run(prod._provider.screen(address=bytes(20), chain_id=1))


def _alembic(database_url: str) -> Config:
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


@pytest.mark.skipif(
    "TP_TEST_DATABASE_URL" not in os.environ,
    reason="TP_TEST_DATABASE_URL is required for the PostgreSQL screening test",
)
def test_database_fixture_list_and_chain_scoped_cache_on_postgres() -> None:
    database_url = os.environ["TP_TEST_DATABASE_URL"]
    config = _alembic(database_url)
    command.upgrade(config, "head")

    async def run() -> None:
        engine = create_async_engine(database_url)
        try:
            sessions = async_sessionmaker(engine)
            async with sessions.begin() as session:
                session.add(Organization(id=ORG_ID, name="Screening test"))
            screening = build_screening_service("test", sessions)
            hit = await screening.screen(organization_id=ORG_ID, address=LISTED, chain_id=11155111)
            assert hit.result == ScreeningResult.HIT
            assert hit.source_ref is not None and "TEST DATA" in hit.source_ref
            first = await screening.screen(organization_id=ORG_ID, address=CLEAN, chain_id=11155111)
            again = await screening.screen(organization_id=ORG_ID, address=CLEAN, chain_id=11155111)
            other_chain = await screening.screen(organization_id=ORG_ID, address=CLEAN, chain_id=1)
            assert again.id == first.id
            assert other_chain.id != first.id and other_chain.chain_id == 1
        finally:
            await engine.dispose()

    try:
        command.check(config)
        asyncio.run(run())
    finally:
        command.downgrade(config, "base")
