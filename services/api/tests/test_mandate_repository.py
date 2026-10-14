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

from treasurypilot_api.mandate.routes import MandateContext, SqlAlchemyMandateRepository

API_ROOT = Path(__file__).parents[1]
ORG = "00000000-0000-7000-8000-000000000010"
USER = "00000000-0000-7000-8000-000000000001"
TREASURY = "00000000-0000-7000-8000-000000000040"
OTHER_TREASURY = "00000000-0000-7000-8000-000000000041"
_SEED_SQL = f"""
INSERT INTO users (id, email) VALUES ('{USER}', 'owner@example.com');
INSERT INTO organizations (id, name) VALUES ('{ORG}', 'Org A');
INSERT INTO chains (chain_id, name, is_testnet, confirmations, explorer_url, rpc_urls)
VALUES (11155111, 'Sepolia', true, 3, 'https://sepolia.etherscan.io', '["https://rpc"]');
INSERT INTO assets (id, chain_id, address, symbol, decimals, issuer_label) VALUES
    ('00000000-0000-7000-8000-000000000031', 11155111, decode(repeat('11', 20), 'hex'),
     'tUSDC', 6, 'Test');
INSERT INTO treasuries (id, org_id, chain_id, asset_id) VALUES
    ('{TREASURY}', '{ORG}', 11155111, '00000000-0000-7000-8000-000000000031'),
    ('{OTHER_TREASURY}', '{ORG}', 11155111, '00000000-0000-7000-8000-000000000031')
"""


async def _verify_create_draft(database_url: str) -> None:
    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as connection:
            for statement in _SEED_SQL.strip().split(";\n"):
                await connection.execute(text(statement))
        repository = SqlAlchemyMandateRepository(async_sessionmaker(engine, expire_on_commit=False))
        seen: list[MandateContext] = []

        def build_config(context: MandateContext) -> dict[str, object]:
            seen.append(context)
            return {
                "validFrom": "2030-01-01T00:00:00+00:00",
                "expiresAt": "2030-02-01T00:00:00+00:00",
            }

        for expected_version in (1, 2):
            created = await repository.create_draft(
                organization_id=uuid.UUID(ORG),
                treasury_id=uuid.UUID(TREASURY),
                user_id=uuid.UUID(USER),
                build_config=build_config,
            )
            assert created is not None
            assert created[0].version == expected_version
        other_created = await repository.create_draft(
            organization_id=uuid.UUID(ORG),
            treasury_id=uuid.UUID(OTHER_TREASURY),
            user_id=uuid.UUID(USER),
            build_config=lambda context: {
                "validFrom": "2030-01-01T00:00:00+00:00",
                "expiresAt": "2030-03-01T00:00:00+00:00",
                "scope": "other-treasury",
            },
        )
        assert other_created is not None and other_created[0].version == 1
        primary_versions = await repository.list_versions(
            organization_id=uuid.UUID(ORG), treasury_id=uuid.UUID(TREASURY)
        )
        other_versions = await repository.list_versions(
            organization_id=uuid.UUID(ORG), treasury_id=uuid.UUID(OTHER_TREASURY)
        )
        assert primary_versions is not None and [v.version for v in primary_versions] == [2, 1]
        assert {v.treasury_id for v in primary_versions} == {uuid.UUID(TREASURY)}
        assert other_versions is not None and [v.version for v in other_versions] == [1]
        assert other_versions[0].treasury_id == uuid.UUID(OTHER_TREASURY)
        assert other_versions[0].config["scope"] == "other-treasury"
        assert (
            await repository.get_version(
                organization_id=uuid.UUID(ORG),
                treasury_id=uuid.UUID(TREASURY),
                mandate_id=other_created[0].id,
            )
            is None
        )
        assert [context.asset_symbol for context in seen] == ["tUSDC", "tUSDC"]
        assert (
            await repository.create_draft(
                organization_id=uuid.uuid4(),
                treasury_id=uuid.UUID(TREASURY),
                user_id=uuid.UUID(USER),
                build_config=build_config,
            )
            is None
        )
        async with engine.connect() as connection:
            org_ids = (
                await connection.execute(text("SELECT org_id::text FROM mandate_versions"))
            ).scalars()
            assert set(org_ids) == {ORG}
    finally:
        await engine.dispose()


@pytest.mark.skipif(
    "TP_TEST_DATABASE_URL" not in os.environ,
    reason="TP_TEST_DATABASE_URL is required for the PostgreSQL repository test",
)
def test_create_draft_sets_org_id_on_postgres() -> None:
    database_url = os.environ["TP_TEST_DATABASE_URL"]
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))

    command.upgrade(config, "head")
    try:
        asyncio.run(_verify_create_draft(database_url))
    finally:
        command.downgrade(config, "base")
