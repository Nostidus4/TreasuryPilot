"""Sequential plan executor (EXE-008, M10 §7.3 steps 1 and 4-6).

``sequence_plan`` is resumable and never blocks: it walks the plan in order, sends at most one
step per call and returns ``Waiting`` while that step is Submitted/Pending. The tracker confirms
the transaction; the caller re-runs the plan and the next step is then re-validated against a
fresh snapshot (``Gate.pre_step``) before anything is signed. ``plan_steps`` carries no status,
so progress is derived from the ``operations`` rows (one per ``step_id``).

Not wired here: the REC-001 post-condition gate (M10-D6) and building the ``Gate`` from a
snapshot (the planner owns that context); Confirmed is the only wait condition for now.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol
from uuid import UUID

import asyncpg  # type: ignore[import-untyped]

from treasurypilot_core.policy import Decision, PolicyReasonCode
from treasurypilot_worker.executor.outbox import (
    SignerClient,
    SignerRefused,
    StepExecution,
    execute_step,
)
from treasurypilot_worker.recovery.retry import ReviewIntent, classify

logger = logging.getLogger(__name__)

SequenceStatus = Literal["Completed", "Waiting", "PartiallyCompleted", "Blocked"]


@dataclass(frozen=True)
class PlanRun:
    """An attested plan: ``steps`` in seq order, valid until ``valid_until`` (attestation expiry)."""

    plan_id: UUID
    request_id: UUID
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


@dataclass(frozen=True)
class SequenceResult:
    status: SequenceStatus
    code: str | None = None
    completed: int = 0


_OPEN = ("Submitted", "Pending", "Unknown")
# Mirrors treasurypilot_api.recovery.review_queue routing for the kinds raised here (tested).
_POLICY_EDIT_CODES = frozenset(
    {"AMOUNT_CHANGED", "PAYEE_CHANGED", "APPROVAL_INVALID", "APPROVAL_EXPIRED"}
)


def _route(kind: str, code: str) -> tuple[list[str], timedelta]:
    if kind == "NEEDS_AUTHORITY":
        return ["Owner"], timedelta(hours=24)
    if kind == "POLICY_BLOCK" and code in _POLICY_EDIT_CODES:
        return ["Operator", "Approver"], timedelta(hours=48)
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


async def _transition(
    connection: asyncpg.Connection, request_id: UUID, to: str, sources: tuple[str, ...], why: str
) -> bool:
    row = await connection.fetchrow(
        "WITH old AS (SELECT id, status FROM payment_requests "
        "WHERE id = $1 AND status = ANY($2::text[]) FOR UPDATE), "
        "upd AS (UPDATE payment_requests r SET status = $3, version = r.version + 1, "
        "updated_at = now() FROM old WHERE r.id = old.id RETURNING r.id) "
        'INSERT INTO request_status_events (id, request_id, "from", "to", actor_type, '
        "actor_id, reason) SELECT gen_random_uuid(), old.id, old.status, $3, 'SYSTEM', NULL, $4 "
        "FROM old JOIN upd USING (id) RETURNING request_id",
        request_id,
        list(sources),
        to,
        why,
    )
    return row is not None


async def _stop(
    pool: asyncpg.Pool, run: PlanRun, intent: ReviewIntent, completed: int
) -> SequenceResult:
    """Open one review item and move the request to NeedsReview; completed steps stay (BR-054)."""

    async with pool.acquire() as connection, connection.transaction():
        await _transition(
            connection,
            run.request_id,
            "NeedsReview",
            ("Planning", "Preparing", "Paying"),
            f"execution stopped: {intent.primary_code}",
        )
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
    *,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> SequenceResult:
    """Advance the plan by at most one step; see the module docstring."""

    for seq, step in enumerate(run.steps):
        status = await pool.fetchval(
            "SELECT status FROM operations WHERE step_id = $1", step.step_id
        )
        if status == "Confirmed":
            continue
        if status in _OPEN:
            if step.kind == "PAY":
                await _mark(pool, run, "Paying", ("Preparing",))
            return SequenceResult("Waiting", completed=seq)
        if status in ("Reverted", "Abandoned"):
            return await _stop(pool, run, ReviewIntent("INFRA", f"STEP_{status.upper()}"), seq)

        if clock() >= run.valid_until:  # attestation expired before this step (M10 §5)
            renewed = await gate.reattest(seq)
            if isinstance(renewed, Decision):
                return await _stop(pool, run, _intent(renewed), seq)
            run, step = renewed, renewed.steps[seq]
        decision = await gate.pre_step(seq)
        if decision.decision != "ALLOW":
            return await _stop(pool, run, _intent(decision), seq)
        try:
            await execute_step(pool, signer, step)
        except SignerRefused as error:
            return await _stop(pool, run, _refusal_intent(error.code), seq)
        if step.kind == "PAY":
            await _mark(pool, run, "Paying", ("Preparing",))
        return SequenceResult("Waiting", completed=seq)

    if any(step.kind == "PAY" for step in run.steps):
        await _mark(pool, run, "Paid", ("Preparing", "Paying"))
    return SequenceResult("Completed", completed=len(run.steps))


async def _mark(pool: asyncpg.Pool, run: PlanRun, to: str, sources: tuple[str, ...]) -> None:
    async with pool.acquire() as connection, connection.transaction():
        await _transition(connection, run.request_id, to, sources, f"PAY step {to.lower()}")


__all__ = ["Gate", "PlanRun", "SequenceResult", "sequence_plan"]
