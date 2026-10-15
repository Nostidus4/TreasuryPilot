"""Operator run-now: scheduler gates, problem codes and one outbox job per Idempotency-Key."""

from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI, Request
from sqlalchemy import text

from treasurypilot_api.database import create_session_factory
from treasurypilot_api.execution.routes import run_now
from treasurypilot_api.identity.auth import AuthFailure
from treasurypilot_api.identity.rbac import MemberAccess

API_ROOT = Path(__file__).parents[1]
ORG, USER, ASSET, TREASURY = (uuid.uuid4() for _ in range(4))


def _config(url: str) -> Config:
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return config


async def _scenario(url: str) -> None:
    engine, sessions = create_session_factory(url)
    app = FastAPI()
    app.state.request_sessions = sessions
    request = Request({"type": "http", "app": app, "method": "POST", "path": "/"})
    member = MemberAccess(
        access=SimpleNamespace(user=SimpleNamespace(id=USER)),  # type: ignore[arg-type]
        organization_id=ORG,
        roles=frozenset({"Operator"}),
    )

    async def sql(statement: str) -> None:
        async with engine.begin() as connection:
            await connection.execute(text(statement), {"t": TREASURY})

    async def call(key: str) -> uuid.UUID:
        return (await run_now(ORG, TREASURY, request, member, key)).job_id

    async def blocked(key: str) -> str:
        with pytest.raises(AuthFailure) as info:
            await call(key)
        assert info.value.status == 409
        return info.value.code

    async def jobs() -> int:
        async with engine.begin() as connection:
            return int(
                await connection.scalar(
                    text(
                        "SELECT count(*) FROM domain_events WHERE type = 'ExecutionCycleRequested'"
                    )
                )
                or 0
            )

    try:
        async with engine.begin() as c:
            await c.execute(
                text("INSERT INTO organizations (id, name) VALUES (:o, 'rn')"), {"o": ORG}
            )
            await c.execute(
                text("INSERT INTO users (id, email) VALUES (:u, 'rn@example.test')"), {"u": USER}
            )
            await c.execute(
                text(
                    "INSERT INTO chains (chain_id, name, is_testnet, confirmations, explorer_url, rpc_urls) "
                    "VALUES (31337, 'Anvil', true, 3, 'https://e.invalid', '[\"http://rpc\"]')"
                )
            )
            await c.execute(
                text(
                    "INSERT INTO assets (id, chain_id, address, symbol, decimals, issuer_label) "
                    "VALUES (:a, 31337, decode(repeat('11', 20), 'hex'), 'USDC', 6, 'Circle')"
                ),
                {"a": ASSET},
            )
            await c.execute(
                text(
                    "INSERT INTO treasuries (id, org_id, chain_id, asset_id, status, coverage) "
                    "VALUES (:t, :o, 31337, :a, 'Ready', 'COMPLETE')"
                ),
                {"t": TREASURY, "o": ORG, "a": ASSET},
            )
            await c.execute(
                text(
                    "INSERT INTO mandate_versions (id, org_id, treasury_id, version, onchain_version, "
                    "status, config, config_hash, valid_from, expires_at, created_by, activated_at) "
                    "VALUES (:m, :o, :t, 1, 1, 'Active', '{}'::jsonb, decode(repeat('22', 32), 'hex'), "
                    "now() - interval '1 day', now() + interval '1 day', :u, now())"
                ),
                {"m": uuid.uuid4(), "o": ORG, "t": TREASURY, "u": USER},
            )

        # Gates fail closed with the scheduler's reasons and enqueue nothing.
        await sql("UPDATE treasuries SET status = 'Paused' WHERE id = :t")
        assert await blocked("k-paused") == "TREASURY_PAUSED"
        await sql("UPDATE treasuries SET status = 'Ready' WHERE id = :t")
        await sql(
            "INSERT INTO backend_pause (treasury_id, org_id, paused, reason) "
            "SELECT id, org_id, true, 'test' FROM treasuries WHERE id = :t"
        )
        assert await blocked("k-backend") == "TREASURY_PAUSED"
        await sql("DELETE FROM backend_pause WHERE treasury_id = :t")
        await sql("UPDATE treasuries SET coverage = 'UNKNOWN' WHERE id = :t")
        assert await blocked("k-coverage") == "COVERAGE_INCOMPLETE"
        await sql("UPDATE treasuries SET coverage = 'COMPLETE' WHERE id = :t")
        await sql("UPDATE mandate_versions SET status = 'Revoked' WHERE treasury_id = :t")
        assert await blocked("k-mandate") == "MANDATE_NOT_ACTIVE"
        await sql("UPDATE mandate_versions SET status = 'Active' WHERE treasury_id = :t")
        assert await jobs() == 0

        # Same key twice (also concurrently) is one job; a new key is a new job.
        first, second, third = await asyncio.gather(call("k1"), call("k1"), call("k1"))
        assert first == second == third
        assert await jobs() == 1
        assert await call("k2") != first
        assert await jobs() == 2

        with pytest.raises(AuthFailure) as info:
            await run_now(uuid.uuid4(), TREASURY, request, member, "k3")
        assert info.value.status == 404
    finally:
        await engine.dispose()


def test_run_now_applies_scheduler_gates_and_enqueues_once() -> None:
    if "TP_TEST_DATABASE_URL" not in os.environ:
        pytest.skip("TP_TEST_DATABASE_URL is required for run-now integration tests")
    url = os.environ["TP_TEST_DATABASE_URL"]
    config = _config(url)
    command.upgrade(config, "head")
    try:
        asyncio.run(_scenario(url))
    finally:
        command.downgrade(config, "base")
