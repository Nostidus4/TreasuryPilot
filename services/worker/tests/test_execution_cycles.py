from __future__ import annotations

import asyncio
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

from treasurypilot_worker.trigger.cycles import (
    CycleSkipReason,
    RequestSelection,
    ScheduledRequest,
    run_execution_cycle,
)


class _Connection:
    def __init__(self, *, executing_plan: bool = False, **gates: bool) -> None:
        self.executing_plan = executing_plan
        self.gates = {
            "treasury_ready": True,
            "backend_paused": False,
            "mandate_active": True,
            "coverage_allowed": True,
            "unknown_operation": False,
            "executing_operation": False,
            **gates,
        }

    async def fetchrow(self, _query: str, *_args: object) -> dict[str, bool]:
        return self.gates

    async def fetchval(self, query: str, *_args: object) -> bool:
        if "to_regclass" in query:
            return self.executing_plan
        return self.executing_plan


class _Lock:
    def __init__(self, connection: _Connection) -> None:
        self.connection = connection
        self.held = False

    def for_treasury(self, _treasury_id: uuid.UUID) -> Any:
        @asynccontextmanager
        async def acquire() -> Any:
            if self.held:
                yield None
                return
            self.held = True
            try:
                yield self.connection
            finally:
                self.held = False

        return acquire()


class _Schedule:
    def __init__(self, request: ScheduledRequest) -> None:
        self.request = request
        self.calls = 0

    async def next_eligible_request(self, *_args: object, **_kwargs: object) -> RequestSelection:
        self.calls += 1
        return RequestSelection(self.request)


class _Starter:
    def __init__(self) -> None:
        self.calls = 0

    async def start(self, *_args: object, **_kwargs: object) -> bool:
        self.calls += 1
        await asyncio.sleep(0)
        return True


def test_paused_treasury_is_skipped_with_a_structured_reason() -> None:
    treasury_id = uuid.uuid4()
    lock = _Lock(_Connection(backend_paused=True))
    result = asyncio.run(
        run_execution_cycle(
            treasury_id,
            lock_for=lock.for_treasury,
            schedule_provider=None,
            plan_starter=None,
        )
    )

    assert not result.started
    assert result.reason is CycleSkipReason.BACKEND_PAUSED


def test_missing_exe004_provider_is_reported_after_gates_pass() -> None:
    result = asyncio.run(
        run_execution_cycle(
            uuid.uuid4(),
            lock_for=_Lock(_Connection()).for_treasury,
            schedule_provider=None,
            plan_starter=None,
        )
    )

    assert result.reason is CycleSkipReason.SCHEDULE_PROVIDER_UNAVAILABLE


def test_existing_executing_plan_blocks_another_cycle() -> None:
    result = asyncio.run(
        run_execution_cycle(
            uuid.uuid4(),
            lock_for=_Lock(_Connection(executing_plan=True)).for_treasury,
            schedule_provider=None,
            plan_starter=None,
        )
    )

    assert result.reason is CycleSkipReason.EXECUTING_PLAN_EXISTS


def test_nonblocking_lock_allows_only_one_callback_to_claim_a_request() -> None:
    treasury_id = uuid.uuid4()
    request = ScheduledRequest(uuid.uuid4(), datetime.now(UTC), 0)
    connection = _Connection()
    lock = _Lock(connection)
    schedule = _Schedule(request)
    starter = _Starter()

    async def exercise() -> tuple[Any, Any]:
        return await asyncio.gather(
            *(
                run_execution_cycle(
                    treasury_id,
                    lock_for=lock.for_treasury,
                    schedule_provider=schedule,
                    plan_starter=starter,
                )
                for _ in range(2)
            )
        )

    first, second = asyncio.run(exercise())

    assert sorted((first.reason, second.reason), key=lambda reason: str(reason)) == sorted(
        (None, CycleSkipReason.LOCK_BUSY), key=lambda reason: str(reason)
    )
    assert sum((first.started, second.started)) == 1
    assert starter.calls == 1
    assert schedule.calls == 1
