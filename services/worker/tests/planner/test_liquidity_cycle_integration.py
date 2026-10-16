"""The liquidity cycle against PostgreSQL with a fake chain snapshot (EXE-014, D2 and D3).

The chain is a stored snapshot standing in for Aave on a fork (an external RPC is out of scope);
the worker-to-contract path is covered by executor/test_liquidity_cycle_anvil.py.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import uuid
from collections.abc import Awaitable, Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from eth_account import Account
from eth_account.messages import encode_typed_data

from treasurypilot_core.eip712 import payment_approval_typed_data
from treasurypilot_core.money import BaseUnits
from treasurypilot_core.policy import Decision, ExecutionPlan
from treasurypilot_worker.attestation import attest
from treasurypilot_worker.chain.snapshot import (
    Snapshot,
    SnapshotPurpose,
    SnapshotScope,
    store_snapshot,
)
from treasurypilot_worker.executor.plan_loader import load_plan
from treasurypilot_worker.executor.sequencer import PlanRun, sequence_plan
from treasurypilot_worker.locks import create_worker_pool, treasury_advisory_xact_lock
from treasurypilot_worker.planner.borrow import clear_borrow_proposal, record_borrow_proposal
from treasurypilot_worker.planner.inputs import engine_snapshot
from treasurypilot_worker.planner.liquidity import DbLiquidityStarter, plan_liquidity
from treasurypilot_worker.planner.pipeline import PlannerDeps, plan_request
from treasurypilot_worker.planner.start import DbPlanStarter, DbScheduleProvider
from treasurypilot_worker.trigger.cycles import (
    CycleSkipReason,
    ScheduledRequest,
    run_execution_cycle,
)

API_ROOT = Path(__file__).parents[3] / "api"
CHAIN_ID = 31337
ASSET = uuid.UUID("00000000-0000-7000-8000-000000000030")
EXECUTOR = "0x" + "66" * 20
A_TOKEN = "0x" + "ab" * 20
POLICY_KEY = Account.create()
APPROVER = Account.create()
SUPPLY, WITHDRAW, REFILL, PAY = 4, 5, 2, 1


def _addr(tag: str) -> bytes:
    return hashlib.sha256(tag.encode()).digest()[:20]


@dataclass
class World:
    org: uuid.UUID
    treasury: uuid.UUID
    module: str
    safe_t: str
    op: str
    payee: str
    request_hashes: list[bytes]


@pytest.fixture(scope="module")
def database_url() -> Iterator[str]:
    if "TP_TEST_DATABASE_URL" not in os.environ:
        pytest.skip("TP_TEST_DATABASE_URL is required for the liquidity cycle tests")
    url = os.environ["TP_TEST_DATABASE_URL"]
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    command.upgrade(config, "head")
    try:
        yield url
    finally:
        # liquidity rows are evidence: 0085 refuses to downgrade over them, so reset the schema
        async def reset() -> None:
            pool = await create_worker_pool(url, min_size=1, max_size=1)
            await pool.execute(
                "DROP SCHEMA IF EXISTS signer CASCADE; DROP SCHEMA public CASCADE; CREATE SCHEMA public"
            )
            await pool.close()

        asyncio.run(reset())


def pooled(fn: Callable[[Any, str], Awaitable[None]]) -> Callable[[str], None]:
    async def main(database_url: str) -> None:
        pool = await create_worker_pool(database_url, min_size=1, max_size=4)
        await pool.execute(
            "INSERT INTO chains (chain_id, name, is_testnet, confirmations, explorer_url, "
            "rpc_urls) VALUES ($1, 'Anvil', true, 3, 'https://e.test', '[\"http://rpc\"]') "
            "ON CONFLICT DO NOTHING",
            CHAIN_ID,
        )
        await pool.execute(
            "INSERT INTO assets (id, chain_id, address, symbol, decimals, issuer_label) VALUES "
            "($1, $2, decode(repeat('11', 20), 'hex'), 'USDC', 6, 'Circle') ON CONFLICT DO NOTHING",
            ASSET,
            CHAIN_ID,
        )
        try:
            await fn(pool, database_url)
        finally:
            await pool.close()

    def test(database_url: str) -> None:
        asyncio.run(main(database_url))

    test.__name__ = fn.__name__
    return test


async def _seed(pool: Any, requests: list[tuple[int, int]]) -> World:
    """A treasury with one approved request per ``(amount, due_offset_days)``."""

    tag = uuid.uuid4().hex
    org, treasury, vendor, payee_id = (uuid.uuid4() for _ in range(4))
    maker, checker = uuid.uuid4(), uuid.uuid4()
    module, safe_t, op, payee = (_addr(f"{tag}{n}") for n in ("m", "s", "o", "p"))
    module_hex = "0x" + module.hex()
    today = datetime.now(UTC).date()
    async with pool.acquire() as c, c.transaction():
        await c.execute("INSERT INTO organizations (id, name) VALUES ($1, 'Liquidity')", org)
        for user in (maker, checker):
            await c.execute("INSERT INTO users (id, email) VALUES ($1, $2)", user, f"{user}@e.test")
        await c.execute(
            "INSERT INTO treasuries (id, org_id, chain_id, asset_id, module_address, status, "
            "coverage) VALUES ($1, $2, $3, $4, $5, 'Ready', 'COMPLETE')",
            treasury, org, CHAIN_ID, ASSET, module,
        )  # fmt: skip
        for role, address in (("SOURCE", safe_t), ("OPERATIONAL", op)):
            await c.execute(
                "INSERT INTO treasury_wallets (id, org_id, treasury_id, chain_id, role, label, "
                "safe_address, owners, threshold) VALUES ($1, $2, $3, $4, $5, $6, $7, "
                "'[\"0x1\"]'::jsonb, 1)",
                uuid.uuid4(), org, treasury, CHAIN_ID, role, role, address,
            )  # fmt: skip
        await c.execute(
            "INSERT INTO mandate_versions (id, org_id, treasury_id, version, onchain_version, "
            "status, config, config_hash, valid_from, expires_at, created_by, activated_at) "
            "VALUES ($1, $2, $3, 1, 1, 'Active', '{}'::jsonb, decode(repeat('aa', 32), 'hex'), "
            "now() - interval '1 day', now() + interval '30 days', $4, now())",
            uuid.uuid4(), org, treasury, maker,
        )  # fmt: skip
        await c.execute(
            "INSERT INTO vendors (id, org_id, name, normalized_ref) VALUES ($1, $2, 'V', 'v')",
            vendor, org,
        )  # fmt: skip
        await c.execute(
            "INSERT INTO payees (id, treasury_id, org_id, vendor_id, label, address, status, "
            "oob_verified_by, oob_verified_at, oob_method, oob_note, active_from) VALUES "
            "($1, $2, $3, $4, 'Main', $5, 'Active', $6, now(), 'PHONE', 'verified', "
            "now() - interval '2 days')",
            payee_id, treasury, org, vendor, payee, maker,
        )  # fmt: skip
        await c.execute(
            "INSERT INTO screenings (id, org_id, payee_id, address, chain_id, provider, result, "
            "checked_at) VALUES ($1, $2, $3, $4, $5, 'fake', 'CLEAR', now())",
            uuid.uuid4(), org, payee_id, payee, CHAIN_ID,
        )  # fmt: skip
        wallet = await c.fetchval(
            "SELECT id FROM treasury_wallets WHERE treasury_id = $1 AND role = 'OPERATIONAL'",
            treasury,
        )
        hashes = []
        for number, (amount, due_offset) in enumerate(requests):
            request = uuid.uuid4()
            request_hash = hashlib.sha256(f"{tag}r{number}".encode()).digest()
            hashes.append(request_hash)
            fingerprint = hashlib.sha256(f"{tag}f{number}".encode()).digest()
            due = today + timedelta(days=due_offset)
            deadline = int(datetime.combine(due, datetime.min.time(), UTC).timestamp()) + 86_399
            terms = {"net_due_day": (due - datetime(1970, 1, 1).date()).days}
            message = {
                "requestId": "0x" + request_hash.hex(),
                "invoiceHash": "0x" + "02" * 32,
                "fingerprint": "0x" + fingerprint.hex(),
                "treasury": module_hex,
                "payingWallet": "0x" + op.hex(),
                "asset": "0x" + "11" * 20,
                "payee": "0x" + payee.hex(),
                "amount": str(amount),
                "earlyAmount": "0",
                "earlyPayBy": 0,
                "deadline": deadline,
                "termsHash": "0x" + "04" * 32,
                "expiry": deadline + 7 * 86_400,
                "isFiat": False,
            }
            typed = payment_approval_typed_data(
                message, chain_id=CHAIN_ID, verifying_contract=module_hex
            )
            signature = APPROVER.sign_message(encode_typed_data(full_message=typed)).signature
            await c.execute(
                "INSERT INTO payment_requests (id, org_id, treasury_id, chain_id, vendor_id, "
                "payee_id, asset_id, issue_date, due_at, invoice_no, amount, status, fingerprint,"
                " invoice_hash, terms_hash, onchain_request_id, paying_wallet_id, terms,"
                " terms_confirmed_by, terms_confirmed_at, created_by, last_edited_by) VALUES ($1,"
                " $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, 'Approved', $12, decode(repeat('02',"
                " 32), 'hex'), decode(repeat('04', 32), 'hex'), $13, $14, $15::jsonb, $16, now(),"
                " $16, $16)",
                request, org, treasury, CHAIN_ID, vendor, payee_id, ASSET,
                today - timedelta(days=5), due, f"INV-{number}", amount, fingerprint,
                request_hash, wallet, json.dumps(terms), maker,
            )  # fmt: skip
            await c.execute(
                "INSERT INTO request_revisions (id, request_id, revision, snapshot) "
                "VALUES (gen_random_uuid(), $1, 1, '{}')",
                request,
            )
            await c.execute(
                "INSERT INTO approvals (id, request_id, revision, approver_user_id, "
                "approver_address, typed_data, signature, expires_at) VALUES ($1, $2, 1, $3, $4, "
                "$5::jsonb, $6, now() + interval '7 days')",
                uuid.uuid4(), request, checker,
                bytes.fromhex(APPROVER.address.removeprefix("0x")), json.dumps(typed),
                bytes(signature),
            )  # fmt: skip
        await c.execute(
            "INSERT INTO treasury_fee_policies (id, org_id, treasury_id, preset, "
            "max_fee_multiplier_bps, tip_percentile, resend_after_s, bump_bps, "
            "per_plan_threshold_wei, daily_budget_wei, reference_eth_price, accepted_by, "
            "accepted_at, version) VALUES (gen_random_uuid(), $1, $2, 'NORMAL', 20000, 50, "
            "60, 1250, $3, $4, 1, $5, now(), 1)",
            org, treasury, 10**18, 10**19, maker,
        )  # fmt: skip
    return World(
        org, treasury, module_hex, "0x" + safe_t.hex(), "0x" + op.hex(), "0x" + payee.hex(), hashes
    )


def _chain(world: World, *, safe: int, a_token: int = 50_000) -> Snapshot:
    now = int(datetime.now(UTC).timestamp())
    zero = "0x" + "00" * 32
    request_state = {
        "paid": False,
        "cancelled": False,
        "exception": {
            "amount": "0", "expiry": 0, "mandate_version": 0, "payee": world.op, "used": False,
        },
        "refilled": {world.op: False},
    }  # fmt: skip
    data = {
        "asset": {"decimals": 6},
        "module": {
            "mandate": {
                "version": 1,
                "valid_from": now - 86_400,
                "expires_at": now + 30 * 86_400,
                "payee_cooling_seconds": 0,
                "executor": EXECUTOR,
                "guardian": "0x" + "77" * 20,
                "pay": {"per_request": "5000", "daily": "20000"},
                "refill": {"per_request": "5000", "daily": "20000"},
                "approval_max_age": 86_400,
                "supply": {"per_request": "5000", "daily": "20000"},
            },
            "status": 0,
            "used_today": {"PAY": "0", "REFILL": "0", "SUPPLY": "0"},
            "approvers": {APPROVER.address.lower(): True},
        },
        "balances": {world.safe_t: str(safe), world.op: "100"},
        "buffers": {world.safe_t: "0", world.op: "10"},
        "targets": {world.safe_t: "0", world.op: "150"},
        "payees": {world.payee: {"state": 2, "active_from": now - 2 * 86_400}},
        "requests": {zero: request_state}
        | {"0x" + h.hex(): request_state for h in world.request_hashes},
        "fingerprints": {},
        "aave": {
            "pool": "0x" + "cd" * 20,
            "a_token": A_TOKEN,
            "a_token_balance": str(a_token),
            "available_liquidity": "1000000",
        },
    }  # fmt: skip
    return Snapshot(
        purpose=SnapshotPurpose.PLAN,
        block_number=100,
        block_hash="0x" + "ab" * 32,
        block_timestamp=datetime.now(UTC) - timedelta(seconds=5),
        provider="fake",
        data=data,
        coverage="COMPLETE",
        missing=(),
    )


def _deps(pool: Any, database_url: str, world: World, snapshot: Snapshot) -> PlannerDeps:
    async def take(treasury_id: uuid.UUID, scope: SnapshotScope) -> tuple[Snapshot, int]:
        async with pool.acquire() as c:
            await store_snapshot(c, world.org, treasury_id, snapshot)
        return snapshot, snapshot.block_number

    async def fee(_treasury: uuid.UUID, plan: ExecutionPlan) -> int:
        return 1_000 * len(plan.steps)

    async def issue(
        plan_id: uuid.UUID,
        plan: Any,
        decision: Decision,
        digest: str,
        now: datetime,
        liquidity_cycle_id: str | None = None,
    ) -> None:
        await asyncio.to_thread(
            attest,
            database_url,
            POLICY_KEY,
            plan_id=plan_id,
            plan=plan,
            decision=decision,
            executor=EXECUTOR,
            evidence_digest=digest,
            now=now,
            liquidity_cycle_id=liquidity_cycle_id,
        )

    return PlannerDeps(take, EXECUTOR, fee, issue)


async def _cycle(pool: Any, world: World) -> tuple[Any, list[uuid.UUID], list[uuid.UUID]]:
    """One execution cycle; returns (result, claimed request plans, claimed liquidity plans)."""

    requests: list[uuid.UUID] = []
    liquidity: list[uuid.UUID] = []
    result = await run_execution_cycle(
        world.treasury,
        lock_for=lambda item: treasury_advisory_xact_lock(pool, item),
        schedule_provider=DbScheduleProvider(),
        plan_starter=DbPlanStarter(lambda plan_id, _t: requests.append(plan_id)),
        liquidity_starter=DbLiquidityStarter(lambda plan_id, _t: liquidity.append(plan_id)),
    )
    return result, requests, liquidity


async def _steps(pool: Any, plan_id: uuid.UUID) -> list[tuple[int, int, int]]:
    rows = await pool.fetch(
        "SELECT seq, action, amount FROM plan_steps WHERE plan_id = $1 ORDER BY seq", plan_id
    )
    return [(r["seq"], r["action"], int(r["amount"])) for r in rows]


@pooled
async def test_d2_surplus_is_supplied_and_the_reserve_stays_intact(
    pool: Any, database_url: str
) -> None:
    # One approved 1000 invoice inside the 30-day horizon but outside the 24 h payment window.
    world = await _seed(pool, [(1_000, 20)])
    chain = _chain(world, safe=100_000)

    result, requests, liquidity = await _cycle(pool, world)
    assert result.started and result.request_id is None and not requests
    (plan_id,) = liquidity
    assert result.liquidity_plan_id == plan_id

    outcome = await plan_liquidity(pool, plan_id, _deps(pool, database_url, world, chain))
    reason = await pool.fetchval("SELECT chosen_reason FROM plans WHERE id = $1", plan_id)
    assert outcome is not None and outcome.status == "Attested", reason
    # min(available 99_000, per-request 5_000): the surplus is supplied, capped by the mandate.
    steps = await _steps(pool, plan_id)
    assert steps == [(0, SUPPLY, 5_000)]
    assert 100_000 - steps[0][2] >= 1_000  # the payment reserve is still in Safe T

    plan = await pool.fetchrow(
        "SELECT request_id, liquidity_cycle_id, attestation_id, status FROM plans WHERE id = $1",
        plan_id,
    )
    assert plan["request_id"] is None and plan["attestation_id"] is not None
    assert len(plan["liquidity_cycle_id"]) == 32
    attestation = await pool.fetchrow(
        "SELECT request_id FROM attestations WHERE plan_id = $1", plan_id
    )
    assert bytes(attestation["request_id"]) == b"\x00" * 32
    validation = await pool.fetchrow(
        "SELECT decision, stage FROM validations WHERE plan_id = $1", plan_id
    )
    assert (validation["decision"], validation["stage"]) == ("ALLOW", "PLAN")


@pooled
async def test_d2_only_the_part_above_the_reserve_is_supplied(pool: Any, database_url: str) -> None:
    world = await _seed(pool, [(1_000, 20)])
    chain = _chain(world, safe=1_500)  # reserve 1000: only 500 is idle

    _, _, (plan_id,) = await _cycle(pool, world)
    await plan_liquidity(pool, plan_id, _deps(pool, database_url, world, chain))

    assert await _steps(pool, plan_id) == [(0, SUPPLY, 500)]


@pooled
async def test_d3_new_invoice_breaks_the_reserve_and_a_withdraw_is_planned(
    pool: Any, database_url: str
) -> None:
    # The only obligation is a new 2500 invoice due in 20 days; Safe T holds 1000.
    world = await _seed(pool, [(2_500, 20)])
    chain = _chain(world, safe=1_000)

    result, _, (plan_id,) = await _cycle(pool, world)
    assert result.started
    outcome = await plan_liquidity(pool, plan_id, _deps(pool, database_url, world, chain))

    assert outcome is not None and outcome.status == "Attested"
    # Deficit 1500, withdrawn with the 5 % margin of BR-032.
    assert await _steps(pool, plan_id) == [(0, WITHDRAW, 1_575)]


@pooled
async def test_d3_request_plan_starts_with_a_withdraw_when_paying_would_break_the_reserve(
    pool: Any, database_url: str
) -> None:
    # A is due now; B (2500, due in 10 days) is owed from Safe T, which holds 3000.
    world = await _seed(pool, [(1_000, 1), (2_500, 10)])
    chain = _chain(world, safe=3_000)

    result, requests, liquidity = await _cycle(pool, world)
    assert result.started and result.request_id is not None and not liquidity
    (plan_id,) = requests
    outcome = await plan_request(pool, plan_id, _deps(pool, database_url, world, chain))

    reviews = await pool.fetch("SELECT type, primary_code, reason_codes FROM review_items")
    assert outcome is not None and outcome.status == "Attested", [dict(r) for r in reviews]
    steps = await _steps(pool, plan_id)
    assert [action for _, action, _ in steps] == [WITHDRAW, REFILL, PAY]
    refill = steps[1][2]
    # Safe T after the refill is below B's 2500: the leading withdraw covers the gap (+5 %).
    deficit = 2_500 - (3_000 - refill)
    assert steps[0][2] == (deficit * 105 + 99) // 100 and deficit > 0
    validation = await pool.fetchval("SELECT decision FROM validations WHERE plan_id = $1", plan_id)
    assert validation == "ALLOW"


@pooled
async def test_d3_request_plan_has_no_withdraw_when_the_reserve_holds(
    pool: Any, database_url: str
) -> None:
    world = await _seed(pool, [(1_000, 1), (2_500, 10)])
    chain = _chain(world, safe=100_000)

    _, (plan_id,), _ = await _cycle(pool, world)
    await plan_request(pool, plan_id, _deps(pool, database_url, world, chain))

    assert [a for _, a, _ in await _steps(pool, plan_id)] == [REFILL, PAY]


@pooled
async def test_at_most_one_liquidity_plan_per_cycle_and_per_treasury(
    pool: Any, database_url: str
) -> None:
    world = await _seed(pool, [(1_000, 20)])
    chain = _chain(world, safe=100_000)

    first, _, claimed = await _cycle(pool, world)
    assert first.started and len(claimed) == 1  # one claim per cycle
    again, _, more = await _cycle(pool, world)  # the Draft is still open
    assert not again.started and not more
    await plan_liquidity(pool, claimed[0], _deps(pool, database_url, world, chain))
    later, _, more = await _cycle(pool, world)  # the plan is Attested, not finished
    assert not later.started and not more
    assert (
        await pool.fetchval(
            "SELECT count(*) FROM plans WHERE treasury_id = $1 AND request_id IS NULL",
            world.treasury,
        )
        == 1
    )


@pooled
async def test_no_liquidity_plan_while_a_request_plan_is_executing_or_in_flight(
    pool: Any, database_url: str
) -> None:
    world = await _seed(pool, [(1_000, 1)])
    chain = _chain(world, safe=100_000)
    _, (plan_id,), _ = await _cycle(pool, world)
    await plan_request(pool, plan_id, _deps(pool, database_url, world, chain))  # Attested

    # Attested request plan: the request is claimed, but Safe T is spoken for.
    result, _, liquidity = await _cycle(pool, world)
    assert not result.started and not liquidity

    await pool.execute("UPDATE plans SET status = 'Executing' WHERE id = $1", plan_id)
    result, _, liquidity = await _cycle(pool, world)
    assert result.reason is CycleSkipReason.EXECUTING_PLAN_EXISTS and not liquidity

    # Once the request plan is done the surplus can be supplied.
    await pool.execute("UPDATE plans SET status = 'Completed' WHERE id = $1", plan_id)
    await pool.execute(
        "UPDATE payment_requests SET status = 'Paid' WHERE treasury_id = $1", world.treasury
    )
    result, _, liquidity = await _cycle(pool, world)
    assert result.liquidity_plan_id is not None and len(liquidity) == 1


@pooled
async def test_nothing_to_do_leaves_no_plan_behind(pool: Any, database_url: str) -> None:
    world = await _seed(pool, [(1_000, 20)])
    chain = _chain(world, safe=1_000)  # exactly the reserve: neither supply nor withdraw

    _, _, (plan_id,) = await _cycle(pool, world)
    outcome = await plan_liquidity(pool, plan_id, _deps(pool, database_url, world, chain))

    assert outcome is not None and outcome.status == "Superseded"
    assert await pool.fetchval("SELECT count(*) FROM plans WHERE id = $1", plan_id) == 0


async def _proposals(pool: Any, world: World) -> list[tuple[uuid.UUID, str, int]]:
    rows = await pool.fetch(
        "SELECT id, status, shortfall FROM borrow_proposals WHERE treasury_id = $1 "
        "ORDER BY created_at, id",
        world.treasury,
    )
    return [(r["id"], r["status"], int(r["shortfall"])) for r in rows]


@pooled
async def test_an_uncovered_shortfall_stores_a_borrow_proposal(
    pool: Any, database_url: str
) -> None:
    # Owed 2500, Safe T holds 1000, but the pool only has 200 to give: 1300 stays uncovered.
    world = await _seed(pool, [(2_500, 20)])
    chain = _chain(world, safe=1_000, a_token=5_000)
    chain.data["aave"]["available_liquidity"] = "200"
    chain.data["aave"]["reserve"] = {
        "liquidity_rate": str(4 * 10**25),
        "variable_borrow_rate": str(6 * 10**25),
    }

    _, _, (plan_id,) = await _cycle(pool, world)
    await plan_liquidity(pool, plan_id, _deps(pool, database_url, world, chain))

    ((proposal_id, status, shortfall),) = await _proposals(pool, world)
    assert (status, shortfall) == ("Proposed", 1_300)
    row = await pool.fetchrow("SELECT * FROM borrow_proposals WHERE id = $1", proposal_id)
    assert int(row["amount"]) == 1_300 and row["reason"] and row["snapshot_id"] == chain.id
    # the partial withdrawal is still planned: it narrows the gap
    assert await _steps(pool, plan_id) == [(0, WITHDRAW, 200)]


@pooled
async def test_a_new_proposal_supersedes_the_open_one_and_no_shortfall_clears_it(
    pool: Any, database_url: str
) -> None:
    world = await _seed(pool, [(2_500, 20)])
    snapshot = engine_snapshot(_chain(world, safe=1_000).data, world.safe_t, [world.op], day=20_000)
    async with pool.acquire() as connection:
        args = (connection, world.org, world.treasury, snapshot)
        first = await record_borrow_proposal(*args, BaseUnits(1_300))
        # the same shortfall refreshes it in place: the id a reader holds stays valid
        assert await record_borrow_proposal(*args, BaseUnits(1_300)) == first
        second = await record_borrow_proposal(*args, BaseUnits(900))
        assert second != first
        assert await _proposals(pool, world) == [
            (first, "Superseded", 1_300),
            (second, "Proposed", 900),
        ]
        await clear_borrow_proposal(connection, world.treasury)
        assert [p[1] for p in await _proposals(pool, world)] == ["Superseded", "Superseded"]
        third = await record_borrow_proposal(*args, BaseUnits(900))
        assert third not in (first, second)


class _Signer:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    async def sign_and_send(self, request: dict[str, Any]) -> dict[str, Any]:
        self.sent.append(request)
        key = request["plan"]["steps"][request["stepSeq"]]["stepId"].removeprefix("0x")
        return {"txHash": "0x" + key, "nonce": 1, "from": "0x" + "ab" * 20}


class _Gate:
    def __init__(self, allow: Decision) -> None:
        self.allow = allow

    async def pre_step(self, seq: int) -> Decision:
        return self.allow

    async def reattest(self, seq: int) -> PlanRun | Decision:
        raise AssertionError("not expired")


class _Passed:
    async def verify(self, step_id: bytes, operation_id: uuid.UUID) -> str:
        return "PASSED"


_ALLOW = Decision(
    decision="ALLOW", primary=None, codes=[], warnings=[], checks=[], stage="PRE_STEP",
    step_seq=0, policy_version=b"\x01" * 32, snapshot_block=1,
)  # fmt: skip


async def _run_of(pool: Any, plan_id: uuid.UUID) -> tuple[PlanRun, Any]:
    from treasurypilot_worker.executor.outbox import StepExecution

    loaded = await load_plan(pool, plan_id)
    assert loaded is not None and loaded.request_id is None and loaded.liquidity_cycle_id
    (step,) = loaded.plan.steps
    assert step.action.value == "SUPPLY"
    execution = StepExecution(
        treasury_id=loaded.treasury_id,
        request_id=None,
        plan_step_id=loaded.plan_step_ids[0],
        step_id=step.step_id,
        kind="SUPPLY",
        chain_id=loaded.plan.chain_id,
        sign_request={
            "treasuryId": str(loaded.treasury_id),
            "plan": loaded.plan.message(),
            "stepSeq": 0,
            "payload": {"to": loaded.plan.treasury, "data": "0x"},
        },
    )
    return PlanRun(plan_id, None, (execution,), loaded.valid_until), step


@pooled
async def test_the_executor_sequences_a_liquidity_plan_without_a_request(
    pool: Any, database_url: str
) -> None:
    world = await _seed(pool, [(1_000, 20)])
    chain = _chain(world, safe=100_000)
    _, _, (plan_id,) = await _cycle(pool, world)
    await plan_liquidity(pool, plan_id, _deps(pool, database_url, world, chain))

    run, step = await _run_of(pool, plan_id)
    allow = _ALLOW
    signer = _Signer()

    first = await sequence_plan(pool, signer, run, _Gate(allow), _Passed())
    assert first.status == "Waiting" and len(signer.sent) == 1
    operation = await pool.fetchrow("SELECT request_id, kind, status FROM operations")
    assert (operation["request_id"], operation["kind"], operation["status"]) == (
        None, "SUPPLY", "Submitted",
    )  # fmt: skip

    await pool.execute(
        "UPDATE operations SET status = 'Confirmed' WHERE step_id = $1", step.step_id
    )
    done = await sequence_plan(pool, signer, run, _Gate(allow), _Passed())
    assert done.status == "Completed" and len(signer.sent) == 1


@pooled
async def test_a_reverted_step_gets_a_fresh_cycle_id_on_the_next_cycle(
    pool: Any, database_url: str
) -> None:
    world = await _seed(pool, [(1_000, 20)])
    chain = _chain(world, safe=100_000)
    _, _, (plan_id,) = await _cycle(pool, world)
    await plan_liquidity(pool, plan_id, _deps(pool, database_url, world, chain))
    run, step = await _run_of(pool, plan_id)
    signer = _Signer()
    await sequence_plan(pool, signer, run, _Gate(_ALLOW), _Passed())
    await pool.execute("UPDATE operations SET status = 'Reverted' WHERE step_id = $1", step.step_id)
    stopped = await sequence_plan(pool, signer, run, _Gate(_ALLOW), _Passed())
    assert stopped.status == "PartiallyCompleted"

    result, _, (next_plan,) = await _cycle(pool, world)
    assert result.liquidity_plan_id == next_plan
    cycles = {
        r["liquidity_cycle_id"]
        for r in await pool.fetch(
            "SELECT liquidity_cycle_id FROM plans WHERE request_id IS NULL AND treasury_id = $1",
            world.treasury,
        )
    }
    assert len(cycles) == 2  # the spent step id is not reused


@pooled
async def test_a_request_plan_waits_for_an_open_liquidity_plan(
    pool: Any, database_url: str
) -> None:
    world = await _seed(pool, [(1_000, 20)])
    _, _, (liquidity_plan,) = await _cycle(pool, world)  # Draft
    request = await pool.fetchval(
        "SELECT id FROM payment_requests WHERE treasury_id = $1", world.treasury
    )
    now = datetime.now(UTC)
    for status in ("Draft", "Attested"):
        await pool.execute("UPDATE plans SET status = $2 WHERE id = $1", liquidity_plan, status)
        async with pool.acquire() as connection:
            started = await DbPlanStarter(lambda *_: None).start(
                connection, world.treasury, ScheduledRequest(request, now, 0), now=now
            )
        assert not started
    await pool.execute("UPDATE plans SET status = 'Completed' WHERE id = $1", liquidity_plan)
    async with pool.acquire() as connection:
        assert await DbPlanStarter(lambda *_: None).start(
            connection, world.treasury, ScheduledRequest(request, now, 0), now=now
        )
