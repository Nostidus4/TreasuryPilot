"""Queue routing by treasury hash (NFR-SCAL-03).

With N shards each treasury maps to one ``core-<i>`` queue, so N single-consumer workers
(``celery worker -Q core-<i>``) scale out while a treasury's work stays on one consumer.
The per-treasury advisory lock (locks.py) remains the correctness guard; routing only
reduces contention. One shard (default) keeps the plain ``core`` queue.
"""

import hashlib
from uuid import UUID


def treasury_shard(treasury_id: UUID | str, shards: int) -> int:
    # sha256, not hash(): Python's str hash is salted per process.
    return int.from_bytes(hashlib.sha256(str(treasury_id).encode()).digest()[:8], "big") % shards


def shard_queues(shards: int) -> tuple[str, ...]:
    return ("core",) if shards <= 1 else tuple(f"core-{i}" for i in range(shards))


def treasury_queue(treasury_id: UUID | str, shards: int) -> str:
    return shard_queues(shards)[treasury_shard(treasury_id, max(shards, 1))]
