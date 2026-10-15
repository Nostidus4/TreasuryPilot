"""Partial completion: resume or cancel a plan that stopped after some steps (RCV-003, BR-054).

``resume_partial`` only reopens the request (NeedsReview -> Preparing) and the plan
(PartiallyCompleted -> Executing). It sends nothing: the next ``sequence_plan`` call skips every
Confirmed step (their operation rows exist, so a refill is never repeated) and re-reads and
re-validates the first unfinished step with ``Gate.pre_step`` before signing it. The caller
(review action RETRY, the startup scan, unknown resolution) then enqueues
``treasurypilot.execution.sequence_plan``; the 15 s sweep also picks the plan up.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

import asyncpg  # type: ignore[import-untyped]

from treasurypilot_worker.executor.sequencer import _transition

ResumeStatus = Literal["Resumed", "NotPartial", "InFlight"]


@dataclass(frozen=True)
class ResumeResult:
    status: ResumeStatus
    plan_id: UUID | None = None


@dataclass(frozen=True)
class CancelReport:
    cancelled: bool
    plan_id: UUID | None = None
    completed_steps: tuple[str, ...] = ()  # 0x step ids
    # Cancel never reverses a step: whatever the confirmed steps moved stays where it is.
    funds_left_in_place: bool = False


async def resume_partial(pool: asyncpg.Pool, request_id: UUID) -> ResumeResult:
    """Reopen a request whose plan stopped part-way so only its unfinished steps run again."""

    async with pool.acquire() as connection, connection.transaction():
        plan_id = await connection.fetchval(
            "SELECT id FROM plans WHERE request_id = $1 AND status = 'PartiallyCompleted' "
            "FOR UPDATE",
            request_id,
        )
        if plan_id is None:
            return ResumeResult("NotPartial")
        # Unknown/in-flight operations are M12's to resolve first (BR-060); never re-send them.
        if await connection.fetchval(
            "SELECT 1 FROM operations WHERE request_id = $1 "
            "AND status IN ('Submitted', 'Pending', 'Unknown') LIMIT 1",
            request_id,
        ):
            return ResumeResult("InFlight", plan_id)
        if not await _transition(
            connection, request_id, "Preparing", ("NeedsReview",), "partial plan resumed"
        ):
            return ResumeResult("NotPartial", plan_id)
        await connection.execute(
            "UPDATE plans SET status = 'Executing', updated_at = now() WHERE id = $1", plan_id
        )
        # The stop's items are answered; a new stop must be able to open a fresh one.
        await connection.execute(
            "UPDATE review_items SET status = 'Resolved', resolution = 'RETRY', "
            "resolved_at = now(), version = version + 1 "
            "WHERE request_id = $1 AND status = 'Open'",
            request_id,
        )
    return ResumeResult("Resumed", plan_id)


async def cancel_partial(pool: asyncpg.Pool, request_id: UUID) -> CancelReport:
    """Cancel a stopped request and report which confirmed steps stay as they are."""

    async with pool.acquire() as connection, connection.transaction():
        if not await _transition(
            connection, request_id, "Cancelled", ("NeedsReview",), "partial plan cancelled"
        ):
            return CancelReport(False)
        plan_id = await connection.fetchval(
            "SELECT id FROM plans WHERE request_id = $1 AND status = 'PartiallyCompleted'",
            request_id,
        )
        done = tuple(
            "0x" + row["step_id"].hex()
            for row in await connection.fetch(
                "SELECT step_id FROM operations WHERE request_id = $1 AND status = 'Confirmed' "
                "ORDER BY created_at",
                request_id,
            )
        )
    return CancelReport(True, plan_id, done, funds_left_in_place=bool(done))
