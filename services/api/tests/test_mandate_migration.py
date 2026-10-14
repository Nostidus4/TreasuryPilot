from __future__ import annotations

import asyncio
import io
import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

API_ROOT = Path(__file__).parents[1]
MANDATE_TABLES = (
    "vendors",
    "governance_txs",
    "governance_signatures",
    "mandate_versions",
    "mandate_status_events",
    "payees",
    "screenings",
    "exceptions",
    "guardian_setups",
    "treasury_fee_policies",
    "fee_acceptances",
    "backend_pause",
)

ORG = "00000000-0000-7000-8000-000000000010"
USER = "00000000-0000-7000-8000-000000000001"
TREASURY = "00000000-0000-7000-8000-000000000040"
SAFE = "decode(repeat('22', 20), 'hex')"
HASH = "decode(repeat('ab', 32), 'hex')"


def alembic_config(*, database_url: str | None = None) -> Config:
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "migrations"))
    url = database_url or "postgresql+asyncpg://offline/offline"
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return config


def test_mandate_upgrade_and_downgrade_compile_offline() -> None:
    output = io.StringIO()
    config = alembic_config()
    config.output_buffer = output

    command.upgrade(config, "head", sql=True)
    command.downgrade(config, "head:base", sql=True)

    sql = output.getvalue()
    for table_name in MANDATE_TABLES:
        assert f"CREATE TABLE {table_name}" in sql
        assert f"DROP TABLE {table_name}" in sql
    for trigger in ("mandate_versions_immutable", "mandate_status_events_append_only"):
        assert f"CREATE TRIGGER {trigger}" in sql
    assert "RAISE EXCEPTION" in sql
    assert "mandate_version_id IS NOT NULL" in sql


_SEED_SQL = f"""
INSERT INTO users (id, email) VALUES ('{USER}', 'owner@example.com');
INSERT INTO organizations (id, name) VALUES ('{ORG}', 'Org A');
INSERT INTO chains (chain_id, name, is_testnet, confirmations, explorer_url, rpc_urls)
VALUES (11155111, 'Sepolia', true, 3, 'https://sepolia.etherscan.io', '["https://rpc"]');
INSERT INTO assets (id, chain_id, address, symbol, decimals, issuer_label) VALUES
    ('00000000-0000-7000-8000-000000000031', 11155111, decode(repeat('11', 20), 'hex'),
     'tUSDC', 6, 'Test');
INSERT INTO treasuries (id, org_id, chain_id, asset_id) VALUES
    ('{TREASURY}', '{ORG}', 11155111, '00000000-0000-7000-8000-000000000031')
"""


def _governance_tx(tx_id: str, *, nonce: int, status: str = "Collecting") -> str:
    return (
        "INSERT INTO governance_txs (id, org_id, treasury_id, chain_id, safe_address, purpose, "
        'calls, "to", value, data, operation, safe_nonce, safe_tx_hash, threshold, '
        f"owners_snapshot, status) VALUES ('{tx_id}', '{ORG}', '{TREASURY}', 11155111, {SAFE}, "
        f"'MANDATE', '[]', {SAFE}, 0, '\\x', 0, {nonce}, {HASH}, 1, ARRAY[{SAFE}], '{status}')"
    )


async def _expect_rejected(engine: AsyncEngine, statement: str, error: type[Exception]) -> None:
    with pytest.raises(error):
        async with engine.begin() as connection:
            await connection.execute(text(statement))


