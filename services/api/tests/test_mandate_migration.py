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
from sqlalchemy.ext.asyncio import create_async_engine

API_ROOT = Path(__file__).parents[1]


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
    for table_name in (
        "vendors",
        "mandate_versions",
        "mandate_status_events",
        "governance_txs",
        "governance_signatures",
        "payees",
        "screenings",
        "exceptions",
        "guardian_setups",
        "treasury_fee_policies",
        "fee_acceptances",
        "backend_pause",
    ):
        assert f"CREATE TABLE {table_name}" in sql
        assert f"DROP TABLE {table_name}" in sql

    assert "uq_governance_txs_open_safe_nonce" in sql
    assert "WHERE status IN ('Collecting', 'Ready', 'Submitted')" in sql
    assert "CREATE TRIGGER trg_mandate_versions_immutable" in sql
    assert "CREATE TRIGGER trg_mandate_status_events_append_only" in sql
    assert "fk_payees_placeholder" not in sql


async def _verify_mandate_constraints(database_url: str) -> None:
    user_id = "00000000-0000-7000-8000-000000000001"
    org_id = "00000000-0000-7000-8000-000000000010"
    treasury_id = "00000000-0000-7000-8000-000000000040"
    mandate_id = "00000000-0000-7000-8000-000000000060"
    governance_tx_id = "00000000-0000-7000-8000-000000000070"

    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO users (id, email) VALUES "
                    f"('{user_id}', 'mandate-migration@example.com')"
                )
            )
            await connection.execute(
                text(f"INSERT INTO organizations (id, name) VALUES ('{org_id}', 'Mandate test')")
            )
            await connection.execute(
                text(
                    "INSERT INTO chains (chain_id, name, is_testnet, confirmations, "
                    "explorer_url, rpc_urls) VALUES "
                    "(11155111, 'Sepolia', true, 3, 'https://sepolia.etherscan.io', '[\"https://rpc\"]')"
                )
            )
            await connection.execute(
                text(
                    "INSERT INTO assets (id, chain_id, address, symbol, decimals, issuer_label) "
                    "VALUES ('00000000-0000-7000-8000-000000000030', 11155111, "
                    "decode(repeat('11', 20), 'hex'), 'USDC', 6, 'Circle')"
                )
            )
            await connection.execute(
                text(
                    "INSERT INTO treasuries (id, org_id, chain_id, asset_id) VALUES "
                    f"('{treasury_id}', '{org_id}', 11155111, '00000000-0000-7000-8000-000000000030')"
                )
            )
            await connection.execute(
                text(
                    "INSERT INTO mandate_versions "
                    "(id, treasury_id, version, status, config, config_hash) VALUES "
                    f"('{mandate_id}', '{treasury_id}', 1, 'Draft', '{{}}'::jsonb, "
                    "decode(repeat('aa', 32), 'hex'))"
                )
            )
            await connection.execute(
                text(
                    "INSERT INTO governance_txs "
                    "(id, treasury_id, safe_address, purpose, calls, to_address, value, data, "
                    "operation, safe_nonce, threshold, owners_snapshot, status, created_by) VALUES "
                    f"('{governance_tx_id}', '{treasury_id}', decode(repeat('22', 20), 'hex'), "
                    "'MANDATE', '[]'::jsonb, decode(repeat('33', 20), 'hex'), 0, "
                    "decode('', 'hex'), 0, 7, 1, ARRAY[decode(repeat('44', 20), 'hex')], "
                    f"'Collecting', '{user_id}')"
                )
            )

        with pytest.raises(DBAPIError, match="mandate_versions configuration is immutable"):
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        f"UPDATE mandate_versions SET config = '{{\"changed\": true}}'::jsonb "
                        f"WHERE id = '{mandate_id}'"
                    )
                )

        with pytest.raises(IntegrityError, match="uq_governance_txs_open_safe_nonce"):
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        "INSERT INTO governance_txs "
                        "(id, treasury_id, safe_address, purpose, calls, to_address, value, data, "
                        "operation, safe_nonce, threshold, owners_snapshot, status) VALUES "
                        "('00000000-0000-7000-8000-000000000071', "
                        f"'{treasury_id}', decode(repeat('22', 20), 'hex'), 'MANDATE', "
                        "'[]'::jsonb, decode(repeat('33', 20), 'hex'), 0, decode('', 'hex'), "
                        "0, 7, 1, ARRAY[decode(repeat('44', 20), 'hex')], 'Ready')"
                    )
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
        command.check(config)
        asyncio.run(_verify_mandate_constraints(database_url))
    finally:
        command.downgrade(config, "base")
