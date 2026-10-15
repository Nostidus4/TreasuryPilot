"""Circuit rules trip an auto-pause within one evaluation cycle (RCV-006) against PostgreSQL."""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from pathlib import Path

import asyncpg  # type: ignore[import-untyped]
import pytest
from alembic import command
from alembic.config import Config

from treasurypilot_worker.recovery.circuit import evaluate_circuit_breakers

API_ROOT = Path(__file__).parents[2] / "api"
WALLET = bytes.fromhex("aa" * 20)


class _Sentinel:
    def __init__(self) -> None:
        self.calls: list[uuid.UUID] = []

    async def __call__(self, treasury_id: uuid.UUID) -> str:
        self.calls.append(treasury_id)
        return "SENTINEL_SUBMITTED"


class _World:
    def __init__(self, pool: asyncpg.Pool, org: uuid.UUID, asset: uuid.UUID, chain: int) -> None:
        self.pool, self.org, self.asset, self.chain = pool, org, asset, chain
        self.requests: dict[uuid.UUID, uuid.UUID] = {}

    async def treasury(self) -> uuid.UUID:
        tid = uuid.uuid4()
        await self.pool.execute(
            "INSERT INTO treasuries (id, org_id, chain_id, asset_id, status, coverage) "
            "VALUES ($1, $2, $3, $4, 'Ready', 'COMPLETE')",
            tid,
            self.org,
            self.chain,
            self.asset,
        )
        return tid

    async def request(self, tid: uuid.UUID) -> uuid.UUID:
        if tid in self.requests:
            return self.requests[tid]
        vendor, payee, request = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        await self.pool.execute(
            "INSERT INTO vendors (id, org_id, name, normalized_ref) VALUES ($1, $2, 'V', $3)",
            vendor,
            self.org,
            str(vendor),
        )
        await self.pool.execute(
            "INSERT INTO payees (id, treasury_id, org_id, vendor_id, label, address, status) "
            "VALUES ($1, $2, $3, $4, 'Main', decode(repeat('22', 20), 'hex'), 'Proposed')",
            payee,
            tid,
            self.org,
            vendor,
        )
        await self.pool.execute(
            "INSERT INTO payment_requests (id, org_id, treasury_id, chain_id, vendor_id, payee_id, "
            "invoice_no, issue_date, due_at, amount, asset_id) VALUES ($1, $2, $3, $4, $5, $6, "
            "'INV', '2026-10-01', '2026-10-31', 1001, $7)",
            request,
            self.org,
            tid,
            self.chain,
            vendor,
            payee,
            self.asset,
        )
        self.requests[tid] = request
        return request

    async def operation(self, tid: uuid.UUID, status: str = "Reverted") -> uuid.UUID:
        oid = uuid.uuid4()
        await self.pool.execute(
            "INSERT INTO operations (id, treasury_id, plan_step_id, request_id, step_id, kind, "
            "payload, idempotency_key, status) VALUES ($1, $2, gen_random_uuid(), "
            "$5, sha256($3::text::bytea), 'PAY', '{}'::jsonb, $3, $4)",
            oid,
            tid,
            str(oid),
            status,
            await self.request(tid),
        )
        return oid

    async def outflow(self, tid: uuid.UUID, amount: int, balance: int) -> None:
        event, movement = uuid.uuid4(), uuid.uuid4()
        await self.pool.execute(
            "INSERT INTO snapshots (id, org_id, treasury_id, purpose, block_number, block_hash, "
            "block_timestamp, provider, data, coverage, missing) VALUES ($1, $2, $3, 'DASHBOARD', 1, "
            "decode(repeat('01', 32), 'hex'), now() - interval '1 hour', 'p', $4::jsonb, 'COMPLETE', '[]')",
            uuid.uuid4(),
            self.org,
            tid,
            json.dumps({"balances": {"0x" + WALLET.hex(): str(balance)}}),
        )
        await self.pool.execute(
            "INSERT INTO observed_events (id, treasury_id, chain_id, stream, block_number, block_hash, "
            "tx_hash, log_index, address, event_name, payload) VALUES ($1, $2, $3, 'TOKEN', 1, "
            "decode(repeat('01', 32), 'hex'), $4, 0, $5, 'Transfer', '{}'::jsonb)",
            event,
            tid,
            self.chain,
            uuid.uuid4().bytes * 2,
            WALLET,
        )
        await self.pool.execute(
            "INSERT INTO token_movements (id, treasury_id, event_id, wallet, direction, counterparty, "
            "amount, \"class\") VALUES ($1, $2, $3, $4, 'OUT', $4, $5, 'UNEXPECTED_OUTFLOW')",
            movement,
            tid,
            event,
            WALLET,
            amount,
        )
        await self.pool.execute(
            "INSERT INTO chain_safety_signals (id, treasury_id, observed_event_id, token_movement_id, "
            "signal_type, payload) VALUES ($1, $2, $3, $4, 'CIRCUIT_BREAKER', '{}'::jsonb)",
            uuid.uuid4(),
            tid,
            event,
            movement,
        )

    async def paused(self, tid: uuid.UUID) -> bool:
        return bool(
            await self.pool.fetchval("SELECT paused FROM backend_pause WHERE treasury_id = $1", tid)
        )

    async def events(self, tid: uuid.UUID) -> list[tuple[str, str]]:
        rows = await self.pool.fetch(
            "SELECT rule, action FROM circuit_events WHERE treasury_id = $1 ORDER BY created_at",
            tid,
        )
        return [(r["rule"], r["action"]) for r in rows]