async def _verify_behaviour(database_url: str) -> None:
    mandate = "00000000-0000-7000-8000-000000000060"
    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as connection:
            for statement in _SEED_SQL.strip().split(";\n"):
                await connection.execute(text(statement))
            await connection.execute(
                text(_governance_tx("00000000-0000-7000-8000-000000000070", nonce=7))
            )
            await connection.execute(
                text(
                    "INSERT INTO mandate_versions (id, org_id, treasury_id, version, status, "
                    "config, config_hash, valid_from, expires_at, created_by) VALUES "
                    f"('{mandate}', '{ORG}', '{TREASURY}', 1, 'Draft', '{{\"pay\": 1}}', "
                    f"{HASH}, now(), now() + interval '30 days', '{USER}')"
                )
            )
            await connection.execute(
                text(
                    "INSERT INTO mandate_status_events (id, org_id, mandate_version_id, "
                    "from_status, to_status) VALUES ('00000000-0000-7000-8000-000000000061', "
                    f"'{ORG}', '{mandate}', 'Draft', 'PendingActivation')"
                )
            )

        # The lifecycle columns may move on; the configuration snapshot may not.
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "UPDATE mandate_versions SET status = 'Active', onchain_version = 1, "
                    f"activated_at = now() WHERE id = '{mandate}'"
                )
            )
        await _expect_rejected(
            engine,
            f"UPDATE mandate_versions SET config = '{{\"pay\": 2}}' WHERE id = '{mandate}'",
            DBAPIError,
        )
        await _expect_rejected(
            engine,
            f"UPDATE mandate_versions SET status = 'Draft' WHERE id = '{mandate}'",
            DBAPIError,
        )
        await _expect_rejected(
            engine, f"DELETE FROM mandate_versions WHERE id = '{mandate}'", DBAPIError
        )
        # Only a Draft may be discarded, together with its creation event.
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO mandate_versions (id, org_id, treasury_id, version, config, "
                    "config_hash, valid_from, expires_at, created_by) VALUES "
                    f"('00000000-0000-7000-8000-000000000062', '{ORG}', '{TREASURY}', 2, '{{}}', "
                    f"{HASH}, now(), now() + interval '30 days', '{USER}')"
                )
            )
            await connection.execute(
                text(
                    "INSERT INTO mandate_status_events (id, org_id, mandate_version_id, "
                    "to_status) VALUES ('00000000-0000-7000-8000-000000000063', "
                    f"'{ORG}', '00000000-0000-7000-8000-000000000062', 'Draft')"
                )
            )
            await connection.execute(text("DELETE FROM mandate_versions WHERE version = 2"))
        # At most one Active version per treasury.
        await _expect_rejected(
            engine,
            "INSERT INTO mandate_versions (id, org_id, treasury_id, version, status, "
            "onchain_version, activated_at, config, config_hash, valid_from, expires_at, "
            f"created_by) VALUES ('00000000-0000-7000-8000-000000000064', '{ORG}', "
            f"'{TREASURY}', 3, 'Active', 2, now(), '{{}}', {HASH}, now(), "
            f"now() + interval '30 days', '{USER}')",
            IntegrityError,
        )
        await _expect_rejected(engine, "TRUNCATE mandate_versions CASCADE", DBAPIError)
        await _expect_rejected(
            engine, "UPDATE mandate_status_events SET to_status = 'Active'", DBAPIError
        )
        await _expect_rejected(engine, "DELETE FROM mandate_status_events", DBAPIError)

        # One open governance tx per Safe nonce; a closed one frees the nonce.
        await _expect_rejected(
            engine,
            _governance_tx("00000000-0000-7000-8000-000000000071", nonce=7, status="Ready"),
            IntegrityError,
        )
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    _governance_tx(
                        "00000000-0000-7000-8000-000000000072", nonce=7, status="Superseded"
                    )
                )
            )
            await connection.execute(
                text(_governance_tx("00000000-0000-7000-8000-000000000073", nonce=8))
            )
    finally:
        await engine.dispose()


@pytest.mark.skipif(
    "TP_TEST_DATABASE_URL" not in os.environ,
    reason="TP_TEST_DATABASE_URL is required for the PostgreSQL migration cycle",
)
def test_mandate_migration_round_trip_on_postgres() -> None:
    database_url = os.environ["TP_TEST_DATABASE_URL"]
    config = alembic_config(database_url=database_url)

    command.upgrade(config, "head")
    try:
        asyncio.run(_verify_behaviour(database_url))
    finally:
        command.downgrade(config, "base")
