"""Partial completion: resume or cancel a plan that stopped after some steps (RCV-003, BR-054).

``resume_partial`` only reopens the request (NeedsReview -> Preparing) and the plan
(PartiallyCompleted -> Executing). It sends nothing: the next ``sequence_plan`` call skips every
Confirmed step (their operation rows exist, so a refill is never repeated) and re-reads and
re-validates the first unfinished step with ``Gate.pre_step`` before signing it. The caller
(the celery task the review-item RETRY action enqueues) then enqueues
``treasurypilot.execution.sequence_plan``; the 15 s sweep also picks the plan up.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

import asyncpg  # type: ignore[import-untyped]

from treasurypilot_worker.executor.sequencer import transition_request

ResumeStatus = Literal["Resumed", "NotPartial", "InFlight", "NotRetryable"]

# Review item types whose routing table allows RETRY (recovery README 8.3).
_RETRYABLE_TYPES = ("POLICY_BLOCK", "INFRA")
_IN_FLIGHT = (
    "SELECT 1 FROM operations WHERE request_id = $1 "
    "AND status IN ('Submitted', 'Pending', 'Unknown') LIMIT 1"
)


@dataclass(frozen=True)
class ResumeResult:
    status: ResumeStatus
    plan_id: UUID | None = None
    treasury_id: UUID | None = None  # routes the follow-up task to the treasury's shard


@dataclass(frozen=True)
class CancelReport:
    cancelled: bool
    plan_id: UUID | None = None
    completed_steps: tuple[str, ...] = ()  # 0x step ids
    # Cancel never reverses a step: whatever the confirmed steps moved stays where it is.
    funds_left_in_place: bool = False
    # Set when cancel was refused because these steps are Submitted/Pending/Unknown.
    in_flight_steps: tuple[str, ...] = ()
    summary: str = ""


async def resume_partial(
    pool: asyncpg.Pool, request_id: UUID, actor_id: UUID | None = None
) -> ResumeResult:
    """Reopen a request whose plan stopped part-way so only its unfinished steps run again."""

    async with pool.acquire() as connection, connection.transaction():
        plan = await connection.fetchrow(
            "SELECT id, treasury_id FROM plans WHERE request_id = $1 "
            "AND status = 'PartiallyCompleted' FOR UPDATE",
            request_id,
        )
        if plan is None:
            return ResumeResult("NotPartial")
        plan_id, treasury_id = plan["id"], plan["treasury_id"]
        # Unknown/in-flight operations are M12's to resolve first (BR-060); never re-send them.
        if await connection.fetchval(_IN_FLIGHT, request_id):
            return ResumeResult("InFlight", plan_id, treasury_id)
        # A Reverted/Abandoned step needs a re-plan, and only RETRY-able review items resolve here.
        if await connection.fetchval(
            "SELECT 1 FROM operations WHERE request_id = $1 "
            "AND status IN ('Reverted', 'Abandoned') LIMIT 1",
            request_id,
        ) or await connection.fetchval(
            "SELECT 1 FROM review_items WHERE request_id = $1 AND status = 'Open' "
            "AND NOT (type = ANY($2::text[])) LIMIT 1",
            request_id,
            list(_RETRYABLE_TYPES),
        ):
            return ResumeResult("NotRetryable", plan_id, treasury_id)
        if not await transition_request(
            connection,
            request_id,
            "Preparing",
            ("NeedsReview",),
            "partial plan resumed",
            actor_id,
        ):
            return ResumeResult("NotPartial", plan_id, treasury_id)
        await connection.execute(
            "UPDATE plans SET status = 'Executing', updated_at = now() WHERE id = $1", plan_id
        )
        await _resolve_items(connection, request_id, "RETRY", actor_id)
    return ResumeResult("Resumed", plan_id, treasury_id)


async def cancel_partial(
    pool: asyncpg.Pool, request_id: UUID, actor_id: UUID | None = None
) -> CancelReport:
    """Cancel a stopped request and report which confirmed steps stay as they are."""

    async with pool.acquire() as connection, connection.transaction():
        plan_id = await connection.fetchval(
            "SELECT id FROM plans WHERE request_id = $1 AND status = 'PartiallyCompleted' "
            "FOR UPDATE",
            request_id,
        )
        if plan_id is None:
            return CancelReport(False, summary="Nothing to cancel: no partially completed plan.")
        in_flight = tuple(
            "0x" + row["step_id"].hex()
            for row in await connection.fetch(
                "SELECT step_id FROM operations WHERE request_id = $1 "
                "AND status IN ('Submitted', 'Pending', 'Unknown') ORDER BY created_at",
                request_id,
            )
        )
        if in_flight:
            return CancelReport(
                False,
                plan_id,
                in_flight_steps=in_flight,
                summary=f"Not cancelled: {len(in_flight)} step(s) in flight must be resolved first.",
            )
        if not await transition_request(
            connection,
            request_id,
            "Cancelled",
            ("NeedsReview",),
            "partial plan cancelled",
            actor_id,
        ):
            return CancelReport(False, plan_id, summary="Not cancelled: request not in review.")
        # The plan enum has no Cancelled; Superseded is its closed-without-replacement state.
        await connection.execute(
            "UPDATE plans SET status = 'Superseded', updated_at = now() WHERE id = $1", plan_id
        )
        await _resolve_items(connection, request_id, "CANCEL", actor_id)
        done = tuple(
            "0x" + row["step_id"].hex()
            for row in await connection.fetch(
                "SELECT step_id FROM operations WHERE request_id = $1 AND status = 'Confirmed' "
                "ORDER BY created_at",
                request_id,
            )
        )
    summary = (
        f"Cancelled. {len(done)} confirmed step(s) are not reversed; their funds stay in place."
        if done
        else "Cancelled. No step had been confirmed."
    )
    return CancelReport(True, plan_id, done, funds_left_in_place=bool(done), summary=summary)


async def _resolve_items(
    connection: asyncpg.Connection, request_id: UUID, resolution: str, actor_id: UUID | None
) -> None:
    # Answered items must not block a new stop from opening a fresh one.
    await connection.execute(
        "UPDATE review_items SET status = 'Resolved', resolution = $2, resolved_by = $3, "
        "resolved_at = now(), version = version + 1 WHERE request_id = $1 AND status = 'Open'",
        request_id,
        resolution,
        actor_id,
    )
