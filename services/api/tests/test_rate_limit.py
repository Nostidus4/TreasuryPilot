from __future__ import annotations

import asyncio
import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from redis.asyncio import Redis

from treasurypilot_api.identity.rate_limit import (
    MemoryRateLimiter,
    RateLimiterUnavailable,
    RateLimitResult,
    RedisRateLimiter,
)


def test_memory_limiter_resets_after_the_window() -> None:
    now = datetime(2026, 10, 12, tzinfo=UTC)
    limiter = MemoryRateLimiter(lambda: now)

    async def run() -> list[RateLimitResult]:
        return [await limiter.hit("k", limit=2, window=timedelta(minutes=15)) for _ in range(3)]

    results = asyncio.run(run())
    assert [result.allowed for result in results] == [True, True, False]
    assert results[-1].retry_after == 900


def test_redis_limiter_fails_closed_when_redis_is_unreachable() -> None:
    limiter = RedisRateLimiter(Redis.from_url("redis://127.0.0.1:1/0", socket_connect_timeout=0.2))

    async def run() -> None:
        try:
            await limiter.hit("k", limit=1, window=timedelta(minutes=15))
        finally:
            await limiter.aclose()

    with pytest.raises(RateLimiterUnavailable):
        asyncio.run(run())


@pytest.mark.skipif(
    "TP_TEST_REDIS_URL" not in os.environ,
    reason="TP_TEST_REDIS_URL is required for the Redis rate limiter test",
)
def test_redis_limiter_counts_within_a_shared_expiring_window() -> None:
    client = Redis.from_url(os.environ["TP_TEST_REDIS_URL"])
    limiter = RedisRateLimiter(client, prefix=f"test:{uuid.uuid4()}:")

    async def run() -> tuple[list[RateLimitResult], int]:
        try:
            results = [
                await limiter.hit("email", limit=2, window=timedelta(minutes=15)) for _ in range(3)
            ]
            ttl = await client.ttl(limiter._prefix + "email")
            return results, ttl
        finally:
            await limiter.aclose()

    results, ttl = asyncio.run(run())
    assert [result.allowed for result in results] == [True, True, False]
    assert all(1 <= result.retry_after <= 900 for result in results)
    assert 0 < ttl <= 15 * 60
