from __future__ import annotations

import asyncio
import os
from contextlib import AbstractAsyncContextManager
from types import TracebackType
from uuid import uuid4

import pytest

from treasurypilot_worker.locks import create_worker_pool, treasury_advisory_xact_lock


class _FakeTransaction(AbstractAsyncContextManager[None]):
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc_value, traceback


class _FakeConnection:
    def __init__(self, acquired: bool) -> None:
        self.acquired = acquired
        self.query: str | None = None
        self.lock_name: str | None = None

    def transaction(self) -> _FakeTransaction:
        return _FakeTransaction()

    async def fetchval(self, query: str, lock_name: str) -> bool:
        self.query = query
        self.lock_name = lock_name
        return self.acquired


class _FakeAcquire(AbstractAsyncContextManager[_FakeConnection]):
    def __init__(self, connection: _FakeConnection) -> None:
        self.connection = connection

    async def __aenter__(self) -> _FakeConnection:
        return self.connection

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc_value, traceback


class _FakePool:
    def __init__(self, acquired: bool) -> None:
        self.connection = _FakeConnection(acquired)

    def acquire(self) -> _FakeAcquire:
        return _FakeAcquire(self.connection)


def test_lock_yields_connection_only_when_postgres_acquires_it() -> None:
    async def exercise() -> None:
        treasury_id = uuid4()
        acquired_pool = _FakePool(acquired=True)
        async with treasury_advisory_xact_lock(acquired_pool, treasury_id) as connection:  # type: ignore[arg-type]
            assert connection is acquired_pool.connection

        assert "pg_try_advisory_xact_lock" in (acquired_pool.connection.query or "")
        assert acquired_pool.connection.lock_name == f"treasury:{treasury_id}"

        contended_pool = _FakePool(acquired=False)
        async with treasury_advisory_xact_lock(contended_pool, treasury_id) as connection:  # type: ignore[arg-type]
            assert connection is None

    asyncio.run(exercise())


@pytest.mark.integration
def test_two_transactions_cannot_enter_same_treasury_critical_section() -> None:
    database_url = os.getenv("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("TEST_DATABASE_URL is required for the PostgreSQL lock contention test")

    async def exercise() -> None:
        pool = await create_worker_pool(database_url, min_size=2, max_size=2)
        treasury_id = uuid4()
        first_has_lock = asyncio.Event()
        release_first = asyncio.Event()

        async def hold_first_lock() -> None:
            async with treasury_advisory_xact_lock(pool, treasury_id) as connection:
                assert connection is not None
                first_has_lock.set()
                await release_first.wait()

        first = asyncio.create_task(hold_first_lock())
        await first_has_lock.wait()
        try:
            async with treasury_advisory_xact_lock(pool, treasury_id) as connection:
                assert connection is None
        finally:
            release_first.set()
            await first

        async with treasury_advisory_xact_lock(pool, treasury_id) as connection:
            assert connection is not None
        await pool.close()

    asyncio.run(exercise())
