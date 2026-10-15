from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from treasurypilot_api.compliance.travel_rule import (
    SqlAlchemyTravelRuleRepository,
    TravelRuleRecord,
    TravelRuleStatus,
)

pytestmark = pytest.mark.skipif(
    "TP_TEST_DATABASE_URL" not in os.environ,
    reason="TP_TEST_DATABASE_URL is required for PostgreSQL integration tests",
)

API_ROOT = Path(__file__).parents[1]


async def _exercise(database_url: str) -> None:
    engine = create_async_engine(database_url)
    try:
        org_id = uuid.uuid4()
        async with engine.begin() as connection:
            await connection.execute(
                text("INSERT INTO organizations (id, name) VALUES (:id, 'Travel Rule test')"),
                {"id": org_id},
            )
            # Payment-request fixtures are irrelevant to repository semantics under test.
            await connection.execute(
                text(
                    "ALTER TABLE travel_rule_exchanges "
                    "DROP CONSTRAINT travel_rule_exchanges_request_id_fkey"
                )
            )
        repository = SqlAlchemyTravelRuleRepository(
            async_sessionmaker(engine, expire_on_commit=False)
        )

        def record(status: TravelRuleStatus, threshold: int | None) -> TravelRuleRecord:
            return TravelRuleRecord(
                id=uuid.uuid4(),
                organization_id=org_id,
                payment_request_id=uuid.uuid4(),
                provider="test-provider",
                status=status,
                amount_minor_units=101,
                currency="USD",
                origin_jurisdiction="US",
                beneficiary_jurisdiction="GB",
                beneficiary_address=bytes(20),
                chain_id=1,
                payload_encrypted="ciphertext",
                provider_ref=None,
                threshold_minor_units=threshold,
            )

        skipped = await repository.create(record(TravelRuleStatus.NOT_REQUIRED, 100))
        assert skipped.threshold_minor_units == 100

        pending = await repository.create(record(TravelRuleStatus.PENDING, 100))
        with_ref = await repository.update(
            record_id=pending.id, status=TravelRuleStatus.PENDING, provider_ref="ref-1"
        )
        assert with_ref.provider_ref == "ref-1"
        # A reply without a reference must not erase the one already stored.
        kept = await repository.update(
            record_id=pending.id, status=TravelRuleStatus.PENDING, provider_ref=None
        )
        assert kept.provider_ref == "ref-1"

        done = await repository.update(
            record_id=pending.id, status=TravelRuleStatus.SELF_HOSTED, provider_ref=None
        )
        assert done.status == TravelRuleStatus.SELF_HOSTED
        # Stale replies cannot reopen a terminal decision.
        stale = await repository.update(
            record_id=pending.id, status=TravelRuleStatus.ERROR, provider_ref="ref-2"
        )
        assert stale.status == TravelRuleStatus.SELF_HOSTED
        assert stale.provider_ref == "ref-1"
    finally:
        await engine.dispose()


def test_repository_preserves_references_and_terminal_decisions() -> None:
    database_url = os.environ["TP_TEST_DATABASE_URL"]
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    command.upgrade(config, "head")
    try:
        asyncio.run(_exercise(database_url))
    finally:
        command.downgrade(config, "base")
