from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

sys.path.insert(0, str(Path(__file__).parents[1]))
import seed_local  # noqa: E402

from treasurypilot_api.mandate.configuration import MandateConfig  # noqa: E402
from treasurypilot_api.treasury import sync as seed_sync  # noqa: E402

pytestmark = pytest.mark.skipif(
    "TP_TEST_DATABASE_URL" not in os.environ,
    reason="TP_TEST_DATABASE_URL is required for PostgreSQL integration tests",
)
API_ROOT = Path(__file__).parents[3] / "services" / "api"
TABLES = (
    "organizations", "memberships", "treasuries", "treasury_wallets", "mandate_versions",
    "vendors", "payees", "payment_requests", "guardian_setups", "treasury_fee_policies",
    "safe_config_snapshots",
)  # fmt: skip
ADDRESS_FIELDS = (
    "safeT", "safeO1", "safeO2", "module", "testToken", "demoOwner", "implementation",
    "safeSingleton", "safeProxyFactory", "multiSend", "factory",
)  # fmt: skip


async def _no_rpc(*_args: object) -> None:
    return None


def _manifest(offset: int) -> dict[str, Any]:
    return {
        **{k: "0x" + f"{i + 1 + offset:040x}" for i, k in enumerate(ADDRESS_FIELDS)},
        "mandateExpiresAt": 2_000_000_000 + offset,
    }


async def _run_twice(url: str, tmp: Path, monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    """Run main_async (sync commit + seed) twice, the second time after a 'redeploy'."""
    monkeypatch.setattr(seed_local, "rpc", lambda *_a: "0x6001")  # any non-empty code
    monkeypatch.setattr(seed_sync, "verify_asset_decimals", _no_rpc)
    monkeypatch.setenv("DATABASE_URL", url)
    results = []
    engine = create_async_engine(url)
    try:
        for offset in (0, 0, 100):
            manifest = tmp / "manifest.json"
            manifest.write_text(json.dumps(_manifest(offset)))
            await seed_local.main_async(
                argparse.Namespace(
                    manifest=str(manifest), config_dir=str(tmp / "local"),
                    rpc_url="http://rpc", api_rpc_url="http://anvil:8545", web_url="http://w", env_file=None,
                )
            )  # fmt: skip
            async with engine.connect() as c:
                counts = {
                    t: int(await c.scalar(text(f"SELECT count(*) FROM {t}")) or 0) for t in TABLES
                }
                module = await c.scalar(text("SELECT module_address FROM treasuries"))
                safes = set(await c.scalars(text("SELECT safe_address FROM treasury_wallets")))
                mandate = await c.scalar(text("SELECT config FROM mandate_versions"))
            # The API (forecast, mandate pages) parses the stored config strictly.
            assert MandateConfig.model_validate(mandate).limits is not None
            results.append((counts, module, safes))
    finally:
        await engine.dispose()
    return results


def test_seed_is_idempotent_and_follows_redeploys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    url = os.environ["TP_TEST_DATABASE_URL"]
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    command.upgrade(config, "head")
    try:
        (first, _, _), (second, _, _), (redeployed, module, safes) = asyncio.run(
            _run_twice(url, tmp_path, monkeypatch)
        )
    finally:
        command.downgrade(config, "base")
    assert first == second == redeployed
    assert first["treasury_wallets"] == first["safe_config_snapshots"] == 3
    assert first["payees"] == 3
    assert first["payment_requests"] == 5
    assert first["mandate_versions"] == first["treasuries"] == first["organizations"] == 1
    chains = json.loads((tmp_path / "local" / "chains.json").read_text())["chains"][0]
    assert chains["rpcUrls"][0] == "http://anvil:8545"
    assert module == seed_local.b(_manifest(100)["module"])
    assert safes == {seed_local.b(_manifest(100)[k]) for k in ("safeT", "safeO1", "safeO2")}
