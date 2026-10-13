from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Protocol

from redis.asyncio import Redis
from redis.exceptions import RedisError


class RateLimiterUnavailable(Exception):
    """The limiter backend could not be reached; auth endpoints fail closed."""


class RateLimiter(Protocol):
    async def hit(self, key: str, *, limit: int, window: timedelta) -> bool:
        """Count one attempt for ``key`` and return whether it is within ``limit``."""
        ...


class RedisRateLimiter:
    """Fixed-window counter shared by every API process."""

    def __init__(self, client: Redis, *, prefix: str = "tp:ratelimit:") -> None:
        self._client = client
        self._prefix = prefix

    async def hit(self, key: str, *, limit: int, window: timedelta) -> bool:
        redis_key = self._prefix + key
        try:
            async with self._client.pipeline(transaction=True) as pipeline:
                # Start the window only if the key is new, then count this attempt.
                pipeline.set(redis_key, 0, ex=int(window.total_seconds()), nx=True)
                pipeline.incr(redis_key)
                _, count = await pipeline.execute()
        except (RedisError, OSError) as exc:
            raise RateLimiterUnavailable from exc
        return int(count) <= limit

    async def aclose(self) -> None:
        await self._client.aclose()


class MemoryRateLimiter:
    """Single-process limiter for local development and tests."""

    def __init__(self, clock: Callable[[], datetime]) -> None:
        self._clock = clock
        self._windows: dict[str, tuple[datetime, int]] = {}

    async def hit(self, key: str, *, limit: int, window: timedelta) -> bool:
        now = self._clock()
        started, count = self._windows.get(key, (now, 0))
        if now - started >= window:
            started, count = now, 0
        self._windows[key] = (started, count + 1)
        return count + 1 <= limit
