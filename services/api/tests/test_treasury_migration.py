from __future__ import annotations

import io
import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine

API_ROOT = Path(__file__).parents[1]
TREASURY_TABLES = {
    "chains",
    "assets",
    "deployments",
    "treasuries",
    "treasury_wallets",
    "safe_config_snapshots",
}


def alembic_config(*, database_url: str | None = None) -> Config:
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "migrations"))
    # Offline SQL generation only needs the dialect, never a reachable server.
    url = database_url or "postgresql+asyncpg://offline/offline"
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return config


def test_treasury_upgrade_and_downgrade_compile_offline() -> None:
    output = io.StringIO()
    config = alembic_config()
    config.output_buffer = output

    command.upgrade(config, "head", sql=True)
    command.downgrade(config, "head:base", sql=True)

    sql = output.getvalue()
    for enum_name in ("treasury_status", "treasury_coverage", "treasury_wallet_role"):
        assert f"CREATE TYPE {enum_name}" in sql
        assert f"DROP TYPE {enum_name}" in sql
    for table_name in TREASURY_TABLES:
        assert f"CREATE TABLE {table_name}" in sql
        assert f"DROP TABLE {table_name}" in sql
    assert "UNIQUE (chain_id, address)" in sql
    assert "UNIQUE (chain_id, name, version)" in sql
    assert "UNIQUE (chain_id, safe_address)" in sql
    assert "CREATE UNIQUE INDEX uq_assets_chain_native ON assets (chain_id) WHERE is_native" in sql
    assert "FOREIGN KEY(asset_id, chain_id)" in sql
    assert "FOREIGN KEY(treasury_id, org_id)" in sql
    assert "FOREIGN KEY(wallet_id, org_id)" in sql


async def _verify_postgres_schema(database_url: str) -> None:
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            table_names = await connection.run_sync(
                lambda sync_connection: set(inspect(sync_connection).get_table_names())
            )
            enum_rows = await connection.execute(
                text(
                    """
                    SELECT typname
                    FROM pg_type
                    WHERE typname IN (
                        'treasury_status', 'treasury_coverage', 'treasury_wallet_role'
                    )
                    """
                )
            )
            enum_names = set(enum_rows.scalars())
    finally:
        await engine.dispose()

    assert TREASURY_TABLES.issubset(table_names)
    assert enum_names == {"treasury_status", "treasury_coverage", "treasury_wallet_role"}


_SEED_SQL = """
INSERT INTO users (id, email) VALUES
    ('00000000-0000-7000-8000-000000000001', 'ack@example.com');
INSERT INTO organizations (id, name) VALUES
    ('00000000-0000-7000-8000-000000000010', 'Org A'),
    ('00000000-0000-7000-8000-000000000011', 'Org B');
INSERT INTO memberships (id, org_id, user_id, roles) VALUES
    ('00000000-0000-7000-8000-000000000020', '00000000-0000-7000-8000-000000000010',
     '00000000-0000-7000-8000-000000000001', ARRAY['Owner']);
INSERT INTO chains (chain_id, name, is_testnet, confirmations, explorer_url, rpc_urls)
VALUES (11155111, 'Sepolia', true, 3, 'https://sepolia.etherscan.io', '["https://rpc"]');
INSERT INTO assets (id, chain_id, address, symbol, decimals, issuer_label, is_native) VALUES
    ('00000000-0000-7000-8000-000000000030', 11155111, NULL, 'ETH', 18, 'Native', true),
    ('00000000-0000-7000-8000-000000000031', 11155111, decode(repeat('11', 20), 'hex'),
     'USDC', 6, 'Circle', false);
"""


async def _verify_postgres_behaviour(database_url: str) -> None:
    from sqlalchemy.exc import IntegrityError

    usdc = "00000000-0000-7000-8000-000000000031"
    org_a = "00000000-0000-7000-8000-000000000010"
    org_b = "00000000-0000-7000-8000-000000000011"
    safe = "decode(repeat('22', 20), 'hex')"

    def treasury(treasury_id: str, org_id: str, ack: bool) -> str:
        ack_values = (
            "'00000000-0000-7000-8000-000000000001', now(), 'reviewed'"
            if ack
            else "NULL, NULL, NULL"
        )
        return (
            "INSERT INTO treasuries (id, org_id, chain_id, asset_id, coverage_ack_by, "
            f"coverage_ack_at, coverage_ack_reason) VALUES ('{treasury_id}', '{org_id}', "
            f"11155111, '{usdc}', {ack_values})"
        )

    def wallet(wallet_id: str, treasury_id: str, org_id: str) -> str:
        return (
            "INSERT INTO treasury_wallets (id, org_id, treasury_id, chain_id, role, label, "
            f"safe_address, owners, threshold) VALUES ('{wallet_id}', '{org_id}', "
            f"'{treasury_id}', 11155111, 'SOURCE', 'Main', {safe}, '[\"0xowner\"]', 1)"
        )

    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as connection:
            for statement in _SEED_SQL.strip().split(";\n"):
                await connection.execute(text(statement))
            await connection.execute(
                text(treasury("00000000-0000-7000-8000-000000000040", org_a, ack=True))
            )
            await connection.execute(
                text(treasury("00000000-0000-7000-8000-000000000041", org_b, ack=False))
            )
            await connection.execute(
                text(
                    wallet(
                        "00000000-0000-7000-8000-000000000050",
                        "00000000-0000-7000-8000-000000000040",
                        org_a,
                    )
                )
            )

        # A second native asset on the same chain is rejected.
        with pytest.raises(IntegrityError, match="uq_assets_chain_native"):
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        "INSERT INTO assets (id, chain_id, symbol, decimals, issuer_label, "
                        "is_native) VALUES ('00000000-0000-7000-8000-000000000032', "
                        "11155111, 'ETH2', 18, 'Native', true)"
                    )
                )

        # The same Safe cannot be attributed to another tenant's treasury.
        with pytest.raises(IntegrityError, match="uq_treasury_wallets_chain_address"):
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        wallet(
                            "00000000-0000-7000-8000-000000000051",
                            "00000000-0000-7000-8000-000000000041",
                            org_b,
                        )
                    )
                )

        # Deleting an org whose treasury holds a coverage ack cascades cleanly.
        async with engine.begin() as connection:
            await connection.execute(text(f"DELETE FROM organizations WHERE id = '{org_a}'"))
            remaining = await connection.execute(
                text(f"SELECT count(*) FROM treasuries WHERE org_id = '{org_a}'")
            )
            assert remaining.scalar_one() == 0
    finally:
        await engine.dispose()


@pytest.mark.skipif(
    "TP_TEST_DATABASE_URL" not in os.environ,
    reason="TP_TEST_DATABASE_URL is required for the PostgreSQL migration cycle",
)
def test_treasury_migration_round_trip_on_postgres() -> None:
    import asyncio

    database_url = os.environ["TP_TEST_DATABASE_URL"]
    config = alembic_config(database_url=database_url)

    command.upgrade(config, "head")
    try:
        command.check(config)
        asyncio.run(_verify_postgres_schema(database_url))
        asyncio.run(_verify_postgres_behaviour(database_url))
    finally:
        command.downgrade(config, "base")
