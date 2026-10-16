"""Sequential plan executor (EXE-008, M10 §7.3 steps 1 and 4-6).

``sequence_plan`` is resumable and never blocks: it walks the plan in order, sends at most one
step per call and returns ``Waiting`` while that step is Submitted/Pending. The tracker confirms
the transaction; the caller re-runs the plan and the next step is then re-validated against a
fresh snapshot (``Gate.pre_step``) before anything is signed. ``plan_steps`` carries no status,
so progress is derived from the ``operations`` rows (one per ``step_id``).

The request must be Preparing/Paying on every call and again right before a step is sent, so a
cancel or review stop that landed meanwhile is honoured. The concrete ``Gate`` is
``executor.gate.PlanGate``; the Celery driver is ``tasks.sequence_plan_task``.

M10-D6: a Confirmed step must have a PASSED REC-001 post-condition before the next step is sent.
The verifier makes one read attempt per call; an UNKNOWN waits and is retried by the next call, and
the third UNKNOWN (3 reads in total) newer than the last verdict and the last resolved
VERIFICATION_UNKNOWN review opens an INFRA review. DISCREPANCY opens a DISCREPANCY review (the verifier has
already raised the circuit-breaker signal).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol
from uuid import UUID

import asyncpg  # type: ignore[import-untyped]

from treasurypilot_core.engine.swap_quote import QuoteRejected
from treasurypilot_core.policy import Decision, PolicyReasonCode
from treasurypilot_worker.executor.outbox import (
    PAUSED_SQL,
    SignerClient,
    SignerRefused,
    StepExecution,
    TreasuryPaused,
    execute_step,
)
from treasurypilot_worker.liquidity_review import open_liquidity_review
from treasurypilot_worker.reconcile.build import build_reconciliation
from treasurypilot_worker.recovery.retry import ReviewIntent, classify

logger = logging.getLogger(__name__)

SequenceStatus = Literal[
    "Completed", "Waiting", "PartiallyCompleted", "Blocked", "Inactive", "Paused"
]


@dataclass(frozen=True)
class PlanRun:
    """An attested plan: ``steps`` in seq order, valid until ``valid_until`` (attestation expiry)."""

    plan_id: UUID
    request_id: UUID | None  # None for a liquidity plan: no request moves, the review is by plan
    steps: tuple[StepExecution, ...]
    valid_until: datetime


class Gate(Protocol):
    async def pre_step(self, seq: int) -> Decision:
        """Fresh snapshot, ``validate_step`` (PRE_STEP) then ``simulate`` (SIMULATION), recorded.

        Returns the first non-ALLOW decision, else the ALLOW simulation decision.
        """
        ...

    async def reattest(self, seq: int) -> PlanRun | Decision:
        """New plan validation + attestation for steps ``seq``..; a non-ALLOW decision stops."""
        ...


class Verifier(Protocol):
    async def verify(self, step_id: bytes, operation_id: UUID) -> str:
        """REC-001: PASSED, DISCREPANCY or UNKNOWN; persisted, and a DISCREPANCY trips the breaker."""
        ...


@dataclass(frozen=True)
class SequenceResult:
    status: SequenceStatus
    code: str | None = None
    completed: int = 0


MAX_UNKNOWN = 3  # failed verification reads before a human looks
_OPEN = ("Submitted", "Pending", "Unknown")
_ACTIVE = ("Preparing", "Paying")  # the only request states in which a step may be sent
# Mirrors treasurypilot_api.recovery.review_queue routing for the kinds raised here (tested).
_POLICY_EDIT_CODES = frozenset(
    {"AMOUNT_CHANGED", "PAYEE_CHANGED", "APPROVAL_INVALID", "APPROVAL_EXPIRED"}
)


def _route(kind: str, code: str) -> tuple[list[str], timedelta]:
    if kind == "NEEDS_AUTHORITY":
        return ["Owner"], timedelta(hours=24)
    if kind == "POLICY_BLOCK" and code in _POLICY_EDIT_CODES:
        return ["Operator", "Approver"], timedelta(hours=48)
    if kind == "DISCREPANCY":
        return ["Finance", "Owner"], timedelta(hours=48)
    if kind in ("INFRA", "AI_REJECTED"):
        return ["Operator"], timedelta(hours=48)
    return ["Owner"], timedelta(hours=48)


def _intent(decision: Decision) -> ReviewIntent:
    code = str(decision.primary) if decision.primary else "UNCLASSIFIED_ERROR"
    kind = "NEEDS_AUTHORITY" if decision.decision == "NEEDS_APPROVAL" else "POLICY_BLOCK"
    return ReviewIntent(kind, code, tuple(str(c) for c in decision.codes))  # type: ignore[arg-type]


def _refusal_intent(code: str) -> ReviewIntent:
    try:
        review = classify(PolicyReasonCode(code)).review
    except ValueError:
        review = None
    return ReviewIntent(review.kind if review else "INFRA", code, (code,))


async def transition_request(
    connection: asyncpg.Connection,
    request_id: UUID,
    to: str,
    sources: tuple[str, ...],
    why: str,
    actor_id: UUID | None = None,
) -> bool:
    """Move a request and write its status event; USER actor when ``actor_id`` is given."""

    row = await connection.fetchrow(
        "WITH old AS (SELECT id, status FROM payment_requests "
        "WHERE id = $1 AND status = ANY($2::text[]) FOR UPDATE), "
        "upd AS (UPDATE payment_requests r SET status = $3, version = r.version + 1, "
        "updated_at = now() FROM old WHERE r.id = old.id RETURNING r.id) "
        'INSERT INTO request_status_events (id, request_id, "from", "to", actor_type, '
        "actor_id, reason) SELECT gen_random_uuid(), old.id, old.status, $3, "
        "CASE WHEN $5::uuid IS NULL THEN 'SYSTEM' ELSE 'USER' END, $5::uuid, $4 "
        "FROM old JOIN upd USING (id) RETURNING request_id",
        request_id,
        list(sources),
        to,
        why,
        actor_id,
    )
    return row is not None


async def _stop(
    pool: asyncpg.Pool, run: PlanRun, intent: ReviewIntent, completed: int
) -> SequenceResult:
    """Open one review item and move the request to NeedsReview; completed steps stay (BR-054)."""

    if (
        run.request_id is None
    ):  # a liquidity plan serves no request: free the cycle, review keyed by plan
        # a reverted/abandoned step spent its step id: PartiallyCompleted moves the cycle counter
        spent = completed or intent.primary_code in ("STEP_REVERTED", "STEP_ABANDONED")
        async with pool.acquire() as connection, connection.transaction():
            moved = await connection.execute(
                "UPDATE plans SET status = $2, chosen_reason = left(coalesce(chosen_reason, '') "
                "|| ' | stopped: ' || $3, 500), updated_at = now() "
                "WHERE id = $1 AND status IN ('Attested', 'Executing')",
                run.plan_id,
                "PartiallyCompleted" if spent else "Superseded",
                intent.primary_code,
            )
            if moved.endswith(" 1"):  # a redelivered stop finds the plan already ended
                await open_liquidity_review(
                    connection,
                    plan_id=run.plan_id,
                    kind=intent.kind,
                    primary_code=intent.primary_code,
                    reason_codes=tuple(intent.reason_codes),
                    completed_steps=[
                        {"seq": seq, "stepId": "0x" + step.step_id.hex()}
                        for seq, step in enumerate(run.steps[:completed])
                    ],
                )
        logger.error("liquidity plan %s stopped: %s", run.plan_id, intent.primary_code)
        return SequenceResult(
            "PartiallyCompleted" if spent else "Blocked", intent.primary_code, completed
        )
    async with pool.acquire() as connection, connection.transaction():
        moved = await transition_request(
            connection,
            run.request_id,
            "NeedsReview",
            ("Planning", "Preparing", "Paying"),
            f"execution stopped: {intent.primary_code}",
        )
        if not moved:  # cancelled or already reviewed meanwhile: no second item
            return SequenceResult("Inactive", intent.primary_code, completed)
        request = await connection.fetchrow(
            "SELECT org_id, treasury_id, version FROM payment_requests WHERE id = $1",
            run.request_id,
        )
        roles, sla = _route(intent.kind, intent.primary_code)
        done = [
            {"seq": seq, "stepId": "0x" + step.step_id.hex()}
            for seq, step in enumerate(run.steps[:completed])
        ]
        await connection.execute(
            "INSERT INTO review_items (id, org_id, treasury_id, request_id, request_version, "
            "plan_id, type, primary_code, reason_codes, completed_steps, assigned_roles, "
            "status, sla_due_at, evidence_resolved) VALUES (gen_random_uuid(), $1, $2, $3, $4, "
            "$5, $6, $7, $8, $9::jsonb, $10, 'Open', $11, false) "
            "ON CONFLICT (request_id, type) WHERE status = 'Open' DO NOTHING",
            request["org_id"],
            request["treasury_id"],
            run.request_id,
            request["version"],
            run.plan_id,
            intent.kind,
            intent.primary_code,
            list(intent.reason_codes),
            json.dumps(done),
            roles,
            datetime.now(UTC) + sla,
        )
    logger.warning("plan %s stopped at step %d: %s", run.plan_id, completed, intent.primary_code)
    return SequenceResult(
        "PartiallyCompleted" if completed else "Blocked", intent.primary_code, completed
    )


async def sequence_plan(
    pool: asyncpg.Pool,
    signer: SignerClient,
    run: PlanRun,
    gate: Gate,
    verifier: Verifier,
    *,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    before_send: Callable[[StepExecution], Awaitable[None]] | None = None,
) -> SequenceResult:
    """Advance the plan by at most one step; see the module docstring.

    ``before_send`` runs after a step's PRE_STEP gate allowed it and before anything is signed (EXE-L02:
    fetch, verify and stage a signed swap quote). ``QuoteRejected`` stops the plan with its code.
    """

    if (request_status := await _request_status(pool, run)) not in _ACTIVE:
        return SequenceResult("Inactive", request_status)
    for seq, step in enumerate(run.steps):
        row = await pool.fetchrow(
            "SELECT id, status, attempts FROM operations WHERE step_id = $1", step.step_id
        )
        status = row["status"] if row else None
        if status == "Confirmed":
            if outcome := await _post_condition(pool, run, verifier, step, row["id"], seq):
                return outcome
            continue
        if status in _OPEN:
            if step.kind == "PAY":
                await _mark(pool, run, "Paying", ("Preparing",))
            return SequenceResult("Waiting", completed=seq)
        if status in ("Reverted", "Abandoned"):
            return await _stop(pool, run, ReviewIntent("INFRA", f"STEP_{status.upper()}"), seq)

        # Paused is a no-op, not a review: the request stays queued and is re-planned on Resumed.
        if await _paused(pool, run):
            return SequenceResult("Paused", completed=seq)
        # A NotSubmitted row with attempts was already validated and sent: replay it as is, the
        # signer answers by step_id (re-validating or re-attesting could strand a sent step).
        if not (row and row["attempts"] > 0):
            if clock() >= run.valid_until:  # attestation expired before this step (M10 §5)
                renewed = await gate.reattest(seq)
                if isinstance(renewed, Decision):
                    return await _stop(pool, run, _intent(renewed), seq)
                run, step = renewed, renewed.steps[seq]
            decision = await gate.pre_step(seq)
            if decision.decision != "ALLOW":
                return await _stop(pool, run, _intent(decision), seq)
            if before_send is not None:
                try:
                    await before_send(step)
                except QuoteRejected as error:  # stale or forged quote: nothing is signed
                    return await _stop(pool, run, ReviewIntent("INFRA", error.code), seq)
        # shortcut: re-checked, not locked, through the operation insert (execute_step owns its
        # transaction); a cancel in that window is caught by the signer's attestation checks.
        if (request_status := await _request_status(pool, run)) not in _ACTIVE:
            return SequenceResult("Inactive", request_status, seq)
        try:
            await execute_step(pool, signer, step)
        except SignerRefused as error:
            return await _stop(pool, run, _refusal_intent(error.code), seq)
        except TreasuryPaused:  # a pause landed after the check above; the op stays NotSubmitted
            return SequenceResult("Paused", completed=seq)
        if step.kind == "PAY":
            await _mark(pool, run, "Paying", ("Preparing",))
        return SequenceResult("Waiting", completed=seq)

    if any(step.kind == "PAY" for step in run.steps):
        # Paying first so both state-machine events are recorded, even for a resumed plan.
        await _mark(pool, run, "Paying", ("Preparing",))
        async with pool.acquire() as connection, connection.transaction():
            assert run.request_id is not None
            await transition_request(
                connection, run.request_id, "Paid", ("Paying",), "PAY step paid"
            )
            # Must raise, never swallow: a failed build has to roll Paid back (REC-002).
            await build_reconciliation(connection, run.request_id)
    return SequenceResult("Completed", completed=len(run.steps))


async def _paused(pool: asyncpg.Pool, run: PlanRun) -> bool:
    return bool(run.steps) and bool(await pool.fetchval(PAUSED_SQL, run.steps[0].treasury_id))


async def _post_condition(
    pool: asyncpg.Pool,
    run: PlanRun,
    verifier: Verifier,
    step: StepExecution,
    operation_id: UUID,
    seq: int,
) -> SequenceResult | None:
    """None when the confirmed step PASSED; otherwise the result that stops this call."""

    verdict = await pool.fetchval(
        "SELECT result FROM verifications WHERE operation_id = $1 "
        "AND result IN ('PASSED', 'DISCREPANCY') ORDER BY at DESC LIMIT 1",
        operation_id,
    )
    if verdict is None:
        verdict = await verifier.verify(step.step_id, operation_id)
    if verdict == "PASSED":
        return None
    if verdict == "DISCREPANCY":
        intent = ReviewIntent("DISCREPANCY", "POST_CONDITION_DISCREPANCY")
        return await _stop(pool, run, intent, seq + 1)
    unknown = await pool.fetchval(
        "SELECT count(*) FROM verifications WHERE operation_id = $1 AND result = 'UNKNOWN' "
        "AND at > COALESCE((SELECT max(at) FROM verifications WHERE operation_id = $1 "
        "AND result <> 'UNKNOWN'), '-infinity') "
        "AND at > COALESCE((SELECT max(resolved_at) FROM review_items WHERE request_id = $2 "
        "AND type = 'INFRA' AND primary_code = 'VERIFICATION_UNKNOWN'), '-infinity')",
        operation_id,
        run.request_id,
    )
    if unknown >= MAX_UNKNOWN:
        return await _stop(pool, run, ReviewIntent("INFRA", "VERIFICATION_UNKNOWN"), seq + 1)
    return SequenceResult("Waiting", "VERIFICATION_UNKNOWN", seq)


async def _request_status(pool: asyncpg.Pool, run: PlanRun) -> str | None:
    if run.request_id is None:  # a liquidity plan is active exactly while its plan is open
        plan_status = await pool.fetchval("SELECT status FROM plans WHERE id = $1", run.plan_id)
        return "Preparing" if plan_status in ("Attested", "Executing") else plan_status
    status: str | None = await pool.fetchval(
        "SELECT status FROM payment_requests WHERE id = $1", run.request_id
    )
    return status


async def _mark(pool: asyncpg.Pool, run: PlanRun, to: str, sources: tuple[str, ...]) -> None:
    assert run.request_id is not None  # only a PAY step moves a request
    async with pool.acquire() as connection, connection.transaction():
        await transition_request(connection, run.request_id, to, sources, f"PAY step {to.lower()}")


__all__ = ["Gate", "PlanRun", "SequenceResult", "Verifier", "sequence_plan"]
