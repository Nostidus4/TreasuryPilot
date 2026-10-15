"""Deadline-driven execution-cycle orchestration (EXE-003).

The worker owns when a cycle is entered and its safety gates. EXE-004 owns the
schedule reader and planner consumer; the protocols here keep that dependency
small and deterministic while those durable models are still pending.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol

import asyncpg  # type: ignore[import-untyped]

logger = logging.getLogger(__name__)


class CycleSkipReason(StrEnum):
    LOCK_BUSY = "LOCK_BUSY"
    TREASURY_NOT_FOUND = "TREASURY_NOT_FOUND"
    TREASURY_NOT_READY = "TREASURY_NOT_READY"
    BACKEND_PAUSED = "BACKEND_PAUSED"
    MANDATE_INACTIVE = "MANDATE_INACTIVE"
    COVERAGE_INCOMPLETE = "COVERAGE_INCOMPLETE"
    UNKNOWN_OPERATION_PENDING = "UNKNOWN_OPERATION_PENDING"
    EXECUTING_PLAN_EXISTS = "EXECUTING_PLAN_EXISTS"
    SCHEDULE_PROVIDER_UNAVAILABLE = "SCHEDULE_PROVIDER_UNAVAILABLE"
    NO_ELIGIBLE_REQUEST = "NO_ELIGIBLE_REQUEST"
    PLANNER_UNAVAILABLE = "PLANNER_UNAVAILABLE"


@dataclass(frozen=True, slots=True)
class CycleGateState:
    treasury_ready: bool
    backend_paused: bool
    mandate_active: bool
    coverage_allowed: bool
    unknown_operation: bool
    executing_operation: bool


@dataclass(frozen=True, slots=True)
class ScheduledRequest:
    request_id: uuid.UUID
    scheduled_for: datetime
    order: int


@dataclass(frozen=True, slots=True)
class RequestSelection:
    candidate: ScheduledRequest | None
    skip_reason: CycleSkipReason = CycleSkipReason.NO_ELIGIBLE_REQUEST


@dataclass(frozen=True, slots=True)
class CycleResult:
    treasury_id: uuid.UUID
    started: bool
    reason: CycleSkipReason | None = None
    request_id: uuid.UUID | None = None


class CycleScheduleProvider(Protocol):
    async def next_eligible_request(
        self,
        connection: asyncpg.Connection,
        treasury_id: uuid.UUID,
        *,
        now: datetime,
    ) -> RequestSelection: ...


class PlanStarter(Protocol):
    async def start(
        self,
        connection: asyncpg.Connection,
        treasury_id: uuid.UUID,
        request: ScheduledRequest,
        *,
        now: datetime,
    ) -> bool: ...


class ScheduleWriter(Protocol):
    async def refresh_treasury(
        self,
        connection: asyncpg.Connection,
        treasury_id: uuid.UUID,
        *,
        now: datetime,
    ) -> bool: ...


LockFactory = Callable[[uuid.UUID], AbstractAsyncContextManager[asyncpg.Connection | None]]


_GATES_SQL = """
SELECT
    t.status = 'Ready' AS treasury_ready,
    (t.status = 'Paused' OR COALESCE(bp.paused, false)) AS backend_paused,
    EXISTS (
        SELECT 1 FROM mandate_versions mv
        WHERE mv.treasury_id = t.id
          AND mv.org_id = t.org_id
          AND mv.status = 'Active'
          AND mv.valid_from <= $2
          AND mv.expires_at > $2
    ) AS mandate_active,
    (t.coverage = 'COMPLETE' OR (
        t.coverage = 'PARTIAL'
        AND t.coverage_ack_by IS NOT NULL
        AND t.coverage_ack_at IS NOT NULL
        AND length(btrim(t.coverage_ack_reason)) > 0
    )) AS coverage_allowed,
    EXISTS (
        SELECT 1 FROM operations o
        WHERE o.treasury_id = t.id
          AND (o.status = 'Unknown' OR EXISTS (
              SELECT 1 FROM transactions tx
              WHERE tx.operation_id = o.id AND tx.status = 'Unknown'
          ))
    ) AS unknown_operation,
    EXISTS (
        SELECT 1 FROM operations o
        WHERE o.treasury_id = t.id
          AND o.status IN ('NotSubmitted', 'Submitted', 'Pending')
    ) AS executing_operation
