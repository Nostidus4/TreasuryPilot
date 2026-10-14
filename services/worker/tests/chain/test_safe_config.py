from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

from treasurypilot_worker.chain.rpc import SafeConfig
from treasurypilot_worker.chain.safe_config import (
    _store_snapshot,
    publish_safe_config_changed,
)

ORG_ID = UUID("00000000-0000-7000-8000-000000000001")
TREASURY_ID = UUID("00000000-0000-7000-8000-000000000002")
WALLET_ID = UUID("00000000-0000-7000-8000-000000000003")
SAFE = "0x" + "11" * 20
OWNER_A = "0x" + "22" * 20
OWNER_B = "0x" + "33" * 20
MODULE = "0x" + "44" * 20
BLOCK_HASH = "0x" + "aa" * 32


class FakeConnection:
    def __init__(
        self, previous: dict[str, Any] | None, *, insert_result: str = "INSERT 0 1"
    ) -> None:
        self.previous = previous
        self.insert_result = insert_result
        self.executed: list[tuple[str, tuple[Any, ...]]] = []

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        yield

    async def execute(self, query: str, *args: Any) -> str:
        self.executed.append((query, args))
        if query.startswith("\n            INSERT INTO safe_config_snapshots"):
            return self.insert_result
        return "SELECT 1"

    async def fetchrow(self, query: str, *args: Any) -> dict[str, Any] | None:
        del query, args
        return self.previous


class FakePool:
    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection

    @asynccontextmanager
    async def acquire(self) -> AsyncIterator[FakeConnection]:
        yield self.connection


def snapshot(*, owners: tuple[str, ...] = (OWNER_A, OWNER_B), threshold: int = 2) -> SafeConfig:
    return SafeConfig(100, BLOCK_HASH, owners, threshold, (MODULE,), None, None, 0)


def previous_snapshot(config: SafeConfig) -> dict[str, Any]:
    return {
        "owners": list(config.owners),
        "threshold": config.threshold,
        "modules": [bytes.fromhex(module.removeprefix("0x")) for module in config.modules],
        "guard": None,
        "block_number": 99,
        "block_hash": bytes.fromhex("bb" * 32),
    }


def test_snapshot_and_safe_config_changed_event_are_written_together() -> None:
    connection = FakeConnection(previous_snapshot(snapshot()))
    events: list[dict[str, Any]] = []

    async def publish(_connection: Any, payload: dict[str, Any]) -> None:
        events.append(payload)

    result = asyncio.run(
        _store_snapshot(
            FakePool(connection),
            {"wallet_id": WALLET_ID, "org_id": ORG_ID, "treasury_id": TREASURY_ID},
            snapshot(owners=(OWNER_A, OWNER_B, SAFE)),
            event_publisher=publish,
        )
    )

    assert result == 1
    assert len(connection.executed) == 2  # wallet lock and snapshot insert
    assert events == [
        {
            "type": "SafeConfigChanged",
            "orgId": str(ORG_ID),
            "treasuryId": str(TREASURY_ID),
            "walletId": str(WALLET_ID),
            "blockNumber": 100,
        }
    ]


def test_initial_snapshot_does_not_emit_a_change_event() -> None:
    connection = FakeConnection(None)
    events: list[dict[str, Any]] = []

    async def publish(_connection: Any, payload: dict[str, Any]) -> None:
        events.append(payload)

    asyncio.run(
        _store_snapshot(
            FakePool(connection),
            {"wallet_id": WALLET_ID, "org_id": ORG_ID, "treasury_id": TREASURY_ID},
            snapshot(),
            event_publisher=publish,
        )
    )

    assert events == []


def test_duplicate_block_snapshot_does_not_emit_a_change_event() -> None:
    connection = FakeConnection(previous_snapshot(snapshot()), insert_result="INSERT 0 0")
    events: list[dict[str, Any]] = []

    async def publish(_connection: Any, payload: dict[str, Any]) -> None:
        events.append(payload)

    result = asyncio.run(
        _store_snapshot(
            FakePool(connection),
            {"wallet_id": WALLET_ID, "org_id": ORG_ID, "treasury_id": TREASURY_ID},
            snapshot(owners=(OWNER_A, OWNER_B, SAFE)),
            event_publisher=publish,
        )
    )

    assert result == 0
    assert events == []


def test_default_event_publisher_emits_commit_scoped_postgres_notification() -> None:
    connection = FakeConnection(None)
    payload = {"type": "SafeConfigChanged", "walletId": str(WALLET_ID)}

    asyncio.run(publish_safe_config_changed(connection, payload))

    query, args = connection.executed[0]
    assert "pg_notify('safe_config_changed', $1)" in query
    assert '"type": "SafeConfigChanged"' in args[0]
