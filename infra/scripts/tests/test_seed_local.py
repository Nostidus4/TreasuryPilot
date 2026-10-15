from __future__ import annotations

import asyncio
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

sys.path.insert(0, str(Path(__file__).parents[1]))
import seed_local  # noqa: E402

pytestmark = pytest.mark.skipif(
    "TP_TEST_DATABASE_URL" not in os.environ,
    reason="TP_TEST_DATABASE_URL is required for PostgreSQL integration tests",
)
API_ROOT = Path(__file__).parents[3] / "services" / "api"
MANIFEST: dict[str, Any] = {
    **{
        k: "0x" + f"{i + 1:040x}"
        for i, k in enumerate(["safeT", "safeO1", "safeO2", "module", "testToken", "demoOwner"])
    },
    "mandateExpiresAt": 2_000_000_000,
}
TABLES = (
    "organizations", "memberships", "treasuries", "treasury_wallets", "mandate_versions",
    "vendors", "payees", "payment_requests", "guardian_setups", "treasury_fee_policies",
)  # fmt: skip


async def _seed_twice(url: str) -> list[dict[str, int]]:
    engine = create_async_engine(url)
    counts = []
    try:
        async with engine.begin() as c:
            await c.execute(
                text(
                    "INSERT INTO chains (chain_id, name, is_testnet, confirmations, explorer_url, "
                    "rpc_urls) VALUES (31337, 'Anvil', true, 0, 'http://e', '[\"http://r\"]')"
                )
            )
            await c.execute(
                text(
                    "INSERT INTO assets (id, chain_id, address, symbol, decimals, issuer_label, "
                    "is_test) VALUES (:id, 31337, :a, 'tUSDC', 6, 'TEST', true)"
                ),
                {
                    "id": seed_local.asset_id(31337, MANIFEST["testToken"]),
                    "a": seed_local.b(MANIFEST["testToken"]),
                },
            )
        for _ in range(2):
            async with engine.begin() as c:
                await seed_local.seed_database(c, MANIFEST, datetime.now(UTC))
            async with engine.connect() as c:
                counts.append(
                    {t: int(await c.scalar(text(f"SELECT count(*) FROM {t}")) or 0) for t in TABLES}
                )
    finally:
        await engine.dispose()
    return counts


def test_seed_is_idempotent_and_complete() -> None:
    url = os.environ["TP_TEST_DATABASE_URL"]
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    command.upgrade(config, "head")
    try:
        first, second = asyncio.run(_seed_twice(url))
    finally:
        command.downgrade(config, "base")
    assert first == second
    assert first["treasury_wallets"] == 3
    assert first["payees"] == 3
    assert first["payment_requests"] == 5
    assert first["mandate_versions"] == first["treasuries"] == first["organizations"] == 1
