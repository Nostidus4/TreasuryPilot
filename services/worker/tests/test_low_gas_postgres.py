"""Low-gas sweep SQL and its 24 h dedupe against PostgreSQL (EXE-010)."""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import asyncpg  # type: ignore[import-untyped]
import pytest
from alembic import command
from alembic.config import Config

from treasurypilot_worker.low_gas import check_low_gas

API_ROOT = Path(__file__).parents[2] / "api"
THRESHOLD = 100
SENDER = "0x" + "aa" * 20
CONFIGURED = "0x" + "bb" * 20


@pytest.fixture(scope="module")
def database_url() -> Iterator[str]:
    if "TP_TEST_DATABASE_URL" not in os.environ:
        pytest.skip("TP_TEST_DATABASE_URL is required for the PostgreSQL low-gas test")
    url = os.environ["TP_TEST_DATABASE_URL"]
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    command.upgrade(config, "head")
    try:
        yield url
    finally:
        command.downgrade(config, "base")


async def _treasury(connection: Any, *, tx_age_days: float | None) -> tuple[uuid.UUID, uuid.UUID]:
    """A fresh org/chain/treasury, with one PAY transaction from SENDER when ``tx_age_days``."""

    org, asset, treasury, vendor, payee, request = (uuid.uuid4() for _ in range(6))
    chain_id = await connection.fetchval("SELECT COALESCE(MAX(chain_id), 100000) + 1 FROM chains")
    await connection.execute("INSERT INTO organizations (id, name) VALUES ($1, 'Low gas')", org)
    await connection.execute(
        "INSERT INTO chains (chain_id, name, is_testnet, confirmations, explorer_url, rpc_urls) "
        "VALUES ($1, 'Low gas', true, 1, 'https://e.test', '[\"https://r\"]')",
        chain_id,
    )
    await connection.execute(
        "INSERT INTO assets (id, chain_id, address, symbol, decimals, issuer_label) "
        "VALUES ($1, $2, decode(repeat('11', 20), 'hex'), 'LG', 6, 'Test')",
        asset,
        chain_id,
    )
    await connection.execute(
        "INSERT INTO treasuries (id, org_id, chain_id, asset_id) VALUES ($1, $2, $3, $4)",
        treasury,
        org,
        chain_id,
        asset,
    )
    if tx_age_days is None:
        return org, treasury
    await connection.execute(
        "INSERT INTO vendors (id, org_id, name, normalized_ref) VALUES ($1, $2, 'V', 'v')",
        vendor,
        org,
    )
    await connection.execute(
        "INSERT INTO payees (id, treasury_id, org_id, vendor_id, label, address, status) "
        "VALUES ($1, $2, $3, $4, 'Main', decode(repeat('22', 20), 'hex'), 'Proposed')",
        payee,
        treasury,
        org,
        vendor,
    )
    await connection.execute(
        "INSERT INTO payment_requests (id, org_id, treasury_id, chain_id, vendor_id, payee_id, "
        "invoice_no, issue_date, due_at, amount, asset_id) VALUES ($1, $2, $3, $4, $5, $6, "
        "'LG-1', '2026-10-01', '2026-10-31', 1000, $7)",
        request,
        org,
        treasury,
        chain_id,
        vendor,
        payee,
        asset,
    )
    operation = uuid.uuid4()
    await connection.execute(
        "INSERT INTO operations (id, treasury_id, plan_step_id, request_id, step_id, kind, "
        "payload, idempotency_key, status) VALUES ($1, $2, $3, $4, $5, 'PAY', '{}'::jsonb, $6, "
        "'Submitted')",
        operation,
        treasury,
        uuid.uuid4(),
        request,
        uuid.uuid4().bytes * 2,
        str(operation),
    )
    await connection.execute(
        "INSERT INTO transactions (id, operation_id, chain_id, tx_hash, nonce, from_address, "
        "submitted_at) VALUES (gen_random_uuid(), $1, $2, decode(repeat('33', 32), 'hex'), 1, "
        "decode(repeat('aa', 20), 'hex'), now() - make_interval(secs => $3))",
        operation,
        chain_id,
        tx_age_days * 86400,
    )
    return org, treasury


async def _sweep(connection: Any, balances: dict[str, int], configured: Any = ()) -> dict[str, int]:
    class Rpc:
        async def call(self, method: str, params: list[Any]) -> str:
            return hex(balances.get(params[0], 10**18))

    return await check_low_gas(connection, lambda urls: Rpc(), THRESHOLD, configured)


async def _events(connection: Any, treasury: uuid.UUID) -> list[Any]:
    return await connection.fetch(
        "SELECT type, entity_type, entity_id, payload FROM domain_events WHERE treasury_id = $1 "
        "ORDER BY created_at",
        treasury,
    )


async def _scenario(database_url: str) -> None:
    connection = await asyncpg.connect(
        database_url.replace("postgresql+asyncpg://", "postgresql://")
    )
    try:
        low = {SENDER: 7}
        _, treasury = await _treasury(connection, tx_age_days=1)

        # Cold sweep of other treasuries is irrelevant; only this treasury's events are asserted.
        assert (await _sweep(connection, low))["emitted"] >= 1
        assert (await _sweep(connection, low))["emitted"] == 0  # 24 h dedupe
        (event,) = await _events(connection, treasury)
        assert (event["type"], event["entity_type"], event["entity_id"]) == (
            "LowGas",
            "treasury",
            treasury,
        )
        assert json.loads(event["payload"]) == {
            "role": "executor",
            "address": SENDER,
            "balanceWei": "7",
            "thresholdWei": str(THRESHOLD),
        }

        # An alert older than 24 h no longer suppresses a new one.
        await connection.execute(
            "UPDATE domain_events SET created_at = now() - interval '25 hours' "
            "WHERE treasury_id = $1",
            treasury,
        )
        await _sweep(connection, low)
        assert len(await _events(connection, treasury)) == 2

        # Above the threshold: nothing.
        _, funded = await _treasury(connection, tx_age_days=1)
        await _sweep(connection, {SENDER: THRESHOLD})
        assert await _events(connection, funded) == []

        # Transactions older than 30 days are not swept.
        _, stale = await _treasury(connection, tx_age_days=31)
        await _sweep(connection, low)
        assert await _events(connection, stale) == []

        # Cold start: a configured executor that never sent a tx is still checked.
        _, cold = await _treasury(connection, tx_age_days=None)
        await _sweep(connection, {CONFIGURED: 1}, [("sentinel", CONFIGURED)])
        (cold_event,) = await _events(connection, cold)
        assert json.loads(cold_event["payload"])["role"] == "sentinel"
    finally:
        await connection.close()


def test_low_gas_sweep_and_dedupe_against_real_postgres(database_url: str) -> None:
    asyncio.run(_scenario(database_url))
