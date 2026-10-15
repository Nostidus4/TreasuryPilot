from __future__ import annotations

import asyncio
import os
from collections import Counter
from uuid import UUID, uuid4

import pytest

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


@pytest.mark.integration
def test_workers_never_process_one_treasury_concurrently_under_load() -> None:
    database_url = os.getenv("TP_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("TP_TEST_DATABASE_URL is required for the PostgreSQL load test")

    treasuries = [uuid4() for _ in range(4)]
    jobs = [t for t in treasuries for _ in range(15)]
    active: Counter[UUID] = Counter()
    peak: Counter[UUID] = Counter()
    done: Counter[UUID] = Counter()

    async def worker(pool, queue: asyncio.Queue[UUID]) -> None:  # type: ignore[no-untyped-def]
        while not queue.empty():
            treasury_id = queue.get_nowait()
            while True:
                async with treasury_advisory_xact_lock(pool, treasury_id) as connection:
                    if connection is not None:
                        active[treasury_id] += 1
                        peak[treasury_id] = max(peak[treasury_id], active[treasury_id])
                        await asyncio.sleep(0.005)
                        active[treasury_id] -= 1
                        done[treasury_id] += 1
                        break
                await asyncio.sleep(0.002)  # contended: another worker owns this treasury

    async def exercise() -> None:
        # Each "worker" has its own pool, i.e. its own PostgreSQL sessions, like separate processes.
        pools = [await create_worker_pool(database_url, min_size=1, max_size=1) for _ in range(4)]
        queue: asyncio.Queue[UUID] = asyncio.Queue()
        for treasury_id in jobs:
            queue.put_nowait(treasury_id)
        try:
            await asyncio.gather(*(worker(pool, queue) for pool in pools))
        finally:
            for pool in pools:
                await pool.close()

    asyncio.run(exercise())
    assert all(done[t] == 15 for t in treasuries)
    assert max(peak.values()) == 1
