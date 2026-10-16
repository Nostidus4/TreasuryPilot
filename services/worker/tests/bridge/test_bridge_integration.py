"""Bridge transfers against PostgreSQL: one send per transfer under timeouts and races (EXE-L03)."""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from treasurypilot_worker.bridge.adapter import BridgeRoute, FakeBridgeAdapter
from treasurypilot_worker.bridge.policy import BridgePolicy, BridgeRejected
from treasurypilot_worker.bridge.service import BridgeRequest, BridgeService, PgBridgeRepository
from treasurypilot_worker.locks import create_worker_pool

API_ROOT = Path(__file__).parents[3] / "api"
_ORG = "00000000-0000-7000-8000-0000000b1d00"
_SOURCE = uuid.UUID("00000000-0000-7000-8000-0000000b1d01")
_DESTINATION = uuid.UUID("00000000-0000-7000-8000-0000000b1d02")
_POLICY = BridgePolicy(
    allowed_routes=frozenset({BridgeRoute("fake", 31337, 31338)}),
    max_transfer_amount=10_000,
    max_in_flight_amount=15_000,
)


async def _seed(database_url: str) -> None:
    engine = create_async_engine(database_url)
    statements = [f"INSERT INTO organizations (id, name) VALUES ('{_ORG}', 'Bridge test')"]
    for index, (treasury, chain_id) in enumerate(((_SOURCE, 31337), (_DESTINATION, 31338))):
        asset = f"00000000-0000-7000-8000-0000000b1d1{index}"
        statements += [
            "INSERT INTO chains (chain_id, name, is_testnet, confirmations, explorer_url, "
            f"rpc_urls) VALUES ({chain_id}, 'Anvil {chain_id}', true, 3, "
            "'https://explorer.invalid', '[\"http://rpc\"]')",
            "INSERT INTO assets (id, chain_id, address, symbol, decimals, issuer_label) "
            f"VALUES ('{asset}', {chain_id}, decode(repeat('11', 20), 'hex'), 'USDC', 6, 'Circle')",
            "INSERT INTO treasuries (id, org_id, chain_id, asset_id) "
            f"VALUES ('{treasury}', '{_ORG}', {chain_id}, '{asset}')",
            "INSERT INTO treasury_wallets (id, org_id, treasury_id, chain_id, role, label, "
            f"safe_address, owners, threshold) VALUES (gen_random_uuid(), '{_ORG}', "
            f"'{treasury}', {chain_id}, 'SOURCE', 'Source', decode(repeat('2{index}', 20), "
            "'hex'), '[\"0x" + "33" * 20 + "\"]'::jsonb, 1)",
        ]
    try:
        async with engine.begin() as connection:
            for statement in statements:
                await connection.execute(text(statement))
    finally:
        await engine.dispose()


@pytest.fixture(scope="module")
def database_url() -> Iterator[str]:
    if "TP_TEST_DATABASE_URL" not in os.environ:
        pytest.skip("TP_TEST_DATABASE_URL is required for the bridge integration tests")
    url = os.environ["TP_TEST_DATABASE_URL"]
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    command.upgrade(config, "head")
    try:
        asyncio.run(_seed(url))
        yield url
    finally:
        command.downgrade(config, "base")


def _request(key: str, amount: int = 5_000) -> BridgeRequest:
    return BridgeRequest(_SOURCE, _DESTINATION, "fake", key, amount, amount - 10)


async def _timeout_then_retry_and_settle(database_url: str) -> None:
    pool = await create_worker_pool(database_url, min_size=1, max_size=4)
    try:
        adapter = FakeBridgeAdapter(fail_send="timeout_after_accept")
        service = BridgeService(PgBridgeRepository(pool), adapter, _POLICY)
        first = await service.initiate(_request("pg-timeout"))
        assert first.status == "Unknown"
        retries = await asyncio.gather(
            *(service.initiate(_request("pg-timeout")) for _ in range(3))
        )
        assert {t.id for t in retries} == {first.id}
        await service.settle(first.id)
        assert adapter.send_calls == {"pg-timeout": 1}
        assert await service.in_flight(_SOURCE) == 5_000
        adapter.arrive("pg-timeout", 4_995)
        assert (await service.settle(first.id)).status == "Completed"
        assert await service.in_flight(_SOURCE) == 0
        assert adapter.send_calls == {"pg-timeout": 1}
    finally:
        await pool.close()


async def _concurrent_same_key_and_limits(database_url: str) -> None:
    pool = await create_worker_pool(database_url, min_size=1, max_size=8)
    try:
        adapter = FakeBridgeAdapter()
        service = BridgeService(PgBridgeRepository(pool), adapter, _POLICY)
        rows = await asyncio.gather(*(service.initiate(_request("pg-race")) for _ in range(5)))
        assert len({t.id for t in rows}) == 1
        assert adapter.send_calls == {"pg-race": 1}
        # 5 000 is in flight: 8 000 more fits under the 15 000 cap, 5 000 beyond that does not.
        await service.initiate(_request("pg-second", 8_000))
        with pytest.raises(BridgeRejected, match="IN_FLIGHT_LIMIT_EXCEEDED"):
            await service.initiate(_request("pg-third", 5_000))
        assert await service.in_flight(_SOURCE) == 13_000
    finally:
        await pool.close()


def test_timeout_never_sends_a_second_transfer(database_url: str) -> None:
    asyncio.run(_timeout_then_retry_and_settle(database_url))


def test_concurrent_requests_send_once_and_respect_in_flight_limit(database_url: str) -> None:
    asyncio.run(_concurrent_same_key_and_limits(database_url))
