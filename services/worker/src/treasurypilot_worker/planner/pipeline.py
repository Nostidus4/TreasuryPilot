"""The planning pipeline (EXE-004, M10 §7.2): snapshot, engine, AI, select, validate, attest.

`plan_request` takes a claimed `Draft` plan to its final state. Everything slow (chain read, AI
call, fee estimate, signing) happens before the single transaction that records the outcome, so
a crash leaves a `Draft` that the starter expires and re-plans.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from typing import Protocol

import asyncpg  # type: ignore[import-untyped]
from web3 import Web3

from treasurypilot_core.domain import ApprovedRequest, Schedule, ScheduledItem
from treasurypilot_core.domain.fee_policy import FeeDecision, assess_fee
from treasurypilot_core.eip712 import plan_hash
from treasurypilot_core.engine import pay_amount, schedule_edf
from treasurypilot_core.ids import uuid7
from treasurypilot_core.policy import (
    Decision,
    ExecutionPlan,
    ValidationContext,
    validate_plan,
)
from treasurypilot_worker.agent.errors import AiError
from treasurypilot_worker.agent.fallback import FallbackPlan, plan_fallback
from treasurypilot_worker.agent.plan_proposer import (
    PlanProposal,
    PlanProposalRejected,
    needs_full_proposal,
)
from treasurypilot_worker.agent.plan_selection import select_plan
from treasurypilot_worker.audit import append_audit
from treasurypilot_worker.chain.snapshot import Snapshot as ChainRead
from treasurypilot_worker.chain.snapshot import SnapshotScope
from treasurypilot_worker.planner.context import ContextInputs, build_context, scope_for
from treasurypilot_worker.planner.context import load_inputs as load_context_inputs
from treasurypilot_worker.planner.gas import (
    GasSwapDeps,
    GasSwapInfeasible,
    GasSwapUnavailable,
    with_gas_swap,
)
from treasurypilot_worker.planner.inputs import (
    InputsUnavailable,
    PlanInputs,
    load_inputs,
    load_liquidity_inputs,
    plan_steps,
    probe_plan,
    reserve_withdrawal,
)
from treasurypilot_worker.recovery.retry import ReviewIntent

logger = logging.getLogger(__name__)

_OPEN_PLANS = "('Attested', 'Executing')"
_ROLES = {
    "POLICY_BLOCK": (("Owner",), 48),
    "NEEDS_AUTHORITY": (("Owner",), 24),
    "AI_REJECTED": (("Operator",), 48),
    "INFRA": (("Operator",), 48),
    "FEE_APPROVAL": (("Finance", "Operator", "Owner"), 0),
}


@dataclass(frozen=True)
class AiOutcome:
    """One AI attempt: a proposal, or the typed error that ended it."""

    result: PlanProposal | AiError
    ai_call_id: uuid.UUID | None = None


class AiProposer(Protocol):
    async def propose(
        self, *, org_id: uuid.UUID, treasury_id: uuid.UUID, eligible_ids: tuple[str, ...]
    ) -> AiOutcome: ...


@dataclass(frozen=True)
class PlannerDeps:
    # (treasury, scope) -> stored block-consistent snapshot and the head block number
    take_snapshot: Callable[[uuid.UUID, SnapshotScope], Awaitable[tuple[ChainRead, int]]]
    executor: str
    # ExecutionPlan -> estimated plan fee in integer wei
    estimate_fee: Callable[[uuid.UUID, ExecutionPlan], Awaitable[int]]
    # signs and stores the attestation (plan message, decision, evidence digest, now); a liquidity
    # plan also passes ``liquidity_cycle_id=`` (its stepId key)
    attest: Callable[..., Awaitable[None]]
    ai: AiProposer | None = None
    # Set where a configured test router can cover an executor gas shortage (F-064).
    gas_swap: GasSwapDeps | None = None


@dataclass(frozen=True)
class PlanOutcome:
    plan_id: uuid.UUID
    status: str
    planner_source: str | None
    reviews: tuple[str, ...] = ()


def evidence_digest(chain: ChainRead) -> str:
    """Digest of the snapshot a plan was validated against (the attestation's evidenceDigest)."""

    block_hash = bytes.fromhex(chain.block_hash.removeprefix("0x"))
    return "0x" + bytes(Web3.keccak(block_hash + chain.id.bytes)).hex()


def _build_plan(
    probe: ExecutionPlan,
    request: ApprovedRequest,
    item: ScheduledItem,
    source: str,
    snapshot_id: str,
    *,
    withdraw: int = 0,
    a_token: str = "",
) -> ExecutionPlan:
    pay = probe.steps[-1]
    return ExecutionPlan(
        request_id=probe.request_id,
        treasury=probe.treasury,
        chain_id=probe.chain_id,
        steps=plan_steps(
            probe.request_id,
            safe_t=probe.steps[0].from_wallet,  # the probe always carries both steps
            asset=pay.asset,
            wallet=pay.from_wallet,
            payee=pay.to,
            refill=int(item.refill),
            refill_from=item.refill_from,
            pay=int(pay_amount(request, item.day)),
            withdraw=withdraw,
            a_token=a_token,
        ),
        planner_source=source,  # type: ignore[arg-type]
        evidence_ids=[f"snapshot:{snapshot_id}"],
    )


async def insert_plan_validation(
    connection: asyncpg.Connection, plan_id: uuid.UUID, decision: Decision
) -> None:
    """Record the PLAN-stage validation of a plan (also used by the liquidity cycle)."""

    await connection.execute(
        "INSERT INTO validations (id, plan_id, step_seq, stage, decision, primary_code, "
        "reason_codes, warnings, checks, policy_version, snapshot_block) "
        "VALUES ($1, $2, NULL, 'PLAN', $3, $4, $5, $6, $7::jsonb, $8, $9)",
        uuid7(),
        plan_id,
        decision.decision,
        decision.primary.value if decision.primary else None,
        [c.value for c in decision.codes],
        [c.value for c in decision.warnings],
        json.dumps(decision.model_dump(mode="json")["checks"]),
        decision.policy_version,
        decision.snapshot_block,
    )


async def _insert_review(
    connection: asyncpg.Connection,
    inputs: PlanInputs,
    treasury_id: uuid.UUID,
    plan_id: uuid.UUID,
    kind: str,
    primary_code: str,
    reason_codes: tuple[str, ...],
    *,
    now: datetime,
    fee_estimate_wei: int | None = None,
    due: datetime | None = None,
) -> None:
    roles, hours = _ROLES[kind]
    sla = due if due is not None else now + timedelta(hours=hours)
    # One open item per (request, type): a re-plan finds the existing item and leaves it.
    await connection.execute(
        """
        INSERT INTO review_items (id, org_id, treasury_id, request_id, request_version, plan_id,
            type, primary_code, reason_codes, completed_steps, assigned_roles, status, sla_due_at,
            fee_estimate_wei)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, '[]'::jsonb, $10, 'Open', $11, $12)
        ON CONFLICT (request_id, type) WHERE status = 'Open' DO NOTHING
        """,
        uuid7(),
        inputs.org_id,
        treasury_id,
        inputs.request_id,
        inputs.request_version,
        plan_id,
        kind,
        primary_code,
        list(reason_codes),
        list(roles),
        sla,
        fee_estimate_wei,
    )


async def _move_request(
    connection: asyncpg.Connection, request_id: uuid.UUID, target: str, reason: str
) -> None:
    """Walk the request through the system transitions of M05 §5 up to `target`."""
    current = await connection.fetchval(
        "SELECT status FROM payment_requests WHERE id = $1 FOR UPDATE", request_id
    )
    route = ("Approved", "Scheduled", "Planning", target)
    if current not in route[:3]:
        return  # already moved on (a redelivered finish)
    previous = current
    for status in route[route.index(current) + 1 :]:
        await connection.execute(
            "UPDATE payment_requests SET status = $2, version = version + 1, updated_at = now() "
            "WHERE id = $1",
            request_id,
            status,
        )
        await connection.execute(
            'INSERT INTO request_status_events (id, request_id, "from", "to", actor_type, reason) '
            "VALUES ($1, $2, $3, $4, 'SYSTEM', $5)",
            uuid7(),
            request_id,
            previous,
            status,
            reason,
        )
        previous = status


async def _fee_assessment(
    connection: asyncpg.Connection,
    treasury_id: uuid.UUID,
    plan_id: uuid.UUID,
    estimate: int,
    deadline: int,
    now: datetime,
) -> tuple[FeeDecision, str | None]:
    policy = await connection.fetchrow(
        "SELECT per_plan_threshold_wei, daily_budget_wei FROM treasury_fee_policies "
        "WHERE treasury_id = $1 AND accepted_at IS NOT NULL AND superseded_at IS NULL",
        treasury_id,
    )
    if policy is None:
        return FeeDecision.AWAITING_FEE_ACCEPTANCE, "FEE_POLICY_MISSING"
    # "Pay now" (M03 8.7): an Owner-accepted cap for an earlier plan of this request is keyed by
    # that plan, but the replan has a new id, so it is found through the request. Within the cap
    # the plan proceeds past the threshold and the budget; above it the hold repeats.
    cap = await connection.fetchval(
        "SELECT f.accepted_cap_wei FROM fee_acceptances f JOIN plans p ON p.id = f.plan_id "
        "JOIN plans cur ON cur.id = $1 WHERE "
        "(p.request_id IS NOT NULL AND p.request_id = cur.request_id) "
        # a liquidity plan has no request: a cap holds for its cycle (same module, day and count)
        "OR (p.request_id IS NULL AND cur.request_id IS NULL AND p.treasury_id = cur.treasury_id "
        "AND p.liquidity_cycle_id = cur.liquidity_cycle_id) "
        "ORDER BY f.at DESC LIMIT 1",
        plan_id,
    )
    if cap is not None and estimate <= int(cap):
        return FeeDecision.PROCEED, "FEE_ACCEPTED"
    spent = await connection.fetchval(
        "SELECT coalesce(sum(fee_wei), 0) FROM gas_ledger "
        "WHERE treasury_id = $1 AND day = $2 AND payer = 'EXECUTOR'",
        treasury_id,
        now.date(),
    )
    # Plans attested today count against today's budget until the ledger has their fees. Nothing
    # marks a plan Completed yet, so the day bound is what frees the budget the next day.
    in_flight = await connection.fetchval(
        f"SELECT coalesce(sum(fee_estimate_wei), 0) FROM plans WHERE treasury_id = $1 "
        f"AND status IN {_OPEN_PLANS} AND updated_at >= $2",
        treasury_id,
        datetime.combine(now.date(), time.min, UTC),
    )
    result = assess_fee(
        estimated_fee_wei=estimate,
        per_plan_threshold_wei=int(policy["per_plan_threshold_wei"]),
        spent_today_wei=int(spent) + int(in_flight),
        daily_budget_wei=int(policy["daily_budget_wei"]),
        last_safe_execution_at=datetime.fromtimestamp(deadline, UTC),
        now=now,
    )
    return result.decision, result.reason_code


async def plan_request(
    pool: asyncpg.Pool,
    plan_id: uuid.UUID,
    deps: PlannerDeps,
    *,
    now: datetime | None = None,
) -> PlanOutcome | None:
    """Plan the request of the `Draft` plan `plan_id`; the outcome is stored before returning.

    `None` means the plan is already past Draft (a redelivered task); `LookupError`, that the
    claim is not visible yet.
    """
    current = (now or datetime.now(UTC)).astimezone(UTC)
    async with pool.acquire() as connection:
        row = await connection.fetchrow(
            "SELECT treasury_id, request_id, status FROM plans WHERE id = $1", plan_id
        )
        if row is None:
            raise LookupError(f"plan {plan_id} not found")
        if row["status"] != "Draft":
            return None
        treasury_id, request_id = row["treasury_id"], row["request_id"]
        try:
            probe = await probe_plan(connection, treasury_id, request_id)
        except InputsUnavailable as error:
            return await _expire(pool, plan_id, error)
    context_inputs = await load_context_inputs(pool, probe, treasury_id, executor=deps.executor)
    chain, head = await deps.take_snapshot(treasury_id, scope_for(probe, context_inputs))
    try:
        async with pool.acquire() as connection:
            inputs = await load_inputs(connection, treasury_id, request_id, chain, now=current)
            reserve = await load_liquidity_inputs(connection, treasury_id)
    except InputsUnavailable as error:
        return await _expire(pool, plan_id, error)
    context = Context(context_inputs, chain, int(current.timestamp()), head)
    target_id = str(request_id)
    deterministic = schedule_edf(inputs.requests, inputs.snapshot, inputs.policy)

    outcome = None
    if deps.ai is not None and needs_full_proposal(
        eligible_requests=len(inputs.requests),
        terms_or_deferrals_matter=any(
            r.terms.discount_bps or r.terms.priority_note or r.terms.late_fee
            for r in inputs.requests
        ),
    ):
        outcome = await deps.ai.propose(
            org_id=inputs.org_id,
            treasury_id=treasury_id,
            eligible_ids=tuple(r.id for r in inputs.requests),
        )
    ai_ids = [outcome.ai_call_id] if outcome and outcome.ai_call_id else []

    reviews: list[ReviewIntent] = []
    source = "DETERMINISTIC"
    reason = ""
    plan: ExecutionPlan | None = None
    refusal: tuple[str | None, str] | None = None  # (review type or None to defer, code)
    if (
        outcome is not None
        and isinstance(outcome.result, AiError)
        and not isinstance(outcome.result, PlanProposalRejected)
    ):
        # BR-055: an AI outage keeps the pipeline alive only through a validated template.
        fallback = plan_fallback(context.build(probe), outcome.result)
        if isinstance(fallback, FallbackPlan):
            plan, source = fallback.plan, "RULE_BASED"
            reason = (
                f"AI unavailable ({type(outcome.result).__name__}); template {fallback.template}"
            )
        else:
            refusal = ("INFRA", fallback.reason.value)
            reason = f"AI unavailable and no rule-based fallback: {fallback.reason.value}"
    else:
        selection = select_plan(
            deterministic,
            None if outcome is None else outcome.result,  # type: ignore[arg-type]
            inputs.requests,
            inputs.snapshot,
            inputs.policy,
            inputs.today,
        )
        source, reason = selection.planner_source, selection.chosen_reason
        if selection.review is not None:
            reviews.append(selection.review)
        today = inputs.snapshot.day
        item = next(
            (i for i in selection.items if i.request_id == target_id and i.day == today), None
        )
        if item is not None:
            target = next(r for r in inputs.requests if r.id == target_id)
            # EXE-014: a refill that would break the reserve is preceded by a pool withdrawal.
            withdraw = reserve_withdrawal(inputs, reserve, chain.data, int(item.refill), target_id)
            plan = _build_plan(
                probe,
                target,
                item,
                source,
                str(chain.id),
                withdraw=withdraw,
                a_token=str((chain.data.get("aave") or {}).get("a_token", "")),
            )
        else:
            refusal = _not_today(deterministic, target_id)
    return await _finish(
        pool,
        deps,
        inputs,
        context,
        plan_id,
        treasury_id,
        plan,
        source,
        reason,
        refusal,
        reviews,
        ai_ids,
        current,
    )


@dataclass(frozen=True)
class Context:
    """What `planner.context.build_context` needs besides the plan; one per planning run."""

    inputs: ContextInputs
    chain: ChainRead
    now: int
    head: int

    def build(self, plan: ExecutionPlan) -> ValidationContext:
        return build_context(self.chain, plan, self.inputs, now=self.now, head_block=self.head)


async def _expire(pool: asyncpg.Pool, plan_id: uuid.UUID, error: InputsUnavailable) -> PlanOutcome:
    """The request cannot be planned at all (fail closed): free it for the next cycle."""

    logger.warning("plan_inputs_unavailable", extra={"plan_id": str(plan_id), "reason": str(error)})
    await pool.execute(
        "UPDATE plans SET status = 'Expired', chosen_reason = $2, updated_at = now() "
        "WHERE id = $1 AND status = 'Draft'",
        plan_id,
        f"inputs unavailable: {error}",
    )
    return PlanOutcome(plan_id, "Expired", None)


def _not_today(schedule: Schedule, target_id: str) -> tuple[str | None, str]:
    """Why the request is not paid in this cycle: infeasible (a review) or simply later (None)."""
    for item in schedule.infeasible:
        if item.request_id == target_id:
            return (
                "NEEDS_AUTHORITY" if item.reason == "NEEDS_EXCEPTION" else "POLICY_BLOCK"
            ), item.reason
    return None, "DEFERRED"


async def _finish(
    pool: asyncpg.Pool,
    deps: PlannerDeps,
    inputs: PlanInputs,
    context: Context,
    plan_id: uuid.UUID,
    treasury_id: uuid.UUID,
    plan: ExecutionPlan | None,
    source: str,
    reason: str,
    refusal: tuple[str | None, str] | None,
    reviews: list[ReviewIntent],
    ai_ids: list[uuid.UUID],
    now: datetime,
) -> PlanOutcome:
    status = "Superseded"  # deferred or fee-deferred: the cooldown plans it again later
    decision: Decision | None = None
    review: tuple[str, str, tuple[str, ...], int | None] | None = None  # kind, code, codes, fee
    request_to = ""
    estimate: int | None = None
    chain = context.chain
    request = context.inputs.request
    if plan is not None and deps.gas_swap is not None:
        # The swap is sized on the plan's fee, then once more on the fee WITH the swap step so
        # that its own gas is covered (the swap's gas barely depends on its size: one pass).
        try:
            bare = plan
            required = await deps.estimate_fee(treasury_id, bare)
            for _ in range(2):
                swapped = await with_gas_swap(
                    deps.gas_swap,
                    treasury_id,
                    bare,
                    required_wei=required,
                    safe_t=context.inputs.safe_t,
                    asset=context.inputs.asset,
                )
                if swapped is bare:  # no shortage
                    break
                with_swap = await deps.estimate_fee(treasury_id, swapped)
                plan = swapped
                if with_swap <= required:
                    break
                required = with_swap
        except (GasSwapUnavailable, GasSwapInfeasible) as error:
            # Fail closed: a plan the executor cannot pay for must not be attested.
            plan, refusal = None, ("INFRA", "GAS_SHORTAGE_UNCOVERED")
            reason = f"{reason}; gas shortage: {error}"
    if plan is None:
        assert refusal is not None
        kind, code = refusal
        if kind is not None:
            waiting = kind == "NEEDS_AUTHORITY"
            status = "AwaitingAuthority" if waiting else "Blocked"
            request_to = "AwaitingAuthority" if waiting else "NeedsReview"
            review = (kind, code, (code,), None)
    else:
        decision = validate_plan(plan, context.build(plan))
        codes = tuple(c.value for c in decision.codes)
        primary = decision.primary.value if decision.primary else decision.decision
        if decision.decision == "BLOCK":
            status, request_to, review = (
                "Blocked",
                "NeedsReview",
                ("POLICY_BLOCK", primary, codes, None),
            )
        elif decision.decision == "NEEDS_APPROVAL":
            status, request_to = "AwaitingAuthority", "AwaitingAuthority"
            review = ("NEEDS_AUTHORITY", primary, codes, None)
        else:
            assert request is not None  # an ALLOW decision needed the request
            estimate = await deps.estimate_fee(treasury_id, plan)
            async with pool.acquire() as connection:
                fee, fee_code = await _fee_assessment(
                    connection, treasury_id, plan_id, estimate, request.deadline, now
                )
            if fee is FeeDecision.AWAITING_FEE_ACCEPTANCE:
                status = "AwaitingFeeAcceptance"
                code = fee_code or "FEE_APPROVAL_REQUIRED"
                review = ("FEE_APPROVAL", code, (code,), estimate)
            elif fee is FeeDecision.PROCEED:
                digest = evidence_digest(chain)
                # A re-run after a crash between the attestation commit and the plan write finds
                # the attestation already stored: reuse it rather than signing a second one.
                async with pool.acquire() as connection:
                    attested = await connection.fetchval(
                        "SELECT 1 FROM attestations WHERE plan_id = $1", plan_id
                    )
                if not attested:
                    await deps.attest(plan_id, plan.message(), decision, digest, now)
                status, request_to = "Attested", "Preparing"
    message = None if plan is None else plan.message()
    digest_bytes = (
        None
        if message is None
        else plan_hash(
            message["requestId"], message["treasury"], message["chainId"], message["steps"]
        )
    )
    created: list[str] = []
    async with pool.acquire() as connection, connection.transaction():
        attestation_id = (
            await connection.fetchval("SELECT id FROM attestations WHERE plan_id = $1", plan_id)
            if status == "Attested"
            else None
        )
        await connection.execute(
            "UPDATE plans SET status = $2, planner_source = $3, plan_hash = $4, "
            "chosen_reason = $5, ai_call_ids = $6, snapshot_id = $7, attestation_id = $8, "
            "fee_estimate_wei = $9, updated_at = now() WHERE id = $1",
            plan_id,
            status,
            source if plan is not None else None,
            digest_bytes,
            reason,
            ai_ids,
            chain.id,
            attestation_id,
            estimate,
        )
        if decision is not None:
            await insert_plan_validation(connection, plan_id, decision)
        for intent in reviews:
            codes = intent.reason_codes or (intent.primary_code,)
            await _insert_review(
                connection,
                inputs,
                treasury_id,
                plan_id,
                intent.kind,
                intent.primary_code,
                codes,
                now=now,
            )
            created.append(intent.kind)
        if review is not None:
            kind, code, codes, fee_wei = review
            await _insert_review(
                connection,
                inputs,
                treasury_id,
                plan_id,
                kind,
                code,
                codes,
                now=now,
                fee_estimate_wei=fee_wei,
                due=datetime.fromtimestamp(request.deadline, UTC)
                if kind == "FEE_APPROVAL" and request is not None
                else None,
            )
            created.append(kind)
        if request_to:
            await _move_request(connection, inputs.request_id, request_to, f"plan {status}")
        await append_audit(
            connection,
            inputs.org_id,
            action="plan.finished",
            entity_type="plan",
            entity_id=str(plan_id),
            data={
                "status": status,
                "request_id": str(inputs.request_id),
                "planner_source": source if plan is not None else None,
                "plan_hash": None if digest_bytes is None else "0x" + digest_bytes.hex(),
                "reason_codes": [] if decision is None else [c.value for c in decision.codes],
                "reviews": created,
            },
        )
    logger.info(
        "plan_finished",
        extra={
            "plan_id": str(plan_id),
            "status": status,
            "planner_source": source,
            "reviews": created,
        },
    )
    return PlanOutcome(plan_id, status, source if plan is not None else None, tuple(created))
