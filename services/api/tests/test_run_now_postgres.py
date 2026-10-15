"""Operator run-now: scheduler gates, problem codes and one outbox job per Idempotency-Key."""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI, Request, Response
from fastapi.testclient import TestClient
from sqlalchemy import text

from treasurypilot_api.database import create_session_factory
from treasurypilot_api.execution.routes import router, run_now
from treasurypilot_api.identity.api import problem_response
from treasurypilot_api.identity.auth import AuthFailure
from treasurypilot_api.identity.rbac import MemberAccess, require_member

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
            # Fixture rows skip FKs (payment requests, memberships); the test db user is a superuser.
            await connection.execute(text("SET LOCAL session_replication_role = replica"))
            await connection.execute(text(statement), {"t": TREASURY, "o": ORG})

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

        # Treasury not Ready (and not paused) is its own reason.
        await sql("UPDATE treasuries SET status = 'ModulePending' WHERE id = :t")
        assert await blocked("k-notready") == "TREASURY_NOT_READY"
        await sql("UPDATE treasuries SET status = 'Ready' WHERE id = :t")

        # Unknown outcomes (operation or transaction level) and executing work block the run.
        op_insert = (
            "INSERT INTO operations (id, treasury_id, plan_step_id, request_id, step_id, kind, "
            "payload, idempotency_key, status) VALUES (gen_random_uuid(), :t, gen_random_uuid(), "
            "gen_random_uuid(), decode(md5(random()::text) || md5(random()::text), 'hex'), 'PAY', '{}'::jsonb, 'op-' || gen_random_uuid(), "
            "'%s')"
        )
        for status, code in (
            ("Unknown", "UNKNOWN_OPERATION_PENDING"),
            ("Pending", "EXECUTING_PLAN_EXISTS"),
        ):
            await sql(op_insert % status)
            assert await blocked(f"k-op-{status}") == code
            await sql("DELETE FROM operations WHERE treasury_id = :t")
        await sql(op_insert % "Confirmed")
        await sql(
            "INSERT INTO transactions (id, operation_id, chain_id, tx_hash, nonce, from_address, "
            "status) SELECT gen_random_uuid(), id, 31337, decode(md5(random()::text) || md5(random()::text), 'hex'), 1, "
            "decode(repeat('ab', 20), 'hex'), 'Unknown' FROM operations WHERE treasury_id = :t"
        )
        assert await blocked("k-tx-unknown") == "UNKNOWN_OPERATION_PENDING"
        await sql("DELETE FROM transactions")
        await sql("DELETE FROM operations WHERE treasury_id = :t")
        await sql(
            "INSERT INTO plans (id, org_id, treasury_id, request_id, status) "
            "VALUES (gen_random_uuid(), :o, :t, gen_random_uuid(), 'Executing')"
        )
        assert await blocked("k-plan") == "EXECUTING_PLAN_EXISTS"
        await sql("DELETE FROM plans WHERE treasury_id = :t")
        assert await jobs() == 0

        # Same key twice (also concurrently) is one job; a new key is a new job.
        first, second, third = await asyncio.gather(call("k1"), call("k1"), call("k1"))
        assert first == second == third
        assert await jobs() == 1
        assert await call("k2") != first
        assert await jobs() == 2
        async with engine.begin() as c:
            row = (
                await c.execute(
                    text("SELECT org_id, treasury_id, type FROM domain_events WHERE id = :i"),
                    {"i": first},
                )
            ).one()
        assert (row.org_id, row.treasury_id, row.type) == (
            ORG,
            TREASURY,
            "ExecutionCycleRequested",
        )

        # Partial coverage passes once acknowledged with an actor, time and reason.
        await sql(
            "UPDATE treasuries SET coverage = 'PARTIAL', coverage_ack_by = gen_random_uuid(), "
            "coverage_ack_at = now(), coverage_ack_reason = 'accepted' WHERE id = :t"
        )
        await call("k-partial")
        assert await jobs() == 3

        # HTTP level: role dependency, header parsing and the problem+json mapping.
        roles: set[str] = {"Finance"}

        async def fake_member() -> MemberAccess:
            return MemberAccess(access=member.access, organization_id=ORG, roles=frozenset(roles))

        # TestClient runs the app in its own loop, so it gets its own engine.
        @asynccontextmanager
        async def lifespan(app: FastAPI) -> AsyncIterator[None]:
            http_engine, app.state.request_sessions = create_session_factory(url)
            yield
            await http_engine.dispose()

        http_app = FastAPI(lifespan=lifespan)
        http_app.dependency_overrides[require_member] = fake_member
        http_app.include_router(router)

        async def handle(request: Request, error: Exception) -> Response:
            assert isinstance(error, AuthFailure)
            return problem_response(request, error)

        http_app.add_exception_handler(AuthFailure, handle)
        path = f"/v1/orgs/{ORG}/treasuries/{TREASURY}/run-now"

        def http_checks() -> None:
            nonlocal roles
            with TestClient(http_app) as client:
                keyed = {"Idempotency-Key": "h1"}
                for forbidden in ({"Finance"}, {"Approver"}, {"Finance", "Approver"}):
                    roles = forbidden
                    assert client.post(path, headers=keyed).status_code == 403
                roles = {"Operator"}
                missing = client.post(path)
                assert missing.status_code == 400
                assert missing.headers["content-type"].startswith("application/problem+json")
                assert missing.json()["code"] == "IDEMPOTENCY_KEY_REQUIRED"
                ok = client.post(path, headers=keyed)
                assert ok.status_code == 202
                assert client.post(path, headers=keyed).json() == ok.json()
                roles = {"Owner"}
                assert client.post(path, headers={"Idempotency-Key": "h2"}).status_code == 202

        await asyncio.to_thread(http_checks)
        assert await jobs() == 5

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
