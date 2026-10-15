from __future__ import annotations

import asyncio
import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import asyncpg  # type: ignore[import-untyped]
import pytest
from alembic import command
from alembic.config import Config

from treasurypilot_worker.mandate_expiry import expire_mandates

API_ROOT = Path(__file__).parents[2] / "api"


def test_mandate_expiry_sweep_is_scheduled_every_ten_minutes() -> None:
    from treasurypilot_worker.celery_app import app

    entry = app.conf.beat_schedule["expire-mandates"]
    assert entry["task"] == "treasurypilot.mandates.expire"
    assert entry["schedule"].total_seconds() == 600


async def _sweep(database_url: str) -> None:
    connection = await asyncpg.connect(
        database_url.replace("postgresql+asyncpg://", "postgresql://")
    )
    org_id, user_id, asset_id, treasury_id = (uuid.uuid4() for _ in range(4))
    chain_id = await connection.fetchval("SELECT COALESCE(MAX(chain_id), 100000) + 1 FROM chains")
    try:
        await connection.execute(
            "INSERT INTO organizations (id, name) VALUES ($1, 'Mandate expiry')", org_id
        )
        await connection.execute(
            "INSERT INTO chains (chain_id, name, is_testnet, confirmations, explorer_url, "
            "rpc_urls) VALUES ($1, 'Expiry test', true, 1, 'https://e.test', '[\"https://r\"]')",
            chain_id,
        )
        await connection.execute(
            "INSERT INTO assets (id, chain_id, address, symbol, decimals, issuer_label) "
            "VALUES ($1, $2, decode(repeat('11', 20), 'hex'), 'EXP', 6, 'Test')",
            asset_id,
            chain_id,
        )
        await connection.execute(
            "INSERT INTO treasuries (id, org_id, chain_id, asset_id) VALUES ($1, $2, $3, $4)",
            treasury_id,
            org_id,
            chain_id,
            asset_id,
        )
        await connection.execute(
            "INSERT INTO users (id, email) VALUES ($1, $2)", user_id, f"{user_id}@example.test"
        )

        now = datetime.now(UTC)
        mandate_ids = {
            name: uuid.uuid4()
            for name in ("seven_day", "two_day", "one_hour", "catch_up", "expired")
        }
        expiries = {
            "seven_day": now + timedelta(days=6),
            "two_day": now + timedelta(hours=47),
            "one_hour": now + timedelta(minutes=30),
            "catch_up": now + timedelta(minutes=30),
            "expired": now - timedelta(hours=1),
        }
        for index, name in enumerate(mandate_ids, start=1):
            await connection.execute(
                "INSERT INTO mandate_versions (id, org_id, treasury_id, version, onchain_version, "
                "status, config, config_hash, valid_from, expires_at, created_by, activated_at) "
                "VALUES ($1, $2, $3, $4, 1, 'Active', '{}'::jsonb, decode(repeat('22', 32), 'hex'), "
                "$5, $6, $7, $5)",
                mandate_ids[name],
                org_id,
                treasury_id,
                index,
                now - timedelta(days=1),
                expiries[name],
                user_id,
            )
        await connection.close()

        assert await _run_sweep(database_url) == {
            "warnings_emitted": 6,
            "mandates_expired": 1,
        }
        assert await _run_sweep(database_url) == {"warnings_emitted": 0, "mandates_expired": 0}

        connection = await asyncpg.connect(
            database_url.replace("postgresql+asyncpg://", "postgresql://")
        )
        try:
            warnings = await connection.fetch(
                "SELECT mandate_version_id, warning_hours FROM mandate_expiry_notifications "
                "WHERE org_id = $1",
                org_id,
            )
            assert {(row["mandate_version_id"], row["warning_hours"]) for row in warnings} == {
                (mandate_ids["seven_day"], 168),
                (mandate_ids["two_day"], 48),
                (mandate_ids["one_hour"], 1),
                (mandate_ids["catch_up"], 168),
                (mandate_ids["catch_up"], 48),
                (mandate_ids["catch_up"], 1),
            }
            assert (
                await connection.fetchval(
                    "SELECT status::text FROM mandate_versions WHERE id = $1",
                    mandate_ids["expired"],
                )
                == "Expired"
            )
            status_event = await connection.fetchrow(
                'SELECT "from"::text, "to"::text, by_user_id FROM mandate_status_events '
                "WHERE mandate_version_id = $1",
                mandate_ids["expired"],
            )
            assert tuple(status_event) == ("Active", "Expired", None)
            assert (
                await connection.fetchval(
                    "SELECT count(*) FROM domain_events WHERE org_id = $1 "
                    "AND type IN ('MandateExpiring', 'MandateExpired')",
                    org_id,
                )
                == 7
            )
            assert (
                await connection.fetchval(
                    "SELECT count(*) FROM mandate_versions WHERE treasury_id = $1 "
                    "AND status = 'Active'",
                    treasury_id,
                )
                == 4
            )
        finally:
            await connection.close()
    finally:
        if not connection.is_closed():
            await connection.close()


async def _run_sweep(database_url: str) -> dict[str, int]:
    connection = await asyncpg.connect(
        database_url.replace("postgresql+asyncpg://", "postgresql://")
    )
    try:
        return await expire_mandates(connection)
    finally:
        await connection.close()


@pytest.mark.skipif(
    "TP_TEST_DATABASE_URL" not in os.environ,
    reason="TP_TEST_DATABASE_URL is required for the PostgreSQL mandate expiry test",
)
def test_mandate_expiry_sweep_runs_against_real_postgres() -> None:
    database_url = os.environ["TP_TEST_DATABASE_URL"]
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    command.upgrade(config, "head")
    try:
        asyncio.run(_sweep(database_url))
    finally:
        command.downgrade(config, "base")