FROM treasuries t
LEFT JOIN backend_pause bp ON bp.treasury_id = t.id
WHERE t.id = $1
"""


async def _read_gates(
    connection: asyncpg.Connection, treasury_id: uuid.UUID, *, now: datetime
) -> CycleGateState | None:
    row = await connection.fetchrow(_GATES_SQL, treasury_id, now)
    if row is None:
        return None
    executing_plan = False
    if await connection.fetchval("SELECT to_regclass('plans') IS NOT NULL"):
        executing_plan = bool(
            await connection.fetchval(
                "SELECT EXISTS (SELECT 1 FROM plans WHERE treasury_id = $1 "
                "AND status::text = 'Executing')",
                treasury_id,
            )
        )
    return CycleGateState(
        treasury_ready=bool(row["treasury_ready"]),
        backend_paused=bool(row["backend_paused"]),
        mandate_active=bool(row["mandate_active"]),
        coverage_allowed=bool(row["coverage_allowed"]),
        unknown_operation=bool(row["unknown_operation"]),
        executing_operation=bool(row["executing_operation"]) or executing_plan,
    )


def _gate_skip_reason(state: CycleGateState) -> CycleSkipReason | None:
    # Stable order makes the logged reason deterministic if multiple gates fail.
    if not state.treasury_ready:
        return CycleSkipReason.TREASURY_NOT_READY
    if state.backend_paused:
        return CycleSkipReason.BACKEND_PAUSED
    if not state.mandate_active:
        return CycleSkipReason.MANDATE_INACTIVE
    if not state.coverage_allowed:
        return CycleSkipReason.COVERAGE_INCOMPLETE
    if state.unknown_operation:
        return CycleSkipReason.UNKNOWN_OPERATION_PENDING
    if state.executing_operation:
        return CycleSkipReason.EXECUTING_PLAN_EXISTS
    return None


async def run_execution_cycle(
    treasury_id: uuid.UUID,
    *,
    lock_for: LockFactory,
    schedule_provider: CycleScheduleProvider | None,
    plan_starter: PlanStarter | None,
    now: datetime | None = None,
) -> CycleResult:
    """Run one treasury cycle under the nonblocking advisory lock.

    The lock covers gate reads, request selection, and the planner's idempotent
    claim/start callback. The callback must not perform slow RPC or LLM work while
    holding this transaction; it should persist/claim once and enqueue that work.
    """

    current = now or datetime.now(UTC)
    current = current.replace(tzinfo=UTC) if current.tzinfo is None else current.astimezone(UTC)
    async with lock_for(treasury_id) as connection:
        if connection is None:
            result = CycleResult(treasury_id, False, CycleSkipReason.LOCK_BUSY)
            _log_result(result)
            return result

        state = await _read_gates(connection, treasury_id, now=current)
        if state is None:
            result = CycleResult(treasury_id, False, CycleSkipReason.TREASURY_NOT_FOUND)
            _log_result(result)
            return result
        gate_reason = _gate_skip_reason(state)
        if gate_reason is not None:
            result = CycleResult(treasury_id, False, gate_reason)
            _log_result(result)
            return result
        if schedule_provider is None:
            result = CycleResult(treasury_id, False, CycleSkipReason.SCHEDULE_PROVIDER_UNAVAILABLE)
            _log_result(result)
            return result
        selection = await schedule_provider.next_eligible_request(
            connection, treasury_id, now=current
        )
        if selection.candidate is None:
            result = CycleResult(treasury_id, False, selection.skip_reason)
            _log_result(result)
            return result
        if plan_starter is None:
            result = CycleResult(treasury_id, False, CycleSkipReason.PLANNER_UNAVAILABLE)
            _log_result(result)
            return result
        if not await plan_starter.start(connection, treasury_id, selection.candidate, now=current):
            result = CycleResult(treasury_id, False, CycleSkipReason.EXECUTING_PLAN_EXISTS)
            _log_result(result)
            return result
        result = CycleResult(
            treasury_id,
            True,
            request_id=selection.candidate.request_id,
        )
        _log_result(result)
        return result


async def run_scheduling_cycle(
    treasury_id: uuid.UUID,
    *,
    lock_for: LockFactory,
    schedule_writer: ScheduleWriter | None,
    now: datetime | None = None,
) -> CycleResult:
    """Refresh the M07 schedule under the same nonblocking treasury lock."""

    current = now or datetime.now(UTC)
    current = current.replace(tzinfo=UTC) if current.tzinfo is None else current.astimezone(UTC)
    async with lock_for(treasury_id) as connection:
        if connection is None:
            result = CycleResult(treasury_id, False, CycleSkipReason.LOCK_BUSY)
        elif schedule_writer is None:
            result = CycleResult(treasury_id, False, CycleSkipReason.SCHEDULE_PROVIDER_UNAVAILABLE)
        elif await schedule_writer.refresh_treasury(connection, treasury_id, now=current):
            result = CycleResult(treasury_id, True)
        else:
            result = CycleResult(treasury_id, False, CycleSkipReason.TREASURY_NOT_READY)
    _log_result(result, cycle="scheduling")
    return result


def _log_result(result: CycleResult, *, cycle: str = "execution") -> None:
    fields: dict[str, object] = {
        "cycle": cycle,
        "treasury_id": str(result.treasury_id),
        "outcome": "started" if result.started else "skipped",
    }
    if result.reason is not None:
        fields["skip_reason"] = result.reason.value
    if result.request_id is not None:
        fields["request_id"] = str(result.request_id)
    logger.info("execution_cycle_result", extra=fields)