async def _scenarios(database_url: str) -> None:
    pool = await asyncpg.create_pool(database_url.replace("postgresql+asyncpg://", "postgresql://"))
    org, asset = uuid.uuid4(), uuid.uuid4()
    chain = await pool.fetchval("SELECT COALESCE(MAX(chain_id), 100000) + 1 FROM chains")
    await pool.execute("INSERT INTO organizations (id, name) VALUES ($1, 'Circuit')", org)
    await pool.execute(
        "INSERT INTO chains (chain_id, name, is_testnet, confirmations, explorer_url, rpc_urls) "
        "VALUES ($1, 'Circuit', true, 1, 'https://e.test', '[\"https://r\"]')",
        chain,
    )
    await pool.execute(
        "INSERT INTO assets (id, chain_id, address, symbol, decimals, issuer_label) "
        "VALUES ($1, $2, decode(repeat('11', 20), 'hex'), 'CIR', 6, 'T')",
        asset,
        chain,
    )
    world, sentinel = _World(pool, org, asset, chain), _Sentinel()
    try:
        # Two rejections do not trip; the third does, in the very next cycle, and calls the sentinel.
        a = await world.treasury()
        for _ in range(2):
            await world.operation(a)
        await evaluate_circuit_breakers(pool, sentinel)
        assert not await world.paused(a) and sentinel.calls == []
        await world.operation(a, "Pending")  # not a rejection
        await world.operation(a)
        assert await evaluate_circuit_breakers(pool, sentinel) == 1
        assert await world.paused(a) and sentinel.calls == [a]
        assert await world.events(a) == [("REJECTIONS", "PAUSE")]
        assert (
            await pool.fetchval(
                "SELECT count(*) FROM domain_events WHERE treasury_id = $1 AND type = 'CircuitBreakerTripped'",
                a,
            )
            == 1
        )
        # Cool-down: the same rule does not fire again within 30 minutes.
        await evaluate_circuit_breakers(pool, sentinel)
        assert await world.events(a) == [("REJECTIONS", "PAUSE")]

        # An Owner-tightened rule trips sooner (2 in 10 min).
        b = await world.treasury()
        await pool.execute(
            "INSERT INTO circuit_rules (id, org_id, treasury_id, rule, threshold, window_seconds) "
            "VALUES ($1, $2, $3, 'REJECTIONS', 2, 600)",
            uuid.uuid4(),
            org,
            b,
        )
        await world.operation(b)
        await world.operation(b)
        await evaluate_circuit_breakers(pool, sentinel)
        assert await world.paused(b)

        # Coverage COMPLETE -> PARTIAL pauses; the first cycle only records the baseline.
        c = await world.treasury()
        await evaluate_circuit_breakers(pool, sentinel)
        assert not await world.paused(c)
        await pool.execute("UPDATE treasuries SET coverage = 'PARTIAL' WHERE id = $1", c)
        await evaluate_circuit_breakers(pool, sentinel)
        assert await world.events(c) == [("COVERAGE_DROP", "PAUSE")]

        # AI_PLAN_REJECTED (one review item) pauses; a post-condition DISCREPANCY signal pauses.
        d = await world.treasury()
        await pool.execute(
            "INSERT INTO review_items (id, org_id, treasury_id, request_id, request_version, type, "
            "primary_code, reason_codes, completed_steps, assigned_roles, sla_due_at) VALUES "
            "($1, $2, $3, $4, 1, 'AI_REJECTED', 'AI_PLAN_REJECTED', ARRAY['AI_PLAN_REJECTED'], "
            "'[]'::jsonb, ARRAY['Owner'], now() + interval '1 day')",
            uuid.uuid4(),
            org,
            d,
            await world.request(d),
        )
        await evaluate_circuit_breakers(pool, sentinel)
        assert await world.events(d) == [("AI_PLAN_REJECTED", "PAUSE")]

        g = await world.treasury()
        verdict, signal = uuid.uuid4(), uuid.uuid4()
        operation = await world.operation(g, "Confirmed")
        await pool.execute(
            "INSERT INTO verifications (id, operation_id, expected, observed, diffs, result) "
            "VALUES ($1, $2, '{}'::jsonb, '{}'::jsonb, '[]'::jsonb, 'DISCREPANCY')",
            verdict,
            operation,
        )
        await pool.execute(
            "INSERT INTO chain_safety_signals (id, treasury_id, verification_id, signal_type, payload) "
            "VALUES ($1, $2, $3, 'CIRCUIT_BREAKER', '{}'::jsonb)",
            signal,
            g,
            verdict,
        )
        await evaluate_circuit_breakers(pool, sentinel)
        assert await world.events(g) == [("DISCREPANCY", "PAUSE")] and await world.paused(g)

        # Unexpected outflow: 5 % of the balance only alerts, 30 % pauses.
        e, f = await world.treasury(), await world.treasury()
        await world.outflow(e, 50, 1000)
        await world.outflow(f, 300, 1000)
        await evaluate_circuit_breakers(pool, sentinel)
        assert await world.events(e) == [
            ("UNEXPECTED_OUTFLOW", "ALERT")
        ] and not await world.paused(e)
        assert await world.events(f) == [("UNEXPECTED_OUTFLOW", "PAUSE")] and await world.paused(f)
        before = len(sentinel.calls)
        await evaluate_circuit_breakers(pool, sentinel)  # the same signal is not handled twice
        assert len(sentinel.calls) == before
    finally:
        await pool.close()


@pytest.fixture(scope="module")
def url() -> str:
    if "TP_TEST_DATABASE_URL" not in os.environ:
        pytest.skip("TP_TEST_DATABASE_URL is required for the circuit-breaker integration test")
    database_url = os.environ["TP_TEST_DATABASE_URL"]
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    command.upgrade(config, "head")
    return database_url


def test_rules_trip_an_auto_pause_within_one_cycle(url: str) -> None:
    asyncio.run(_scenarios(url))
