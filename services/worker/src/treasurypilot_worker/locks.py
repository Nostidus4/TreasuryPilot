"""PostgreSQL transaction-scoped coordination for treasury work."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Final
from uuid import UUID

import asyncpg  # type: ignore[import-untyped]

_LOCK_NAMESPACE: Final = "treasury"


def _asyncpg_database_url(database_url: str) -> str:
    """Accept either an asyncpg URL or the SQLAlchemy asyncpg URL used by Compose."""

    return database_url.replace("postgresql+asyncpg://", "postgresql://", 1)


@asynccontextmanager
async def treasury_advisory_xact_lock(
    pool: asyncpg.Pool,
    treasury_id: UUID | str,
) -> AsyncIterator[asyncpg.Connection | None]:
    """Try to hold one treasury's critical section for a whole DB transaction.

    ``None`` means another transaction owns the lock and the caller must skip or retry.
    The acquired lock is released by PostgreSQL when the context transaction exits,
    including when the worker is cancelled or raises.
    """

    lock_name = f"{_LOCK_NAMESPACE}:{treasury_id}"
    async with pool.acquire() as connection, connection.transaction():
        acquired = await connection.fetchval(
            "SELECT pg_try_advisory_xact_lock(hashtextextended($1, 0))",
            lock_name,
        )
        yield connection if acquired is True else None


async def create_worker_pool(
    database_url: str, *, min_size: int = 1, max_size: int = 10
) -> asyncpg.Pool:
    """Create the worker pool without leaking SQLAlchemy-specific URL syntax."""

    return await asyncpg.create_pool(
        dsn=_asyncpg_database_url(database_url),
        min_size=min_size,
        max_size=max_size,
    )
