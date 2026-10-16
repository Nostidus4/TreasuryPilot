"""The liquidity cycle (EXE-014, FR-519): at most one SUPPLY or WITHDRAW plan per cycle.

``DbLiquidityStarter`` claims a Draft liquidity plan under the treasury lock (after the request
plans, while none is in flight); ``plan_liquidity`` decides with ``decide_liquidity``, validates
and attests it like a request plan (same validator, attestation and fee check), and the executor
sequences it like any other plan. A liquidity plan serves no request: its ``plans.request_id`` is
NULL, its requestId is 0x0 and its stepIds are keyed by the liquidity cycle id (M08 8.4).

A plan that needs a fee decision waits as ``AwaitingFeeAcceptance`` with a ``FEE_APPROVAL`` review
item keyed by plan (the Owner's ACCEPT_FEE caps that cycle's replan); a plan that is blocked by
policy or fee-deferred ends ``Superseded`` and is retried after ``REPLAN_COOLDOWN``. A stopped plan
or an unresolved operation opens an item too (``liquidity_review``).

A cycle that finds nothing to do deletes its empty Draft and records an idle marker on the
treasury (``liquidity_idle_key``); the next cycles skip the claim while the marker is younger than
``IDLE_COOLDOWN`` and the approved obligations and mandate are unchanged. A new approval or a new
day therefore plans at once (D3); only a chain-side change (an inflow) waits for the cooldown.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, time, timedelta

import asyncpg  # type: ignore[import-untyped]

from treasurypilot_core.domain import ApprovedRequest
from treasurypilot_core.domain.fee_policy import FeeDecision
from treasurypilot_core.domain.utc_days import utc_day_number
from treasurypilot_core.eip712 import SUPPLY, WITHDRAW, liquidity_cycle_id, plan_hash, step_id
from treasurypilot_core.engine.liquidity import decide_liquidity
from treasurypilot_core.ids import uuid7
from treasurypilot_core.money import BaseUnits
from treasurypilot_core.policy import Action, ExecutionPlan, PlanStep, validate_plan
from treasurypilot_worker.audit import append_audit
from treasurypilot_worker.chain.snapshot import Snapshot as ChainRead
from treasurypilot_worker.liquidity_review import open_liquidity_review
from treasurypilot_worker.planner.borrow import clear_borrow_proposal, record_borrow_proposal
from treasurypilot_worker.planner.context import build_context, load_liquidity_context, scope_for
from treasurypilot_worker.planner.inputs import (
    NO_SCHEDULE,
    InputsUnavailable,
    engine_snapshot,
    liquidity_policy,
)
from treasurypilot_worker.planner.pipeline import (
    PlannerDeps,
    PlanOutcome,
    _fee_assessment,
    evidence_digest,
    insert_plan_validation,
)
from treasurypilot_worker.planner.start import DRAFT_TIMEOUT, REPLAN_COOLDOWN

logger = logging.getLogger(__name__)

# An idle result is trusted this long while the DB-side inputs are unchanged.
IDLE_COOLDOWN = timedelta(minutes=5)
# A liquidity fee decision nobody took is stale after this: the surplus/deficit moved on.
FEE_HOLD_TIMEOUT = timedelta(hours=24)
_SUPPLY_PATIENCE_SECONDS = 365 * 86_400
_ZERO_REQUEST = b"\x00" * 32
_REQUEST_PLANS_IN_FLIGHT = (
    "SELECT EXISTS (SELECT 1 FROM plans WHERE treasury_id = $1 AND request_id IS NOT NULL "
    "AND status IN ('Draft', 'Attested', 'Executing'))"
)
_OPEN = "'Draft', 'Blocked', 'AwaitingAuthority', 'AwaitingFeeAcceptance', 'Attested', 'Executing'"


async def idle_key(connection: asyncpg.Connection, treasury_id: uuid.UUID, now: datetime) -> str:
    """Fingerprint of what the liquidity decision reads from the database.

    The unpaid approved requests (id and version), the active mandate version and the UTC day.
    The chain half (balances, pool) is not in it: that is what ``IDLE_COOLDOWN`` bounds.
    """

    digest = await connection.fetchval(
        "SELECT md5(coalesce((SELECT string_agg(id::text || ':' || version::text, ',' ORDER BY id) "
        "FROM payment_requests WHERE treasury_id = $1 AND status IN ('Approved', 'Scheduled')), "
        "'') || '|' || coalesce((SELECT max(version)::text FROM mandate_versions "
        "WHERE treasury_id = $1 AND status = 'Active'), ''))",
        treasury_id,
    )
    return f"{digest}|{utc_day_number(now)}"


class DbLiquidityStarter:
    """Claim a Draft liquidity plan (unique per treasury) and hand it to the planning task."""

    def __init__(self, enqueue: Callable[[uuid.UUID, uuid.UUID], None]) -> None:
        self.enqueue = enqueue

    async def start(
        self, connection: asyncpg.Connection, treasury_id: uuid.UUID, *, now: datetime
    ) -> uuid.UUID | None:
        # A request plan in flight owns Safe T's funds: liquidity moves wait for it (EXE-014).
        if await connection.fetchval(_REQUEST_PLANS_IN_FLIGHT, treasury_id):
            return None
        await connection.execute(
            "UPDATE plans SET status = 'Expired', updated_at = now() WHERE treasury_id = $1 "
            "AND request_id IS NULL AND status = 'Draft' AND created_at < $2",
            treasury_id,
            now - DRAFT_TIMEOUT,
        )
        if await connection.fetchval(
            "SELECT EXISTS (SELECT 1 FROM plans WHERE treasury_id = $1 AND request_id IS NULL "
            "AND status = 'Superseded' AND created_at > $2)",
            treasury_id,
            now - REPLAN_COOLDOWN,
        ):
            return None
        # A fee decision nobody took, or one already taken (the replan inherits the cap), is
        # stale: free the cycle and close its item.
        stale = await connection.fetch(
            "UPDATE plans SET status = 'Expired', updated_at = now() WHERE treasury_id = $1 "
            "AND request_id IS NULL AND status = 'AwaitingFeeAcceptance' AND ("
            "EXISTS (SELECT 1 FROM fee_acceptances a WHERE a.plan_id = plans.id) "
            "OR created_at < $2 OR EXISTS (SELECT 1 FROM treasury_fee_policies f "
            "WHERE f.treasury_id = plans.treasury_id AND f.accepted_at IS NOT NULL "
            "AND f.superseded_at IS NULL AND f.accepted_at > plans.created_at)) RETURNING id",
            treasury_id,
            now - FEE_HOLD_TIMEOUT,
        )
        if stale:
            await connection.execute(
                "UPDATE review_items SET status = 'Dismissed', resolution = 'EXPIRED', "
                "resolved_at = now(), version = version + 1 WHERE plan_id = ANY($1::uuid[]) "
                "AND request_id IS NULL AND type = 'FEE_APPROVAL' AND status = 'Open'",
                [row["id"] for row in stale],
            )
        module = await connection.fetchval(
            "SELECT module_address FROM treasuries WHERE id = $1", treasury_id
        )
        if module is None:
            return None
        key = await idle_key(connection, treasury_id, now)
        if await connection.fetchval(
            "SELECT liquidity_idle_key = $2 AND liquidity_idle_at > $3 FROM treasuries "
            "WHERE id = $1",
            treasury_id,
            key,
            now - IDLE_COOLDOWN,
        ):
            return None
        midnight = datetime.combine(now.date(), time.min, UTC)
        ended_today = await connection.fetchval(
            "SELECT count(*) FROM plans WHERE treasury_id = $1 AND request_id IS NULL "
            "AND status IN ('Completed', 'PartiallyCompleted') AND created_at >= $2",
            treasury_id,
            midnight,
        )
        cycle = liquidity_cycle_id("0x" + bytes(module).hex(), utc_day_number(now), ended_today)
        plan_id: uuid.UUID | None = await connection.fetchval(
            f"""
            INSERT INTO plans (id, org_id, treasury_id, request_id, liquidity_cycle_id)
            SELECT $1, org_id, id, NULL, $3 FROM treasuries WHERE id = $2
            ON CONFLICT (treasury_id) WHERE request_id IS NULL AND status IN ({_OPEN}) DO NOTHING
            RETURNING id
            """,
            uuid7(),
            treasury_id,
            cycle,
        )
        if plan_id is not None:
            self.enqueue(plan_id, treasury_id)
        return plan_id


def _step(
    key: bytes, action: int, kind: Action, source: str, safe_t: str, asset: str, amount: int
) -> PlanStep:
    return PlanStep(
        seq=0,
        step_id=step_id(key, action, safe_t),
        action=kind,
        from_wallet=source,
        to=safe_t,
        asset=asset,
        amount=BaseUnits(amount),
    )


async def _end(
    pool: asyncpg.Pool, plan_id: uuid.UUID, status: str, reason: str, *, delete: bool = False
) -> PlanOutcome:
    if delete:  # an idle cycle's Draft: nothing to record, so it is the one row ever deleted
        await pool.execute("DELETE FROM plans WHERE id = $1 AND status = 'Draft'", plan_id)
    else:
        await pool.execute(
            "UPDATE plans SET status = $2, chosen_reason = $3, updated_at = now() "
            "WHERE id = $1 AND status = 'Draft'",
            plan_id,
            status,
            reason,
        )
    return PlanOutcome(plan_id, status, None)


def _last_safe_execution(kind: str, requests: Sequence[ApprovedRequest], now: datetime) -> int:
    """When a fee above the policy can no longer wait for a cheaper moment (BR-084).

    A SUPPLY only earns yield, so it always waits (and never asks the Owner). A reserve-restoring
    WITHDRAW must land before the first unpaid obligation falls due: the end of that UTC day.
    """

    if kind == "SUPPLY" or not requests:
        return int(now.timestamp()) + _SUPPLY_PATIENCE_SECONDS
    return min(int(r.terms.net_due_day) for r in requests) * 86_400 + 86_399


async def plan_liquidity(
    pool: asyncpg.Pool, plan_id: uuid.UUID, deps: PlannerDeps, *, now: datetime | None = None
) -> PlanOutcome | None:
    """Decide, validate and attest the claimed Draft liquidity plan; the outcome is stored.

    ``None``: the plan is already past Draft (redelivered task). ``Expired``/``Superseded``: no
    action this cycle (nothing to do, inputs unavailable, or not attestable). ``LookupError``:
    the claim is not visible yet.
    """

    current = (now or datetime.now(UTC)).astimezone(UTC)
    row = await pool.fetchrow(
        "SELECT p.treasury_id, p.org_id, p.status, p.liquidity_cycle_id, t.module_address, "
        "t.chain_id FROM plans p JOIN treasuries t ON t.id = p.treasury_id "
        "WHERE p.id = $1 AND p.request_id IS NULL",
        plan_id,
    )
    if row is None:
        raise LookupError(f"liquidity plan {plan_id} not found")
    if row["status"] != "Draft":
        return None
    treasury_id, org_id = row["treasury_id"], row["org_id"]
    cycle = bytes(row["liquidity_cycle_id"])
    module = "0x" + bytes(row["module_address"]).hex()
    async with pool.acquire() as connection:
        key = await idle_key(connection, treasury_id, current)  # before the read: a change re-plans
    inputs = await load_liquidity_context(pool, treasury_id, executor=deps.executor)
    assert inputs.liquidity is not None
    empty = ExecutionPlan(
        request_id=_ZERO_REQUEST,
        treasury=module,
        chain_id=row["chain_id"],
        steps=[],
        planner_source="DETERMINISTIC",
        evidence_ids=[],
    )
    chain: ChainRead
    chain, head = await deps.take_snapshot(treasury_id, scope_for(empty, inputs))
    try:
        data = chain.data
        engine = engine_snapshot(
            data, inputs.safe_t, list(inputs.liquidity.operational), day=utc_day_number(current)
        )
        decision = decide_liquidity(
            engine,
            inputs.liquidity.requests,
            NO_SCHEDULE,
            liquidity_policy(data, inputs.liquidity.config),
        )
        a_token = str((data.get("aave") or {}).get("a_token", ""))
    except (InputsUnavailable, KeyError, TypeError, ValueError) as error:
        logger.warning("liquidity_inputs_unavailable", extra={"plan_id": str(plan_id)})
        return await _end(pool, plan_id, "Expired", f"inputs unavailable: {error!r}")
    async with pool.acquire() as connection:
        if decision.kind == "INSUFFICIENT_LIQUIDITY":
            # What withdrawing cannot cover is a borrow proposal for the owner (F-069).
            await record_borrow_proposal(
                connection, org_id, treasury_id, engine, decision.shortfall, snapshot_id=chain.id
            )
        else:
            await clear_borrow_proposal(connection, treasury_id)
    amount = int(decision.amount)
    if decision.kind == "NONE" or amount == 0:
        await pool.execute(
            "UPDATE treasuries SET liquidity_idle_at = $2, liquidity_idle_key = $3 WHERE id = $1",
            treasury_id,
            current,
            key,
        )
        return await _end(pool, plan_id, "Superseded", decision.reason, delete=True)

    if decision.kind == "SUPPLY":
        step = _step(
            cycle, SUPPLY, Action.SUPPLY, inputs.safe_t, inputs.safe_t, inputs.asset, amount
        )
    else:  # WITHDRAW, or the partial withdrawal of INSUFFICIENT_LIQUIDITY
        step = _step(cycle, WITHDRAW, Action.WITHDRAW, a_token, inputs.safe_t, inputs.asset, amount)
    plan = empty.model_copy(update={"steps": [step], "evidence_ids": [f"snapshot:{chain.id}"]})
    validation = validate_plan(
        plan, build_context(chain, plan, inputs, now=int(current.timestamp()), head_block=head)
    )
    status = "Superseded"
    reason = f"{decision.kind} {amount}: {decision.reason}"
    estimate: int | None = None
    fee_review: str | None = None
    if validation.decision == "ALLOW":
        estimate = await deps.estimate_fee(treasury_id, plan)
        async with pool.acquire() as connection:
            fee, fee_code = await _fee_assessment(
                connection,
                treasury_id,
                plan_id,
                estimate,
                _last_safe_execution(decision.kind, inputs.liquidity.requests, current),
                current,
            )
        if fee is FeeDecision.PROCEED:
            await deps.attest(
                plan_id,
                plan.message(),
                validation,
                evidence_digest(chain),
                current,
                liquidity_cycle_id="0x" + cycle.hex(),
            )
            status = "Attested"
        else:
            reason += f"; fee not accepted: {fee_code or fee.value}"
            if fee is FeeDecision.AWAITING_FEE_ACCEPTANCE:
                status = "AwaitingFeeAcceptance"
                fee_review = fee_code or "FEE_APPROVAL_REQUIRED"
    else:
        codes = ",".join(c.value for c in validation.codes)
        failed = ",".join(c.name for c in validation.checks if not c.passed)
        reason += f"; validation {validation.decision}: {codes} ({failed})"

    message = plan.message()
    digest = plan_hash(
        message["requestId"], message["treasury"], message["chainId"], message["steps"]
    )
    async with pool.acquire() as connection, connection.transaction():
        attestation_id = (
            await connection.fetchval("SELECT id FROM attestations WHERE plan_id = $1", plan_id)
            if status == "Attested"
            else None
        )
        await connection.execute(
            "UPDATE plans SET status = $2, planner_source = 'DETERMINISTIC', plan_hash = $3, "
            "chosen_reason = left($4, 500), snapshot_id = $5, attestation_id = $6, "
            "fee_estimate_wei = $7, updated_at = now() WHERE id = $1",
            plan_id,
            status,
            digest,
            reason,
            chain.id,
            attestation_id,
            estimate,
        )
        await insert_plan_validation(connection, plan_id, validation)
        if fee_review is not None and estimate is not None:
            await open_liquidity_review(
                connection,
                plan_id=plan_id,
                kind="FEE_APPROVAL",
                primary_code=fee_review,
                fee_estimate_wei=estimate,
                now=current,
            )
        await connection.execute(
            "UPDATE treasuries SET liquidity_idle_at = NULL, liquidity_idle_key = NULL "
            "WHERE id = $1",
            treasury_id,
        )
        await append_audit(
            connection,
            org_id,
            action="plan.finished",
            entity_type="plan",
            entity_id=str(plan_id),
            data={
                "status": status,
                "kind": "LIQUIDITY",
                "action": decision.kind,
                "amount": str(amount),
                "plan_hash": "0x" + digest.hex(),
                "reason_codes": [c.value for c in validation.codes],
            },
        )
    logger.info("liquidity_plan_finished", extra={"plan_id": str(plan_id), "status": status})
    return PlanOutcome(plan_id, status, "DETERMINISTIC")
