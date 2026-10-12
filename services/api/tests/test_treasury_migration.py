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
    if database_url is not None:
        config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
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
    assert "UNIQUE (treasury_id, safe_address)" in sql
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


@pytest.mark.skipif(
    "TP_TEST_DATABASE_URL" not in os.environ,
    reason="TP_TEST_DATABASE_URL is required for the PostgreSQL migration cycle",
)
def test_treasury_migration_round_trip_on_postgres() -> None:
    import asyncio

    database_url = os.environ["TP_TEST_DATABASE_URL"]
    config = alembic_config(database_url=database_url)

    command.upgrade(config, "head")
    command.check(config)
    asyncio.run(_verify_postgres_schema(database_url))
    command.downgrade(config, "base")
