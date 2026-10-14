from __future__ import annotations

import asyncio
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from treasurypilot_api.compliance.kyb import (
    FixtureKybProvider,
    KybProviderError,
    KybRecord,
    KybRequired,
    KybService,
    KybStatus,
    UnconfiguredKybProvider,
    build_kyb_service,
)
from treasurypilot_api.identity.models import Organization
from treasurypilot_api.mandate.governance_service import GovernanceFailure, GovernanceService
from treasurypilot_api.treasury.config import ChainConfig, PlatformConfiguration

API_ROOT = Path(__file__).parents[1]
NOW = datetime(2026, 10, 15, tzinfo=UTC)
ORG_ID = uuid.UUID("00000000-0000-7000-8000-000000000010")
MAINNET, TESTNET = 1, 11155111


class MemoryRepository:
    def __init__(self) -> None:
        self.rows: list[KybRecord] = []

    async def latest(self, *, organization_id: uuid.UUID, provider: str) -> KybRecord | None:
        matches = [
            r for r in self.rows if (r.organization_id, r.provider) == (organization_id, provider)
        ]
        return matches[-1] if matches else None

    async def record(self, **fields: object) -> KybRecord:
        row = KybRecord(id=uuid.uuid4(), **fields)  # type: ignore[arg-type]
        self.rows.append(row)
        return row


def service(provider: object, repository: MemoryRepository | None = None) -> KybService:
    return KybService(repository or MemoryRepository(), provider, clock=lambda: NOW)  # type: ignore[arg-type]


def verify(kyb: KybService, name: str = "Acme Ltd") -> KybRecord:
    return asyncio.run(kyb.verify(organization_id=ORG_ID, legal_name=name, country="US"))


def test_no_verification_means_not_approved() -> None:
    with pytest.raises(KybRequired) as error:
        asyncio.run(service(FixtureKybProvider({})).require_approved(ORG_ID))
    assert error.value.status is None


def test_fixture_approves_and_unlocks_the_gate() -> None:
    kyb = service(FixtureKybProvider({}))
    record = verify(kyb)
    assert record.status == KybStatus.APPROVED
    assert asyncio.run(kyb.require_approved(ORG_ID)).id == record.id


@pytest.mark.parametrize("status", [KybStatus.REJECTED, KybStatus.PENDING])
def test_rejected_or_pending_verification_blocks(status: KybStatus) -> None:
    kyb = service(FixtureKybProvider({"acme ltd": status}))
    assert verify(kyb).status == status
    with pytest.raises(KybRequired) as error:
        asyncio.run(kyb.require_approved(ORG_ID))
    assert error.value.status == status


def test_latest_verification_wins_so_a_later_rejection_revokes_approval() -> None:
    repository = MemoryRepository()
    verify(service(FixtureKybProvider({}), repository))
    verify(service(FixtureKybProvider({"acme ltd": KybStatus.REJECTED}), repository))
    with pytest.raises(KybRequired):
        asyncio.run(service(FixtureKybProvider({}), repository).require_approved(ORG_ID))


def test_approval_from_another_provider_is_not_trusted() -> None:
    repository = MemoryRepository()
    verify(service(FixtureKybProvider({}), repository))
    other = FixtureKybProvider({})
    other.name = "other-vendor"
    with pytest.raises(KybRequired):
        asyncio.run(service(other, repository).require_approved(ORG_ID))


def test_provider_failure_raises_and_records_nothing() -> None:
    repository = MemoryRepository()
    with pytest.raises(KybProviderError):
        verify(service(UnconfiguredKybProvider(), repository))
    assert repository.rows == []


def test_production_never_uses_the_fixture_provider() -> None:
    sessions = async_sessionmaker(create_async_engine("postgresql+asyncpg://offline/offline"))
    with pytest.raises(KybProviderError):
        verify(build_kyb_service("production", sessions))


def _chain(chain_id: int, *, testnet: bool) -> ChainConfig:
    return ChainConfig(
        chain_id=chain_id,
        name=f"chain-{chain_id}",
        is_testnet=testnet,
        confirmations=1,
        explorer_url="https://explorer.example",
        rpc_urls=("http://a", "http://b"),
    )


def _governance(kyb: KybService | None) -> GovernanceService:
    configuration = PlatformConfiguration(
        chains=(_chain(MAINNET, testnet=False), _chain(TESTNET, testnet=True)), manifests=()
    )
    return GovernanceService(None, None, configuration, kyb_service=kyb)  # type: ignore[arg-type]


def test_mainnet_activation_requires_kyb_approval_but_testnet_does_not() -> None:
    kyb = service(FixtureKybProvider({}))
    governance = _governance(kyb)

    asyncio.run(governance._require_kyb(ORG_ID, TESTNET))
    with pytest.raises(GovernanceFailure) as error:
        asyncio.run(governance._require_kyb(ORG_ID, MAINNET))
    assert (error.value.code, error.value.status) == ("KYB_REQUIRED", 409)

    verify(kyb)
    asyncio.run(governance._require_kyb(ORG_ID, MAINNET))


def test_mainnet_activation_fails_closed_without_a_kyb_service() -> None:
    with pytest.raises(GovernanceFailure, match="KYB"):
        asyncio.run(_governance(None)._require_kyb(ORG_ID, MAINNET))


@pytest.mark.skipif(
    "TP_TEST_DATABASE_URL" not in os.environ,
    reason="TP_TEST_DATABASE_URL is required for PostgreSQL integration tests",
)
def test_kyb_status_persists_and_gates_mainnet_on_postgres() -> None:
    database_url = os.environ["TP_TEST_DATABASE_URL"]
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    command.upgrade(config, "head")

    async def run() -> None:
        engine = create_async_engine(database_url)
        try:
            sessions = async_sessionmaker(engine)
            async with sessions.begin() as session:
                session.add(Organization(id=ORG_ID, name="KYB test"))
            kyb = build_kyb_service("test", sessions)
            governance = _governance(kyb)
            with pytest.raises(GovernanceFailure):
                await governance._require_kyb(ORG_ID, MAINNET)
            record = await kyb.verify(organization_id=ORG_ID, legal_name="Acme", country="US")
            assert record.status == KybStatus.APPROVED
            await governance._require_kyb(ORG_ID, MAINNET)
        finally:
            await engine.dispose()

    try:
        asyncio.run(run())
    finally:
        command.downgrade(config, "base")
