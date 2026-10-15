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

from treasurypilot_api.chain.routes import SqlAlchemyTokenMovementRepository

pytestmark = pytest.mark.skipif(
    "TP_TEST_DATABASE_URL" not in os.environ,
    reason="TP_TEST_DATABASE_URL is required for PostgreSQL integration tests",
)

API_ROOT = Path(__file__).parents[1]
CHAIN_ID = 31337
ORG, USER, ASSET, TREASURY, EVENT, MOVEMENT = (uuid.uuid4() for _ in range(6))


async def _run(database_url: str) -> None:
    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as connection:
            for statement in (
                f"INSERT INTO organizations (id, name) VALUES ('{ORG}', 'Movement test')",
                f"INSERT INTO users (id, email) VALUES ('{USER}', 'owner@example.com')",
                "INSERT INTO chains (chain_id, name, is_testnet, confirmations, explorer_url, "
                f"rpc_urls) VALUES ({CHAIN_ID}, 'Anvil', true, 3, 'https://e.invalid', "
                "'[\"http://rpc\"]')",
                "INSERT INTO assets (id, chain_id, address, symbol, decimals, issuer_label) "
                f"VALUES ('{ASSET}', {CHAIN_ID}, decode(repeat('11', 20), 'hex'), 'USDC', 6, 'C')",
                "INSERT INTO treasuries (id, org_id, chain_id, asset_id) "
                f"VALUES ('{TREASURY}', '{ORG}', {CHAIN_ID}, '{ASSET}')",
                "INSERT INTO observed_events (id, treasury_id, chain_id, stream, block_number, "
                "block_hash, tx_hash, log_index, address, event_name, payload) VALUES "
                f"('{EVENT}', '{TREASURY}', {CHAIN_ID}, 'TOKEN', 1, decode(repeat('22', 32), "
                "'hex'), decode(repeat('33', 32), 'hex'), 0, decode(repeat('11', 20), 'hex'), "
                "'Transfer', '{}'::jsonb)",
                "INSERT INTO token_movements (id, treasury_id, event_id, wallet, direction, "
                'counterparty, amount, "class") VALUES '
                f"('{MOVEMENT}', '{TREASURY}', '{EVENT}', decode(repeat('44', 20), 'hex'), "
                "'OUT', decode(repeat('55', 20), 'hex'), 5, 'UNEXPECTED_OUTFLOW')",
            ):
                await connection.execute(text(statement))
        repository = SqlAlchemyTokenMovementRepository(
            async_sessionmaker(engine, expire_on_commit=False)
        )

        assert (
            await repository.list_recent(
                organization_id=uuid.uuid4(), treasury_id=TREASURY, limit=5
            )
            is None
        )
        listed = await repository.list_recent(organization_id=ORG, treasury_id=TREASURY, limit=5)
        assert listed is not None and [row.id for row in listed] == [MOVEMENT]

        await repository.acknowledge(
            organization_id=ORG,
            treasury_id=TREASURY,
            movement_id=MOVEMENT,
            user_id=USER,
            reason="Owner withdrawal",
        )
        async with engine.connect() as connection:
            audit = (
                await connection.execute(
                    text("SELECT action, entity_id, actor_id, data FROM audit_log")
                )
            ).all()
        assert [(row.action, row.entity_id, row.actor_id) for row in audit] == [
            ("token_movement.acknowledged", str(MOVEMENT), str(USER))
        ]
        assert audit[0].data["reason"] == "Owner withdrawal"
    finally:
        await engine.dispose()


def test_list_scopes_to_organization_and_acknowledge_writes_an_audit_event() -> None:
    url = os.environ["TP_TEST_DATABASE_URL"]
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    command.upgrade(config, "head")
    try:
        asyncio.run(_run(url))
    finally:
        command.downgrade(config, "base")
