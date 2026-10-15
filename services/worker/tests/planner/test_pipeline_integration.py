"""Planning pipeline against PostgreSQL with a fake chain snapshot and a fake LLM (EXE-004)."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
import uuid
from collections.abc import Awaitable, Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from eth_account import Account
from eth_account.messages import encode_typed_data
from eth_hash.auto import keccak

from treasurypilot_api.audit.chain import DumpRecord, verify_chain
from treasurypilot_core.domain.fee_policy import FeeDecision
from treasurypilot_core.eip712 import SWAP_IN, payment_approval_typed_data
from treasurypilot_core.engine import GasQuote
from treasurypilot_core.policy import Decision, ExecutionPlan
from treasurypilot_worker.agent.plan_proposer import PlanProposalRejected
from treasurypilot_worker.attestation import attest
from treasurypilot_worker.celery_app import app as celery_app
from treasurypilot_worker.chain.event_handlers import activate_due_payees
from treasurypilot_worker.chain.snapshot import Snapshot, SnapshotPurpose, SnapshotScope
from treasurypilot_worker.locks import create_worker_pool, treasury_advisory_xact_lock
from treasurypilot_worker.notify.publisher import publish_pending_events
from treasurypilot_worker.planner.ai import CeleryAiProposer
from treasurypilot_worker.planner.gas import GasSwapDeps
from treasurypilot_worker.planner.pipeline import (
    AiOutcome,
    PlannerDeps,
    _fee_assessment,
    plan_request,
)
from treasurypilot_worker.planner.start import DbPlanStarter, DbScheduleProvider, DbScheduleWriter
from treasurypilot_worker.tasks import PLAN_ENQUEUE_COUNTDOWN_SECONDS
from treasurypilot_worker.trigger.cycles import (
    CycleSkipReason,
    run_execution_cycle,
    run_scheduling_cycle,
)

PICKUP_BUDGET_SECONDS = 1.0  # assumed idle-worker pickup per hop; not measured
API_ROOT = Path(__file__).parents[3] / "api"
CHAIN_ID = 31337
ASSET = uuid.UUID("00000000-0000-7000-8000-000000000030")
EXECUTOR = "0x" + "66" * 20
POLICY_KEY = Account.create()
APPROVER = Account.create()


def _addr(tag: str) -> bytes:
    return hashlib.sha256(tag.encode()).digest()[:20]


@dataclass
class World:
    org: uuid.UUID
    treasury: uuid.UUID
    request: uuid.UUID
    module: str
    safe_t: str
    op: str
    payee: str
    request_hash: bytes
    fingerprint: bytes
    amount: int


@pytest.fixture(scope="module")
def database_url() -> Iterator[str]:
    if "TP_TEST_DATABASE_URL" not in os.environ:
        pytest.skip("TP_TEST_DATABASE_URL is required for the planning integration tests")
    url = os.environ["TP_TEST_DATABASE_URL"]
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    command.upgrade(config, "head")
    try:
        yield url
    finally:
        command.downgrade(config, "base")


def pooled(fn: Callable[[Any, str], Awaitable[None]]) -> Callable[[str], None]:
    """Run an async test body with a seeded-chain pool (no async pytest plugin in this repo)."""

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


async def _seed(
    pool: Any,
    *,
    amount: int = 1_000,
    terms: dict[str, Any] | None = None,
    fee_threshold: int | None = 10**18,
    flag: bool = False,
    due_offset: int = 1,
) -> World:
    tag = uuid.uuid4().hex
    org, treasury, vendor, payee_id, request = (uuid.uuid4() for _ in range(5))
    maker, checker = uuid.uuid4(), uuid.uuid4()
    module, safe_t, op, payee = (_addr(f"{tag}{n}") for n in ("m", "s", "o", "p"))
    request_hash = hashlib.sha256(f"{tag}r".encode()).digest()
    fingerprint = hashlib.sha256(f"{tag}f".encode()).digest()
    today = datetime.now(UTC).date()
    due = today + timedelta(days=due_offset)
    deadline = int(datetime.combine(due, datetime.min.time(), UTC).timestamp()) + 86_399
    terms = terms or {"net_due_day": (due - datetime(1970, 1, 1).date()).days}
    module_hex = "0x" + module.hex()
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
    typed = payment_approval_typed_data(message, chain_id=CHAIN_ID, verifying_contract=module_hex)
    signature = APPROVER.sign_message(encode_typed_data(full_message=typed)).signature
    async with pool.acquire() as c, c.transaction():
        await c.execute("INSERT INTO organizations (id, name) VALUES ($1, 'Plan test')", org)
        for user in (maker, checker):
            await c.execute("INSERT INTO users (id, email) VALUES ($1, $2)", user, f"{user}@e.test")
        await c.execute(
            "INSERT INTO treasuries (id, org_id, chain_id, asset_id, module_address, status, "
            "coverage) VALUES ($1, $2, $3, $4, $5, 'Ready', 'COMPLETE')",
            treasury,
            org,
            CHAIN_ID,
            ASSET,
            module,
        )
        for role, address in (("SOURCE", safe_t), ("OPERATIONAL", op)):
            await c.execute(
                "INSERT INTO treasury_wallets (id, org_id, treasury_id, chain_id, role, label, "
                "safe_address, owners, threshold) VALUES ($1, $2, $3, $4, $5, $6, $7, "
                "'[\"0x1\"]'::jsonb, 1)",
                uuid.uuid4(),
                org,
                treasury,
                CHAIN_ID,
                role,
                role,
                address,
            )
        await c.execute(
            "INSERT INTO mandate_versions (id, org_id, treasury_id, version, onchain_version, "
            "status, config, config_hash, valid_from, expires_at, created_by, activated_at) "
            "VALUES ($1, $2, $3, 1, 1, 'Active', '{}'::jsonb, decode(repeat('aa', 32), 'hex'), "
            "now() - interval '1 day', now() + interval '30 days', $4, now())",
            uuid.uuid4(),
            org,
            treasury,
            maker,
        )
        await c.execute(
            "INSERT INTO vendors (id, org_id, name, normalized_ref) VALUES ($1, $2, 'V', 'v')",
            vendor,
            org,
        )
        await c.execute(
            "INSERT INTO payees (id, treasury_id, org_id, vendor_id, label, address, status, "
            "oob_verified_by, oob_verified_at, oob_method, oob_note, active_from) VALUES "
            "($1, $2, $3, $4, 'Main', $5, 'Active', $6, now(), 'PHONE', 'verified', "
            "now() - interval '2 days')",
            payee_id,
            treasury,
            org,
            vendor,
            payee,
            maker,
        )
        await c.execute(
            "INSERT INTO screenings (id, org_id, payee_id, address, chain_id, provider, result, "
            "checked_at) VALUES ($1, $2, $3, $4, $5, 'fake', 'CLEAR', now())",
            uuid.uuid4(),
            org,
            payee_id,
            payee,
            CHAIN_ID,
        )
        wallet = await c.fetchval(
            "SELECT id FROM treasury_wallets WHERE treasury_id = $1 AND role = 'OPERATIONAL'",
            treasury,
        )
        await c.execute(
            "INSERT INTO payment_requests (id, org_id, treasury_id, chain_id, vendor_id, payee_id,"
            " asset_id, issue_date, due_at, invoice_no, amount, status, fingerprint, invoice_hash,"
            " terms_hash, onchain_request_id, paying_wallet_id, terms, terms_confirmed_by,"
            " terms_confirmed_at, created_by, last_edited_by) VALUES ($1, $2, $3, $4, $5, $6, $7,"
            " $8, $9, 'INV-1', $10, 'Approved', $11, decode(repeat('02', 32), 'hex'),"
            " decode(repeat('04', 32), 'hex'), $12, $13, $14::jsonb, $15, now(), $15, $15)",
            request,
            org,
            treasury,
            CHAIN_ID,
            vendor,
            payee_id,
            ASSET,
            today - timedelta(days=5),
            due,
            amount,
            fingerprint,
            request_hash,
            wallet,
            json.dumps(terms),
            maker,
        )
        await c.execute(
            "INSERT INTO request_revisions (id, request_id, revision, snapshot) "
            "VALUES (gen_random_uuid(), $1, 1, '{}')",
            request,
        )
        await c.execute(
            "INSERT INTO approvals (id, request_id, revision, approver_user_id, approver_address,"
            " typed_data, signature, expires_at) VALUES ($1, $2, 1, $3, $4, $5::jsonb, $6,"
            " now() + interval '7 days')",
            uuid.uuid4(),
            request,
            checker,
            bytes.fromhex(APPROVER.address.removeprefix("0x")),
            json.dumps(typed),
            bytes(signature),
        )
        if flag:
            await c.execute(
                "INSERT INTO flags (id, request_id, revision, code, severity, evidence, source) "
                "VALUES (gen_random_uuid(), $1, 1, 'NEW_VENDOR', 'HIGH', '{}'::jsonb, 'DETERMINISTIC')",
                request,
            )
        if fee_threshold is not None:
            await c.execute(
                "INSERT INTO treasury_fee_policies (id, org_id, treasury_id, preset, "
                "max_fee_multiplier_bps, tip_percentile, resend_after_s, bump_bps, "
                "per_plan_threshold_wei, daily_budget_wei, reference_eth_price, accepted_by, "
                "accepted_at, version) VALUES (gen_random_uuid(), $1, $2, 'NORMAL', 20000, 50, "
                "60, 1250, $3, $4, 1, $5, now(), 1)",
                org,
                treasury,
                fee_threshold,
                10**19,
                maker,
            )
    return World(
        org, treasury, request, module_hex, "0x" + safe_t.hex(), "0x" + op.hex(),
        "0x" + payee.hex(), request_hash, fingerprint, amount,
    )  # fmt: skip


def _chain(world: World, *, wallet_balance: int = 100) -> Snapshot:
    now = int(datetime.now(UTC).timestamp())
    zero = "0x" + "00" * 32
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
                "supply": {"per_request": "0", "daily": "0"},
            },
            "status": 0,
            "used_today": {"PAY": "0", "REFILL": "0"},
            "approvers": {APPROVER.address.lower(): True},
        },
        "balances": {world.safe_t: "100000", world.op: str(wallet_balance)},
        "buffers": {world.safe_t: "0", world.op: "10"},
        "targets": {world.safe_t: "0", world.op: "150"},
        "payees": {world.payee: {"state": 2, "active_from": now - 2 * 86_400}},
        "requests": {
            "0x" + world.request_hash.hex(): {
                "paid": False,
                "cancelled": False,
                "exception": {
                    "amount": "0", "expiry": 0, "mandate_version": 0, "payee": world.payee,
                    "used": False,
                },
                "refilled": {world.op: False},
            }
        },
        "fingerprints": {"0x" + world.fingerprint.hex(): {"paid": False, "allowed_for": zero}},
    }  # fmt: skip
    return Snapshot(
        purpose=SnapshotPurpose.PLAN,
        block_number=100,
        block_hash="0x" + "ab" * 32,
        # Taken after plan_request fixed its clock, so stamp it in the past: a second-boundary
        # crossing would otherwise make the snapshot "from the future" (SNAPSHOT_STALE).
        block_timestamp=datetime.now(UTC) - timedelta(seconds=5),
        provider="fake",
        data=data,
        coverage="COMPLETE",
        missing=(),
    )


def _deps(
    pool: Any,
    database_url: str,
    world: World,
    ai: Any = None,
    snapshot: Snapshot | None = None,
    gas_swap: GasSwapDeps | None = None,
) -> PlannerDeps:
    async def take(treasury_id: uuid.UUID, scope: SnapshotScope) -> tuple[Snapshot, int]:
        taken = snapshot or _chain(world)
        async with pool.acquire() as c:
            from treasurypilot_worker.chain.snapshot import store_snapshot

            await store_snapshot(c, world.org, treasury_id, taken)
        return taken, taken.block_number

    async def fee(_treasury: uuid.UUID, plan: ExecutionPlan) -> int:
        return 1_000 * len(plan.steps)

    async def issue(
        plan_id: uuid.UUID, plan: Any, decision: Decision, digest: str, now: datetime
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
        )

    return PlannerDeps(take, EXECUTOR, fee, issue, ai, gas_swap)


async def _cycle(pool: Any, world: World) -> tuple[Any, list[uuid.UUID]]:
    claimed: list[uuid.UUID] = []
    result = await run_execution_cycle(
        world.treasury,
        lock_for=lambda item: treasury_advisory_xact_lock(pool, item),
        schedule_provider=DbScheduleProvider(),
        plan_starter=DbPlanStarter(lambda plan_id, _treasury_id: claimed.append(plan_id)),
    )
    return result, claimed


async def _plan(pool: Any, database_url: str, world: World, **kwargs: Any) -> Any:
    result, claimed = await _cycle(pool, world)
    assert result.started and result.request_id == world.request
    (plan_id,) = claimed
    outcome = await plan_request(pool, plan_id, _deps(pool, database_url, world, **kwargs))
    assert outcome is not None
    return outcome


async def _reviews(pool: Any, world: World) -> list[tuple[str, str]]:
    rows = await pool.fetch(
        "SELECT type, primary_code FROM review_items WHERE request_id = $1 ORDER BY type",
        world.request,
    )
    return [(r["type"], r["primary_code"]) for r in rows]


@pooled
async def test_ai_disabled_produces_a_valid_deterministic_plan(
    pool: Any, database_url: str
) -> None:
    world = await _seed(pool)
    outcome = await _plan(pool, database_url, world)

    assert (outcome.status, outcome.planner_source) == ("Attested", "DETERMINISTIC")
    plan = await pool.fetchrow("SELECT * FROM plans WHERE id = $1", outcome.plan_id)
    assert plan["chosen_reason"] and plan["plan_hash"] and plan["attestation_id"]
    assert plan["fee_estimate_wei"] > 0
    assert plan["fee_estimate_wei"] == 2_000  # REFILL (balance 100 < 1000 + buffer) then PAY
    steps = await pool.fetch(
        "SELECT seq, action, amount FROM plan_steps WHERE plan_id = $1 ORDER BY seq",
        outcome.plan_id,
    )
    assert [(s["seq"], s["action"]) for s in steps] == [(0, 2), (1, 1)]  # REFILL, PAY
    assert steps[0]["amount"] >= 910 and steps[1]["amount"] == 1_000
    validation = await pool.fetchrow("SELECT decision, stage FROM validations WHERE plan_id = $1",
                                     outcome.plan_id)  # fmt: skip
    assert (validation["decision"], validation["stage"]) == ("ALLOW", "PLAN")
    assert (
        await pool.fetchval("SELECT status FROM payment_requests WHERE id = $1", world.request)
        == "Preparing"
    )
    assert await _reviews(pool, world) == []

    # The request is claimed: the next cycle finds nothing to start.
    again, claimed = await _cycle(pool, world)
    assert not again.started and not claimed
    assert again.reason is CycleSkipReason.NO_ELIGIBLE_REQUEST


@pooled
async def test_ai_timeout_falls_back_to_rule_based(pool: Any, database_url: str) -> None:
    world = await _seed(pool, terms={"net_due_day": 30_000, "priority_note": "critical vendor"})

    def timeout(_request: dict[str, Any]) -> dict[str, Any]:
        raise TimeoutError

    outcome = await _plan(pool, database_url, world, ai=CeleryAiProposer(timeout))

    assert (outcome.status, outcome.planner_source) == ("Attested", "RULE_BASED")
    row = await pool.fetchrow("SELECT planner_source, chosen_reason FROM plans WHERE id = $1",
                              outcome.plan_id)  # fmt: skip
    assert row["planner_source"] == "RULE_BASED" and "AiTimeout" in row["chosen_reason"]
    assert await _reviews(pool, world) == []


@pooled
async def test_rejected_ai_proposal_keeps_the_deterministic_plan_and_opens_one_review(
    pool: Any, database_url: str
) -> None:
    world = await _seed(pool, terms={"net_due_day": 30_000, "priority_note": "critical vendor"})

    class Rejecting:
        async def propose(self, **_: Any) -> AiOutcome:
            return AiOutcome(PlanProposalRejected("unknown request ids"), uuid.uuid4())

    outcome = await _plan(pool, database_url, world, ai=Rejecting())

    assert (outcome.status, outcome.planner_source) == ("Attested", "DETERMINISTIC")
    assert await _reviews(pool, world) == [("AI_REJECTED", "AI_PLAN_REJECTED")]
    assert (
        len(await pool.fetchval("SELECT ai_call_ids FROM plans WHERE id = $1", outcome.plan_id))
        == 1
    )


@pooled
async def test_unacknowledged_high_flag_blocks_with_a_policy_review(
    pool: Any, database_url: str
) -> None:
    world = await _seed(pool, flag=True)
    outcome = await _plan(pool, database_url, world)

    assert outcome.status == "Blocked"
    assert await _reviews(pool, world) == [("POLICY_BLOCK", "FLAG_UNACKNOWLEDGED")]
    status = await pool.fetchval("SELECT status FROM payment_requests WHERE id = $1", world.request)
    assert status == "NeedsReview"
    assert (
        await pool.fetchval("SELECT count(*) FROM attestations WHERE plan_id = $1", outcome.plan_id)
        == 0
    )


@pooled
async def test_needs_approval_creates_exactly_one_review_item(pool: Any, database_url: str) -> None:
    world = await _seed(pool, amount=9_000)
    outcome = await _plan(pool, database_url, world)

    assert outcome.status == "AwaitingAuthority" and outcome.planner_source is None
    assert [kind for kind, _ in await _reviews(pool, world)] == ["NEEDS_AUTHORITY"]


@pooled
async def test_fee_above_the_accepted_threshold_waits_for_acceptance(
    pool: Any, database_url: str
) -> None:
    world = await _seed(pool, fee_threshold=1, due_offset=-1)
    outcome = await _plan(pool, database_url, world)

    assert outcome.status == "AwaitingFeeAcceptance"
    item = await pool.fetchrow(
        "SELECT type, plan_id, fee_estimate_wei FROM review_items WHERE request_id = $1",
        world.request,
    )
    assert (item["type"], item["plan_id"], item["fee_estimate_wei"]) == (
        "FEE_APPROVAL",
        outcome.plan_id,
        2_000,
    )


@pooled
async def test_a_claimed_plan_is_planned_once(pool: Any, database_url: str) -> None:
    world = await _seed(pool)
    result, claimed = await _cycle(pool, world)
    (plan_id,) = claimed
    deps = _deps(pool, database_url, world)
    first = await plan_request(pool, plan_id, deps)
    assert first is not None and first.status == "Attested"
    assert await plan_request(pool, plan_id, deps) is None  # redelivery: no second attestation
    assert await pool.fetchval("SELECT count(*) FROM attestations WHERE plan_id = $1", plan_id) == 1


@pooled
async def test_fee_over_threshold_with_time_left_defers_without_a_review(
    pool: Any, database_url: str
) -> None:
    world = await _seed(pool, fee_threshold=1)  # deadline is tomorrow: wait for a cheaper block
    outcome = await _plan(pool, database_url, world)

    assert outcome.status == "Superseded"
    assert await _reviews(pool, world) == []
    # The cooldown stops the next 60 s cycle from planning (and calling the LLM) again at once.
    again, claimed = await _cycle(pool, world)
    assert not again.started and not claimed


@pooled
async def test_finish_writes_a_verifiable_audit_record(pool: Any, database_url: str) -> None:
    world = await _seed(pool)
    outcome = await _plan(pool, database_url, world)

    rows = await pool.fetch("SELECT * FROM audit_log WHERE org_id = $1 ORDER BY seq", world.org)
    assert [(r["action"], r["entity_id"]) for r in rows] == [
        ("plan.finished", str(outcome.plan_id))
    ]
    data = json.loads(rows[0]["data"])
    assert data["status"] == "Attested" and data["plan_hash"] and data["reason_codes"] is not None
    head = await pool.fetchrow("SELECT * FROM audit_heads WHERE org_id = $1", world.org)
    records = [
        DumpRecord(
            seq=r["seq"],
            org_id=r["org_id"],
            at=r["at"],
            actor_type=r["actor_type"],
            actor_id=r["actor_id"],
            action=r["action"],
            entity_type=r["entity_type"],
            entity_id=r["entity_id"],
            data=json.loads(r["data"]),
            prev_hash=bytes(r["prev_hash"]),
            hash=bytes(r["hash"]),
        )
        for r in rows
    ]
    # The API's verifier accepts what the worker wrote, including the stored head.
    assert verify_chain(records, SimpleNamespace(**dict(head))).status == "INTACT"


@pooled
async def test_finishing_a_plan_twice_keeps_one_attestation(pool: Any, database_url: str) -> None:
    world = await _seed(pool)
    first = await _plan(pool, database_url, world)
    assert first.status == "Attested"
    # A crash after the attestation committed but before the plan write: the plan is still Draft.
    await pool.execute(
        "UPDATE plans SET status = 'Draft', attestation_id = NULL WHERE id = $1", first.plan_id
    )
    again = await plan_request(pool, first.plan_id, _deps(pool, database_url, world))

    assert again is not None and again.status == "Attested"
    assert (
        await pool.fetchval("SELECT count(*) FROM attestations WHERE plan_id = $1", first.plan_id)
        == 1
    )
    assert (
        await pool.fetchval("SELECT attestation_id FROM plans WHERE id = $1", first.plan_id)
        is not None
    )


@pooled
async def test_attested_fees_stop_counting_the_next_day(pool: Any, database_url: str) -> None:
    world = await _seed(pool)
    outcome = await _plan(pool, database_url, world)  # fee 2_000, still Attested
    await pool.execute(
        "UPDATE treasury_fee_policies SET per_plan_threshold_wei = $2, daily_budget_wei = $3 "
        "WHERE treasury_id = $1",
        world.treasury,
        10**18,
        10_000,
    )
    now = datetime.now(UTC)

    async def assess() -> FeeDecision:
        async with pool.acquire() as connection:
            decision, _ = await _fee_assessment(
                connection, world.treasury, 9_000, int((now + timedelta(days=2)).timestamp()), now
            )
        return decision

    assert await assess() is not FeeDecision.PROCEED  # 2_000 in flight + 9_000 > 10_000
    await pool.execute(
        "UPDATE plans SET updated_at = now() - interval '2 days' WHERE id = $1", outcome.plan_id
    )
    assert await assess() is FeeDecision.PROCEED


@pooled
async def test_a_plan_waiting_on_a_fee_policy_is_reclaimed_after_acceptance(
    pool: Any, database_url: str
) -> None:
    world = await _seed(pool, fee_threshold=1, due_offset=-1)
    waiting = await _plan(pool, database_url, world)
    assert waiting.status == "AwaitingFeeAcceptance"
    stuck, _ = await _cycle(pool, world)
    assert not stuck.started  # the open plan holds the request

    await pool.execute(
        "UPDATE plans SET created_at = now() - interval '1 hour' WHERE id = $1", waiting.plan_id
    )
    await pool.execute(
        "UPDATE treasury_fee_policies SET per_plan_threshold_wei = $2, accepted_at = now() "
        "WHERE treasury_id = $1",
        world.treasury,
        10**18,
    )
    result, claimed = await _cycle(pool, world)

    assert result.started and len(claimed) == 1 and claimed[0] != waiting.plan_id
    assert (
        await pool.fetchval("SELECT status FROM plans WHERE id = $1", waiting.plan_id) == "Expired"
    )


@pooled
async def test_unavailable_inputs_expire_the_plan(pool: Any, database_url: str) -> None:
    world = await _seed(pool)
    _, claimed = await _cycle(pool, world)
    (plan_id,) = claimed
    await pool.execute(
        "UPDATE payment_requests SET onchain_request_id = NULL WHERE id = $1", world.request
    )

    outcome = await plan_request(pool, plan_id, _deps(pool, database_url, world))

    assert outcome is not None and outcome.status == "Expired"
    assert await pool.fetchval("SELECT status FROM plans WHERE id = $1", plan_id) == "Expired"


@pooled
async def test_reattest_renews_the_attestation_for_the_same_plan(
    pool: Any, database_url: str
) -> None:
    from treasurypilot_core.policy import Decision as PolicyDecision
    from treasurypilot_worker.executor.plan_loader import load_plan
    from treasurypilot_worker.planner import reattest as module
    from treasurypilot_worker.planner.context import load_inputs

    world = await _seed(pool)
    outcome = await _plan(pool, database_url, world)
    loaded = await load_plan(pool, outcome.plan_id)
    assert loaded is not None
    inputs = await load_inputs(pool, loaded.plan, world.treasury, executor=EXECUTOR)

    async def fresh(*_: Any) -> Snapshot:
        return _chain(world)

    class Rpc:
        async def call(self, _method: str, _params: list[Any]) -> str:
            return hex(100)

    original, module.take_snapshot = module.take_snapshot, fresh
    renew = module.reattest_fn(
        pool,
        loaded,
        inputs,
        rpc=Rpc(),  # type: ignore[arg-type]
        attest=_deps(pool, database_url, world).attest,
        fees={"feeCapWei": 1},
    )
    try:
        run = await renew(0)
    finally:
        module.take_snapshot = original

    assert not isinstance(run, PolicyDecision)
    assert run.plan_id == outcome.plan_id and len(run.steps) == len(loaded.plan.steps)
    assert run.valid_until >= loaded.valid_until
    assert (
        await pool.fetchval("SELECT count(*) FROM attestations WHERE plan_id = $1", outcome.plan_id)
        == 2
    )


ROUTER = "0x" + "99" * 20


def _gas_swap(balance: int, quote: GasQuote | None) -> GasSwapDeps:
    async def native_balance(_treasury: uuid.UUID) -> int:
        return balance

    async def get_quote(_treasury: uuid.UUID, _module: str) -> GasQuote | None:
        return quote

    return GasSwapDeps(native_balance, get_quote, slippage_bps=100, max_amount_in=10**9)


_QUOTE = GasQuote(router=ROUTER, token_out="0x" + "88" * 20, numerator=1, denominator=1)


@pooled
async def test_a_gas_shortage_adds_a_test_router_swap_that_is_persisted_and_encoded(
    pool: Any, database_url: str
) -> None:
    from treasurypilot_worker.executor.plan_loader import load_plan, plan_run
    from treasurypilot_worker.planner.context import load_inputs

    world = await _seed(pool)
    result, claimed = await _cycle(pool, world)
    (plan_id,) = claimed
    deps = _deps(pool, database_url, world, gas_swap=_gas_swap(500, _QUOTE))
    outcome = await plan_request(pool, plan_id, deps)

    assert outcome is not None and outcome.status == "Attested"
    rows = await pool.fetch(
        "SELECT seq, action, amount, min_out, venue, to_address FROM plan_steps "
        "WHERE plan_id = $1 ORDER BY seq",
        plan_id,
    )
    assert [r["action"] for r in rows][0] == SWAP_IN and len(rows) == 3  # SWAP, REFILL, PAY
    swap = rows[0]
    assert swap["venue"] == "TEST_ROUTER" and bytes(swap["to_address"]) == bytes.fromhex(ROUTER[2:])
    # Shortfall = 2 base steps x 1000 - 500 = 1500, at 1% slippage: minOut covers it.
    assert int(swap["min_out"]) >= 1_500 and int(swap["amount"]) < 1_600
    assert all(r["min_out"] is None and r["venue"] is None for r in rows[1:])

    loaded = await load_plan(pool, plan_id)
    assert loaded is not None and loaded.plan.steps[0].venue == "TEST_ROUTER"
    inputs = await load_inputs(pool, loaded.plan, world.treasury, executor=EXECUTOR)
    run = plan_run(loaded, inputs, {"feeCapWei": 1})
    request = run.steps[0].sign_request
    data = bytes.fromhex(request["payload"]["data"][2:])
    assert run.steps[0].kind == "SWAP"
    assert data[:4] == keccak(b"swapForGas(bytes32,uint256,uint256)")[:4]
    assert request["plan"]["swaps"]["0x" + loaded.plan.steps[0].step_id.hex()] == {
        "minOut": int(swap["min_out"]),
        "venue": "TEST_ROUTER",
    }


@pooled
async def test_no_swap_without_a_gas_shortage(pool: Any, database_url: str) -> None:
    world = await _seed(pool)
    result, claimed = await _cycle(pool, world)
    (plan_id,) = claimed

    outcome = await plan_request(
        pool, plan_id, _deps(pool, database_url, world, gas_swap=_gas_swap(10**18, _QUOTE))
    )

    assert outcome is not None and outcome.status == "Attested"
    assert await pool.fetchval("SELECT count(*) FROM plan_steps WHERE plan_id = $1", plan_id) == 2


@pooled
async def test_a_gas_shortage_without_a_quote_source_is_not_attested(
    pool: Any, database_url: str
) -> None:
    world = await _seed(pool)
    result, claimed = await _cycle(pool, world)
    (plan_id,) = claimed

    outcome = await plan_request(
        pool, plan_id, _deps(pool, database_url, world, gas_swap=_gas_swap(0, None))
    )

    assert outcome is not None and outcome.status == "Blocked"
    assert await _reviews(pool, world) == [("INFRA", "GAS_SHORTAGE_UNCOVERED")]
    assert await pool.fetchval("SELECT count(*) FROM attestations WHERE plan_id = $1", plan_id) == 0


@pooled
async def test_unknown_operation_skips_the_cycle_with_a_reason(
    pool: Any, database_url: str
) -> None:
    world = await _seed(pool)
    await pool.execute(
        "INSERT INTO operations (id, treasury_id, plan_step_id, request_id, step_id, kind, "
        "payload, idempotency_key, status) VALUES ($1, $2, gen_random_uuid(), $3, $4, 'PAY', "
        "'{}'::jsonb, $5, 'Unknown')",
        uuid.uuid4(),
        world.treasury,
        world.request,
        uuid.uuid4().bytes * 2,
        uuid.uuid4().hex,
    )

    result, claimed = await _cycle(pool, world)

    assert not result.started and result.reason is CycleSkipReason.UNKNOWN_OPERATION_PENDING
    assert claimed == []


@pooled
async def test_provider_consumes_the_schedule_and_schedules_the_request(
    pool: Any, database_url: str
) -> None:
    world = await _seed(pool)
    result, claimed = await _cycle(pool, world)  # no schedule row yet: the provider refreshes it

    assert result.started and result.request_id == world.request and len(claimed) == 1
    assert (
        await pool.fetchval("SELECT count(*) FROM schedules WHERE treasury_id = $1", world.treasury)
        == 1
    )
    assert (
        await pool.fetchval("SELECT status FROM payment_requests WHERE id = $1", world.request)
        == "Scheduled"
    )
    assert (
        await pool.fetchval(
            'SELECT count(*) FROM request_status_events WHERE request_id = $1 AND "from" = '
            "'Approved' AND \"to\" = 'Scheduled' AND actor_type = 'SYSTEM'",
            world.request,
        )
        == 1
    )


async def _sibling(
    pool: Any,
    world: World,
    *,
    due_offset: int,
    status: str = "Approved",
    discount_offset: int | None = None,
) -> uuid.UUID:
    """Another Approved request of the seeded treasury (same payee/wallet/approval), own due date."""
    new = uuid.uuid4()
    due = datetime.now(UTC).date() + timedelta(days=due_offset)
    day = (due - datetime(1970, 1, 1).date()).days
    terms_dict: dict[str, int] = {"net_due_day": day}
    if discount_offset is not None:  # pay-by is the earlier discount deadline
        terms_dict |= {"discount_bps": 100, "discount_deadline_day": day + discount_offset}
    terms = json.dumps(terms_dict)
    async with pool.acquire() as c, c.transaction():
        await c.execute(
            "INSERT INTO payment_requests (id, org_id, treasury_id, chain_id, vendor_id, payee_id,"
            " asset_id, issue_date, due_at, invoice_no, amount, status, fingerprint, invoice_hash,"
            " terms_hash, onchain_request_id, paying_wallet_id, terms, terms_confirmed_by,"
            " terms_confirmed_at, created_by, last_edited_by) SELECT $1, org_id, treasury_id,"
            " chain_id, vendor_id, payee_id, asset_id, issue_date, $2, 'INV-' || $6::text, amount,"
            " $3, sha256(('f' || $6::text)::bytea), invoice_hash, terms_hash,"
            " sha256(('r' || $6::text)::bytea),"
            " paying_wallet_id, $4::jsonb, terms_confirmed_by, terms_confirmed_at, created_by,"
            " last_edited_by FROM payment_requests WHERE id = $5",
            new,
            due,
            status,
            terms,
            world.request,
            str(new),
        )
        await c.execute(
            "INSERT INTO request_revisions (id, request_id, revision, snapshot) "
            "VALUES (gen_random_uuid(), $1, 1, '{}')",
            new,
        )
        await c.execute(
            "INSERT INTO approvals (id, request_id, revision, approver_user_id, approver_address,"
            " typed_data, signature, expires_at) SELECT gen_random_uuid(), $1, revision,"
            " approver_user_id, approver_address, typed_data, signature, expires_at"
            " FROM approvals WHERE request_id = $2",
            new,
            world.request,
        )
    return new


async def _provider_pick(
    pool: Any, world: World, now: datetime, lead: timedelta = timedelta(hours=24)
) -> Any:
    async with pool.acquire() as connection:
        return await DbScheduleProvider(lead).next_eligible_request(
            connection, world.treasury, now=now
        )


@pooled
async def test_provider_skips_items_that_are_no_longer_live_candidates(
    pool: Any, database_url: str
) -> None:
    world = await _seed(pool)  # due tomorrow, window open
    cooling = await _sibling(pool, world, due_offset=0)  # earlier deadline, so first in the row
    await pool.execute(
        "INSERT INTO plans (id, org_id, treasury_id, request_id, status) "
        "SELECT gen_random_uuid(), org_id, id, $1, 'Expired' FROM treasuries WHERE id = $2",
        cooling,
        world.treasury,
    )

    selection = await _provider_pick(pool, world, datetime.now(UTC))

    stored = await pool.fetchval(
        "SELECT items FROM schedules WHERE treasury_id = $1 ORDER BY computed_at DESC LIMIT 1",
        world.treasury,
    )
    assert [i["requestId"] for i in json.loads(stored)] == [str(cooling), str(world.request)]
    assert selection.candidate is not None and selection.candidate.request_id == world.request
    assert selection.candidate.order == 1  # position in the stored schedule, not in the live set


@pooled
async def test_provider_takes_the_open_second_item_when_the_first_is_closed(
    pool: Any, database_url: str
) -> None:
    world = await _seed(pool, due_offset=2)  # first by due date; window opens tomorrow
    # Due later but with a discount deadline tomorrow: pay-by tomorrow, window open today.
    second = await _sibling(pool, world, due_offset=3, discount_offset=-2)

    selection = await _provider_pick(pool, world, datetime.now(UTC))

    assert selection.candidate is not None and selection.candidate.request_id == second
    assert selection.candidate.order == 1


@pooled
async def test_writer_schedules_only_open_windows_and_is_idempotent(
    pool: Any, database_url: str
) -> None:
    world = await _seed(pool)  # window open
    far = await _sibling(pool, world, due_offset=10)
    draft = await _sibling(pool, world, due_offset=1, status="Draft")
    writer = DbScheduleWriter()
    async with pool.acquire() as connection:
        await writer.refresh_treasury(connection, world.treasury, now=datetime.now(UTC))
        await writer.refresh_treasury(connection, world.treasury, now=datetime.now(UTC))

    async def state(rid: uuid.UUID) -> tuple[str, int, int]:
        row = await pool.fetchrow(
            "SELECT status, version, (SELECT count(*) FROM request_status_events "
            "WHERE request_id = $1) AS events FROM payment_requests WHERE id = $1",
            rid,
        )
        return row["status"], row["version"], row["events"]

    opened = await state(world.request)
    assert opened[0] == "Scheduled" and opened[2] == 1  # one event despite the rerun
    assert await state(far) == ("Approved", 1, 0)  # outside its window: still editable
    assert await state(draft) == ("Draft", 1, 0)


@pooled
async def test_two_simultaneous_cycles_run_one(pool: Any, database_url: str) -> None:
    world = await _seed(pool)
    entered, release = asyncio.Event(), asyncio.Event()
    inner = DbScheduleProvider()

    class Slow:
        async def next_eligible_request(
            self, connection: Any, treasury_id: Any, *, now: Any
        ) -> Any:
            entered.set()
            await release.wait()
            return await inner.next_eligible_request(connection, treasury_id, now=now)

    claimed: list[uuid.UUID] = []

    async def run(provider: Any) -> Any:
        return await run_execution_cycle(
            world.treasury,
            lock_for=lambda item: treasury_advisory_xact_lock(pool, item),
            schedule_provider=provider,
            plan_starter=DbPlanStarter(lambda plan_id, _t: claimed.append(plan_id)),
        )

    first = asyncio.create_task(run(Slow()))
    await entered.wait()
    second = await run(inner)
    release.set()
    first_result = await first

    assert second.reason is CycleSkipReason.LOCK_BUSY and not second.started
    assert first_result.started and len(claimed) == 1


@pooled
async def test_paused_treasury_is_skipped_with_a_reason(pool: Any, database_url: str) -> None:
    world = await _seed(pool)
    await pool.execute(
        "INSERT INTO backend_pause (treasury_id, org_id, paused, reason) "
        "VALUES ($1, $2, true, 'incident')",
        world.treasury,
        world.org,
    )

    result, claimed = await _cycle(pool, world)

    assert not result.started and result.reason is CycleSkipReason.BACKEND_PAUSED
    assert claimed == []


@pooled
async def test_approval_event_chain_and_latency_budget_stay_under_five_seconds(
    pool: Any, database_url: str
) -> None:
    world = await _seed(pool)
    # The API appends this row in the approval transaction (invoices/requests.py).
    approved_at = time.monotonic()
    event_id = uuid.uuid4()
    await pool.execute(
        "INSERT INTO domain_events (id, org_id, treasury_id, type, entity_type, entity_id, "
        "payload) VALUES ($1, $2, $3, 'ExecutionCycleRequested', 'payment_request', $4, "
        "'{}'::jsonb)",
        event_id,
        world.org,
        world.treasury,
        world.request,
    )
    dispatched: list[uuid.UUID] = []

    def dispatch(event: uuid.UUID, treasury: uuid.UUID) -> None:
        if treasury == world.treasury:
            dispatched.append(event)

    async with pool.acquire() as connection:
        await publish_pending_events(connection, dispatch_execution_cycle=dispatch)
    assert dispatched == [event_id]
    result, claimed = await _cycle(pool, world)  # what run_treasury_cycle_task does

    publisher = celery_app.conf.beat_schedule["publish-domain-events"]
    # Budgeted estimate (no live broker): next publisher tick + measured cycle + the plan
    # enqueue countdown + an assumed worker pickup allowance.
    worst_case = (
        publisher["schedule"].total_seconds()
        + (time.monotonic() - approved_at)
        + PLAN_ENQUEUE_COUNTDOWN_SECONDS
        + PICKUP_BUDGET_SECONDS
    )
    assert result.started and result.request_id == world.request and len(claimed) == 1
    assert worst_case < 5


@pooled
async def test_payee_activation_enqueues_an_execution_cycle(pool: Any, database_url: str) -> None:
    world = await _seed(pool)
    address = bytes.fromhex(world.payee.removeprefix("0x"))
    await pool.execute(
        "UPDATE payees SET status = 'Cooling', active_from = now() - interval '1 second' "
        "WHERE treasury_id = $1",
        world.treasury,
    )
    await pool.execute(
        "INSERT INTO observed_events (id, treasury_id, chain_id, stream, block_number, "
        "block_hash, tx_hash, log_index, address, event_name, payload) VALUES ($1, $2, $3, "
        "'MODULE', 1, decode(repeat('01', 32), 'hex'), $4, 0, $5, 'PayeeAdded', $6::jsonb)",
        uuid.uuid4(),
        world.treasury,
        CHAIN_ID,
        uuid.uuid4().bytes * 2,
        address,
        json.dumps({"payee": world.payee}),
    )

    await activate_due_payees(pool)

    assert (
        await pool.fetchval(
            "SELECT count(*) FROM domain_events WHERE treasury_id = $1 "
            "AND type = 'ExecutionCycleRequested' AND entity_type = 'payee'",
            world.treasury,
        )
        == 1
    )


@pooled
async def test_scheduling_cycle_writes_the_advisory_schedule(pool: Any, database_url: str) -> None:
    world = await _seed(pool)
    lead = timedelta(hours=24)

    async def run() -> Any:
        return await run_scheduling_cycle(
            world.treasury,
            lock_for=lambda item: treasury_advisory_xact_lock(pool, item),
            schedule_writer=DbScheduleWriter(lead),
        )

    assert (await run()).started
    assert (await run()).started  # unchanged schedule: no duplicate row
    rows = await pool.fetch(
        "SELECT solver, items FROM schedules WHERE treasury_id = $1", world.treasury
    )
    assert len(rows) == 1 and rows[0]["solver"] == "DUE_DATE"
    (item,) = json.loads(rows[0]["items"])
    deadline = datetime.fromisoformat(item["deadline"])
    assert item["requestId"] == str(world.request) and item["order"] == 0
    assert datetime.fromisoformat(item["scheduledFor"]) == deadline - lead
    assert deadline.date() == datetime.now(UTC).date() + timedelta(days=1)


@pooled
async def test_changed_schedule_appends_and_empty_is_not_stored(
    pool: Any, database_url: str
) -> None:
    world = await _seed(pool)
    writer = DbScheduleWriter(timedelta(hours=24))
    now = datetime.now(UTC)
    count = "SELECT count(*) FROM schedules WHERE treasury_id = $1"
    async with pool.acquire() as connection:
        await writer.refresh_treasury(connection, world.treasury, now=now)
        await pool.execute(
            "UPDATE payment_requests SET status = 'Cancelled' WHERE id = $1", world.request
        )
        await writer.refresh_treasury(connection, world.treasury, now=now + timedelta(minutes=15))
        await writer.refresh_treasury(connection, world.treasury, now=now + timedelta(minutes=30))
    rows = await pool.fetch(
        "SELECT items FROM schedules WHERE treasury_id = $1 ORDER BY computed_at", world.treasury
    )
    assert [len(json.loads(r["items"])) for r in rows] == [1, 0]  # change appended, repeat not
    assert await pool.fetchval(count, world.treasury) == 2


@pooled
async def test_untracked_treasury_status_is_skipped_and_old_rows_pruned(
    pool: Any, database_url: str
) -> None:
    world = await _seed(pool)
    writer = DbScheduleWriter(timedelta(hours=24))
    now = datetime.now(UTC)
    count = "SELECT count(*) FROM schedules WHERE treasury_id = $1"
    await pool.execute(
        "INSERT INTO schedules (id, org_id, treasury_id, computed_at, solver, items) "
        "VALUES ($1, $2, $3, $4, 'DUE_DATE', '[]'::jsonb)",
        uuid.uuid4(),
        world.org,
        world.treasury,
        now - timedelta(days=31),
    )
    async with pool.acquire() as connection:
        await pool.execute("UPDATE treasuries SET status = 'Revoked' WHERE id = $1", world.treasury)
        assert not await writer.refresh_treasury(connection, world.treasury, now=now)
        assert await pool.fetchval(count, world.treasury) == 1
        await pool.execute("UPDATE treasuries SET status = 'Ready' WHERE id = $1", world.treasury)
        assert await writer.refresh_treasury(connection, world.treasury, now=now)
    assert await pool.fetchval(count, world.treasury) == 1  # old pruned, new added
