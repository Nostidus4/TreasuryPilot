from __future__ import annotations

import io
import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

API_ROOT = Path(__file__).parents[1]


def alembic_config(*, database_url: str | None = None) -> Config:
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "migrations"))
    if database_url is not None:
        config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


def test_identity_upgrade_and_downgrade_compile_offline() -> None:
    output = io.StringIO()
    config = alembic_config()
    config.output_buffer = output

    command.upgrade(config, "head", sql=True)
    command.downgrade(config, "head:base", sql=True)

    sql = output.getvalue()
    for table_name in (
        "users",
        "sessions",
        "magic_links",
        "wallet_links",
        "siwe_nonces",
        "organizations",
        "memberships",
        "invites",
    ):
        assert f"CREATE TABLE {table_name}" in sql
        assert f"DROP TABLE {table_name}" in sql
    assert "CREATE EXTENSION IF NOT EXISTS citext" in sql
    assert "CREATE UNIQUE INDEX uq_wallet_links_active_address" in sql
    assert "WHERE unlinked_at IS NULL" in sql


@pytest.mark.skipif(
    "TP_TEST_DATABASE_URL" not in os.environ,
    reason="TP_TEST_DATABASE_URL is required for the PostgreSQL migration cycle",
)
def test_identity_migration_round_trip_on_postgres() -> None:
    database_url = os.environ["TP_TEST_DATABASE_URL"]
    config = alembic_config(database_url=database_url)

    command.upgrade(config, "head")
    command.check(config)
    command.downgrade(config, "base")
