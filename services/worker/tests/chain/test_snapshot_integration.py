"""CHR-002 on a real Anvil node (Multicall3 is predeployed) and Postgres."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import socket
import subprocess
import time
import urllib.request
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import asyncpg  # type: ignore[import-untyped]
import pytest
from alembic import command
from alembic.config import Config

from treasurypilot_worker.chain.rpc import build_rpc_client
from treasurypilot_worker.chain.snapshot import (
    MULTICALL3,
    SnapshotPurpose,
    is_fresh,
    snapshot_dashboards,
    take_snapshot,
)
from treasurypilot_worker.locks import _asyncpg_database_url, create_worker_pool

API_ROOT = Path(__file__).parents[3] / "api"
CHAIN_ID = 31337
ORG, TREASURY, ASSET_ID = (
    uuid.UUID(f"00000000-0000-7000-8000-0000000000{n}") for n in (10, 40, 30)
)
ASSET = "0x" + "a1" * 20
MODULE = "0x" + "a2" * 20
WALLETS = [("SOURCE", "0x" + "b1" * 20), ("OPERATIONAL", "0x" + "b2" * 20)]
# Runtime code that answers every call with block.number: its value proves which block it ran at.
RETURN_BLOCK_NUMBER = "0x435f5260205ff3"
# Canonical Multicall3 runtime code (as deployed on Sepolia); a bare Anvil does not ship it.
MULTICALL3_CODE = (Path(__file__).parent / "multicall3.runtime.hex").read_text().strip()


def _rpc(url: str, method: str, params: list[object]) -> Any:
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    request = urllib.request.Request(url, body, {"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=5) as response:
        payload = json.load(response)
    assert "error" not in payload, payload
    return payload["result"]


@pytest.fixture(scope="module")
def anvil_url() -> Iterator[str]:
    if "TP_TEST_ANVIL_URL" in os.environ:
        yield os.environ["TP_TEST_ANVIL_URL"]
        return
    if shutil.which("anvil") is None:
        pytest.skip("anvil is required for the snapshot integration test")
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = int(probe.getsockname()[1])
    process = subprocess.Popen(
        ["anvil", "--silent", "--port", str(port), "--chain-id", str(CHAIN_ID)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    url = f"http://127.0.0.1:{port}"
    try:
        for _ in range(50):
            try:
                _rpc(url, "eth_chainId", [])
                break
            except OSError:
                time.sleep(0.1)
        else:
            pytest.fail("anvil did not start")
        yield url
    finally:
        process.terminate()
        process.wait(timeout=5)


async def _seed(database_url: str, rpc_url: str) -> None:
    connection = await asyncpg.connect(_asyncpg_database_url(database_url))
    try:
        await connection.execute(
            "INSERT INTO organizations (id, name) VALUES ($1, 'Snapshots')", ORG
        )
        await connection.execute(
            "INSERT INTO chains (chain_id, name, is_testnet, confirmations, explorer_url, rpc_urls)"
            " VALUES ($1, 'Anvil', true, 3, 'http://explorer', $2::jsonb)",
            CHAIN_ID,
            json.dumps([rpc_url]),
        )
        await connection.execute(
            "INSERT INTO assets (id, chain_id, address, symbol, decimals, issuer_label)"
            " VALUES ($1, $2, $3, 'USDC', 6, 'Circle')",
            ASSET_ID,
            CHAIN_ID,
            bytes.fromhex(ASSET[2:]),
        )
        await connection.execute(
            "INSERT INTO treasuries (id, org_id, chain_id, asset_id, module_address)"
            " VALUES ($1, $2, $3, $4, $5)",
            TREASURY,
            ORG,
            CHAIN_ID,
            ASSET_ID,
            bytes.fromhex(MODULE[2:]),
        )
        for role, address in WALLETS:
            await connection.execute(
                "INSERT INTO treasury_wallets"
                " (id, org_id, treasury_id, chain_id, role, label, safe_address, owners, threshold)"
                " VALUES ($1, $2, $3, $4, $5::treasury_wallet_role, $5, $6, '[\"0x01\"]'::jsonb, 1)",
                uuid.uuid4(),
                ORG,
                TREASURY,
                CHAIN_ID,
                role,
                bytes.fromhex(address[2:]),
            )
    finally:
        await connection.close()


@pytest.fixture(scope="module")
def database_url(anvil_url: str) -> Iterator[str]:
    if "TP_TEST_DATABASE_URL" not in os.environ:
        pytest.skip("TP_TEST_DATABASE_URL is required for snapshot integration tests")
    url = os.environ["TP_TEST_DATABASE_URL"]
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    command.upgrade(config, "head")
    try:
        asyncio.run(_seed(url, anvil_url))
        yield url
    finally:
        command.downgrade(config, "base")


def test_snapshot_values_all_come_from_the_pinned_block_and_are_stored(
    anvil_url: str, database_url: str
) -> None:
    _rpc(anvil_url, "anvil_setCode", [MULTICALL3, MULTICALL3_CODE])
    for address in (ASSET, MODULE, *(wallet for _, wallet in WALLETS)):
        _rpc(anvil_url, "anvil_setCode", [address, RETURN_BLOCK_NUMBER])
    # Past the precompile range: the stub also "answers" aavePool() with the block number.
    _rpc(anvil_url, "anvil_mine", ["0x400"])
    head = int(_rpc(anvil_url, "eth_blockNumber", []), 16)
    assert head >= 1024

    async def scenario() -> None:
        pool = await create_worker_pool(database_url, min_size=1, max_size=2)
        try:
            snapshot = await take_snapshot(
                pool, TREASURY, SnapshotPurpose.PLAN, block=1000, reader_factory=build_rpc_client
            )
            block_values = {
                *snapshot.data["balances"].values(),
                *snapshot.data["buffers"].values(),
                *snapshot.data["targets"].values(),
                *snapshot.data["module"]["used_today"].values(),
            }
            # head is later than 1000, yet every value reports block 1000.
            assert snapshot.block_number == 1000
            assert block_values == {"1000"}
            # The stub cannot answer Safe views or the mandate; they are missing, not defaulted.
            assert "module.mandate" in snapshot.missing
            assert any(path.startswith("safes.") for path in snapshot.missing)
            assert snapshot.coverage == "UNKNOWN"
            assert snapshot.provider == "127.0.0.1"
            # A snapshot 3+ blocks behind head is rejected; one at head is accepted.
            assert not is_fresh(snapshot, datetime.now(UTC), head)
            latest = await take_snapshot(pool, TREASURY, SnapshotPurpose.PRE_STEP)
            assert latest.block_number >= head
            assert is_fresh(latest, latest.block_timestamp, latest.block_number)

            row = await pool.fetchrow("SELECT * FROM snapshots WHERE id = $1", snapshot.id)
            assert (row["purpose"], row["block_number"], row["org_id"]) == ("PLAN", 1000, ORG)
            assert "0x" + bytes(row["block_hash"]).hex() == snapshot.block_hash
            assert json.loads(row["missing"]) == list(snapshot.missing)
            with pytest.raises(asyncpg.RaiseError, match="immutable"):
                await pool.execute("UPDATE snapshots SET coverage = 'COMPLETE'")
        finally:
            await pool.close()

    asyncio.run(scenario())


def test_dashboard_snapshots_are_written_and_old_ones_pruned(
    anvil_url: str, database_url: str
) -> None:
    async def scenario() -> None:
        pool = await create_worker_pool(database_url, min_size=1, max_size=2)
        try:
            for purpose in ("DASHBOARD", "PLAN"):
                await pool.execute(
                    "INSERT INTO snapshots (id, org_id, treasury_id, purpose, block_number,"
                    " block_hash, block_timestamp, observed_at, provider, data, coverage, missing)"
                    " VALUES ($1, $2, $3, $4, 1, $5, now(), $6, 'old', '{}', 'UNKNOWN', '[]')",
                    uuid.uuid4(),
                    ORG,
                    TREASURY,
                    purpose,
                    b"\x00" * 32,
                    datetime.now(UTC) - timedelta(days=8),
                )
            before = await pool.fetchval("SELECT count(*) FROM snapshots WHERE purpose='DASHBOARD'")

            assert await snapshot_dashboards(database_url) == 1

            dashboards = await pool.fetch(
                "SELECT provider FROM snapshots WHERE purpose='DASHBOARD'"
            )
            assert [row["provider"] for row in dashboards].count("old") == 0
            assert len(dashboards) == before  # one old removed, one new added
            assert await pool.fetchval("SELECT count(*) FROM snapshots WHERE provider='old'") == 1

            # DAILY rows are retained: a daily run stores one and prunes nothing.
            assert await snapshot_dashboards(database_url, purpose=SnapshotPurpose.DAILY) == 1
            assert await pool.fetchval("SELECT count(*) FROM snapshots WHERE purpose='DAILY'") == 1
            assert await pool.fetchval("SELECT count(*) FROM snapshots WHERE provider='old'") == 1
        finally:
            await pool.close()

    asyncio.run(scenario())
