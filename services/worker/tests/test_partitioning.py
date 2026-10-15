from __future__ import annotations

import asyncio
import os
from collections import Counter
from types import SimpleNamespace
from uuid import UUID, uuid4

import asyncpg
import pytest

from treasurypilot_worker import tasks
from treasurypilot_worker.config import get_settings
from treasurypilot_worker.locks import create_worker_pool, treasury_advisory_xact_lock
from treasurypilot_worker.routing import shard_queues, treasury_queue


def test_single_shard_keeps_core_queue() -> None:
    assert shard_queues(1) == ("core",)
    assert treasury_queue(uuid4(), 1) == "core"


def test_treasury_always_maps_to_same_shard_and_all_shards_are_used() -> None:
    fixed = UUID("12345678-1234-5678-1234-567812345678")
    assert treasury_queue(fixed, 4) == treasury_queue(str(fixed), 4)
    used = Counter(treasury_queue(uuid4(), 4) for _ in range(400))
    assert set(used) == set(shard_queues(4))


@pytest.fixture
def sharded(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    monkeypatch.setenv("TP_TREASURY_QUEUE_SHARDS", "4")
    get_settings.cache_clear()
    yield 4
    get_settings.cache_clear()


def test_core_queue_is_kept_next_to_shards(sharded: int) -> None:
    from treasurypilot_worker.celery_app import create_celery_app

    names = {q.name for q in create_celery_app().conf.task_queues}
    assert {"core", "ai", "webhooks", *shard_queues(sharded)} <= names


def test_every_treasury_scoped_producer_uses_its_shard(
    sharded: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    treasury, plan, event = uuid4(), uuid4(), uuid4()
    expected = treasury_queue(treasury, sharded)
    sent: list[tuple[str, str]] = []
    monkeypatch.setattr(tasks.app, "send_task", lambda name, **kw: sent.append((name, kw["queue"])))

    # tasks.py:329 publish_domain_events -> run_treasury_cycle
    async def fake_publish(connection, *, dispatch_execution_cycle):  # type: ignore[no-untyped-def]
        dispatch_execution_cycle(event, treasury)
        return 1

    class _Pool:
        def acquire(self):  # type: ignore[no-untyped-def]
            return self

        async def __aenter__(self) -> None:
            return None

        async def __aexit__(self, *_: object) -> None:
            return None

    monkeypatch.setenv("DATABASE_URL", "postgresql://unused")
    monkeypatch.setattr(
        "treasurypilot_worker.notify.publisher.publish_pending_events", fake_publish
    )
    monkeypatch.setattr(tasks._publisher, "run", lambda _url, work: asyncio.run(work(_Pool())))
    tasks.publish_domain_events()
    # plan_request starter
    tasks._enqueue_plan(plan, treasury)
    # tracker -> sequence_plan
    from treasurypilot_worker.tracker.track import _enqueue_sequencing

    monkeypatch.setattr(
        "treasurypilot_worker.celery_app.app.send_task",
        lambda name, **kw: sent.append((name, kw["queue"])),
    )
    _enqueue_sequencing(plan, treasury)
    assert sent == [
        ("treasurypilot.execution.run_treasury_cycle", expected),
        ("treasurypilot.planning.plan_request", expected),
        ("treasurypilot.execution.sequence_plan", expected),
    ]

    # resume_partial_task -> sequence_plan
    async def resumed(_action, _request, _actor):  # type: ignore[no-untyped-def]
        return SimpleNamespace(status="Resumed", plan_id=plan, treasury_id=treasury)

    applied: list[str] = []
    monkeypatch.setattr(tasks, "_partial_action", resumed)
    monkeypatch.setattr(
        tasks.sequence_plan_task, "apply_async", lambda args, queue: applied.append(queue)
    )
    tasks.resume_partial_task(str(uuid4()))
    assert applied == [expected]


def test_sequence_plans_sweep_enqueues_each_row_to_its_treasury_queue(
    sharded: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    rows = [{"plan_id": uuid4(), "treasury_id": uuid4()} for _ in range(12)]

    class _Pool:
        async def fetch(self, _sql: str) -> list[dict[str, UUID]]:
            return rows

        async def close(self) -> None:
            return None

    async def fake_pool(*_a: object, **_k: object) -> _Pool:
        return _Pool()

    applied: list[tuple[str, str]] = []
    monkeypatch.setenv("DATABASE_URL", "postgresql://unused")
    monkeypatch.setattr(tasks, "create_worker_pool", fake_pool)
    monkeypatch.setattr(
        tasks.sequence_plan_task,
        "apply_async",
        lambda args, queue: applied.append((args[0], queue)),
    )
    assert tasks.sequence_plans_sweep() == {"plans": 12}
    assert applied == [(str(r["plan_id"]), treasury_queue(r["treasury_id"], sharded)) for r in rows]
    assert len({q for _, q in applied}) > 1  # rows really spread over several shards


@pytest.mark.integration
def test_sharded_consumers_never_process_one_treasury_concurrently_under_load() -> None:
    database_url = os.getenv("TP_TEST_DATABASE_URL") or os.getenv("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("TP_TEST_DATABASE_URL is required for the PostgreSQL load test")

    shards, per_shard = 3, 2
    treasuries = [uuid4() for _ in range(9)]
    jobs_per_treasury = 15
    queues: dict[str, asyncio.Queue[UUID]] = {
        name: asyncio.Queue() for name in shard_queues(shards)
    }
    for treasury_id in treasuries:
        for _ in range(jobs_per_treasury):
            queues[treasury_queue(treasury_id, shards)].put_nowait(treasury_id)
    seen_on: dict[UUID, set[str]] = {t: set() for t in treasuries}
    active: Counter[UUID] = Counter()
    peak: Counter[UUID] = Counter()
    done: Counter[UUID] = Counter()

    async def consumer(pool: asyncpg.Pool, name: str) -> None:
        queue = queues[name]
        while not queue.empty():
            treasury_id = queue.get_nowait()
            seen_on[treasury_id].add(name)
            while True:
                async with treasury_advisory_xact_lock(pool, treasury_id) as connection:
                    if connection is not None:
                        active[treasury_id] += 1
                        peak[treasury_id] = max(peak[treasury_id], active[treasury_id])
                        await asyncio.sleep(0.005)
                        active[treasury_id] -= 1
                        done[treasury_id] += 1
                        break
                await asyncio.sleep(0.002)  # contended: another consumer owns this treasury

    async def exercise() -> None:
        # Every consumer has its own pool, i.e. its own PostgreSQL session, like a process.
        pools = [
            (name, await create_worker_pool(database_url, min_size=1, max_size=1))
            for name in queues
            for _ in range(per_shard)
        ]
        try:
            await asyncio.gather(*(consumer(pool, name) for name, pool in pools))
        finally:
            for _, pool in pools:
                await pool.close()

    asyncio.run(exercise())
    assert all(done[t] == jobs_per_treasury for t in treasuries)
    assert all(seen_on[t] == {treasury_queue(t, shards)} for t in treasuries)
    assert max(peak.values()) == 1
