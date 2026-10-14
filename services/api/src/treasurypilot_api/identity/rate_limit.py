from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from redis.asyncio import Redis
from redis.exceptions import RedisError


class RateLimiterUnavailable(Exception):
    """The limiter backend could not be reached; auth endpoints fail closed."""


@dataclass(frozen=True, slots=True)
class RateLimitResult:
    allowed: bool
    # Whole seconds until the current window resets (at least 1): the Retry-After value.
    retry_after: int


def _seconds_left(remaining_ms: float, window: timedelta) -> int:
    if remaining_ms <= 0:  # no TTL reported; fall back to the full window
        remaining_ms = window.total_seconds() * 1000
    return max(1, math.ceil(remaining_ms / 1000))


class RateLimiter(Protocol):
    async def hit(self, key: str, *, limit: int, window: timedelta) -> RateLimitResult:
        """Count one attempt for ``key``; report whether it is within ``limit`` and when
        the current window resets."""
        ...


class RedisRateLimiter:
    """Fixed-window counter shared by every API process."""

    def __init__(self, client: Redis, *, prefix: str = "tp:ratelimit:") -> None:
        self._client = client
        self._prefix = prefix

    async def hit(self, key: str, *, limit: int, window: timedelta) -> RateLimitResult:
        redis_key = self._prefix + key
        try:
            async with self._client.pipeline(transaction=True) as pipeline:
                # Start the window only if the key is new, count this attempt, and read
                # how long the (fixed) window still has to run.
                pipeline.set(redis_key, 0, ex=int(window.total_seconds()), nx=True)
                pipeline.incr(redis_key)
                pipeline.pttl(redis_key)
                _, count, remaining_ms = await pipeline.execute()
        except (RedisError, OSError) as exc:
            raise RateLimiterUnavailable from exc
        return RateLimitResult(int(count) <= limit, _seconds_left(int(remaining_ms), window))

    async def aclose(self) -> None:
        await self._client.aclose()


class MemoryRateLimiter:
    """Single-process limiter for local development and tests."""

    def __init__(self, clock: Callable[[], datetime]) -> None:
        self._clock = clock
        self._windows: dict[str, tuple[datetime, int]] = {}

    async def hit(self, key: str, *, limit: int, window: timedelta) -> RateLimitResult:
        now = self._clock()
        started, count = self._windows.get(key, (now, 0))
        if now - started >= window:
            started, count = now, 0
        self._windows[key] = (started, count + 1)
        # Clamp: a clock that moved backwards must not report more than one window.
        remaining = min(started + window - now, window)
        return RateLimitResult(
            count + 1 <= limit, _seconds_left(remaining.total_seconds() * 1000, window)
        )
