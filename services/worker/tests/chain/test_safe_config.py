from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

import pytest

from treasurypilot_worker.chain import safe_config as safe_config_module
from treasurypilot_worker.chain.rpc import RpcUnavailable, SafeConfig, decode_rpc_urls
from treasurypilot_worker.chain.safe_config import (
    _mark_coverage_unknown,
    _store_snapshot,
    publish_safe_config_changed,
    refresh_safe_config_snapshots,
)

ORG_ID = UUID("00000000-0000-7000-8000-000000000001")
TREASURY_ID = UUID("00000000-0000-7000-8000-000000000002")
WALLET_ID = UUID("00000000-0000-7000-8000-000000000003")
SAFE = "0x" + "11" * 20
OWNER_A = "0x" + "22" * 20
OWNER_B = "0x" + "33" * 20
MODULE = "0x" + "44" * 20
BLOCK_HASH = "0x" + "aa" * 32


@pytest.mark.parametrize(
    "rpc_urls",
    [
        ["https://rpc.example"],
        '["https://rpc.example"]',
    ],
)
def test_decode_rpc_urls_accepts_asyncpg_jsonb_shapes(rpc_urls: object) -> None:
    assert decode_rpc_urls(rpc_urls) == ["https://rpc.example"]


@pytest.mark.parametrize("rpc_urls", ["not-json", "[]", '[" "]', '["https://rpc.example", 3]'])
def test_decode_rpc_urls_rejects_invalid_config(rpc_urls: object) -> None:
    with pytest.raises(ValueError):
        decode_rpc_urls(rpc_urls)


NO_COVERAGE_ROW: dict[str, Any] = {
    "module_address": None,
    "module_implementation": None,
    "fallback_handler": None,
    "wallet_id": None,
    "label": None,
    "modules": None,
    "guard": None,
    "observed_fallback": None,
    "module_implementations": None,
    "observed_at": None,
}


class FakeConnection:
    def __init__(
        self,
        previous: dict[str, Any] | None,
        *,
        insert_result: str = "INSERT 0 1",
        fetch_rows: list[dict[str, Any]] | None = None,
        coverage_rows: list[dict[str, Any]] | None = None,
    ) -> None:
        self.coverage_rows = [dict(NO_COVERAGE_ROW)] if coverage_rows is None else coverage_rows
        self.previous = previous
        self.insert_result = insert_result
        self.executed: list[tuple[str, tuple[Any, ...]]] = []
        self.fetches: list[tuple[str, tuple[Any, ...]]] = []
        self.fetch_rows = fetch_rows or []

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

    async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
        self.fetches.append((query, args))
        return self.fetch_rows if "FROM treasury_wallets AS w" in query else self.coverage_rows


class FakePool:
    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection

    @asynccontextmanager
    async def acquire(self) -> AsyncIterator[FakeConnection]:
        yield self.connection

    async def close(self) -> None:
        return None


def snapshot(*, owners: tuple[str, ...] = (OWNER_A, OWNER_B), threshold: int = 2) -> SafeConfig:
    return SafeConfig(100, BLOCK_HASH, owners, threshold, (MODULE,), None, None, 0, (None,))


def previous_snapshot(config: SafeConfig) -> dict[str, Any]:
    return {
        "owners": list(config.owners),
        "threshold": config.threshold,
        "modules": [bytes.fromhex(module.removeprefix("0x")) for module in config.modules],
        "guard": None,
        "fallback_handler": None,
        "module_implementations": {MODULE: None},
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
    assert len(connection.executed) == 3  # wallet lock, snapshot insert and coverage update
    assert "TREASURY_MODULE_IMPLEMENTATION" in connection.fetches[0][0]
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


def test_rpc_read_failure_marks_coverage_unknown_and_clears_acknowledgment() -> None:
    connection = FakeConnection(None)

    asyncio.run(_mark_coverage_unknown(FakePool(connection), TREASURY_ID))

    query, args = connection.executed[0]
    assert "coverage = 'UNKNOWN'::treasury_coverage" in query
    assert "coverage_ack_by = NULL" in query
    assert args[0] == TREASURY_ID
    assert "RPC read failed" in args[1]


def test_rpc_failure_during_refresh_leaves_coverage_unknown(monkeypatch: Any) -> None:
    wallet = {
        "wallet_id": WALLET_ID,
        "org_id": ORG_ID,
        "treasury_id": TREASURY_ID,
        "safe_address": bytes.fromhex(SAFE.removeprefix("0x")),
        "rpc_urls": ["https://rpc.example"],
    }
    connection = FakeConnection(None, fetch_rows=[wallet])
    pool = FakePool(connection)

    async def create_pool(_url: str) -> FakePool:
        return pool

    class FailingReader:
        async def safe_config(self, _address: str) -> SafeConfig:
            raise RpcUnavailable("provider unavailable")

    monkeypatch.setattr(safe_config_module, "create_worker_pool", create_pool)

    assert (
        asyncio.run(
            refresh_safe_config_snapshots(
                "postgresql://test", reader_factory=lambda _urls: FailingReader()
            )
        )
        == 0
    )
    updates = [query for query, _ in connection.executed if "coverage = 'UNKNOWN'" in query]
    assert len(updates) == 2  # failure is marked immediately and again after the polling cycle


def _coverage_update(connection: FakeConnection) -> tuple[str, tuple[Any, ...]]:
    return next(item for item in connection.executed if "UPDATE treasuries" in item[0])


def test_partial_acknowledgment_is_cleared_when_coverage_details_change() -> None:
    connection = FakeConnection(None)

    asyncio.run(safe_config_module._refresh_coverage(connection, TREASURY_ID))

    query, _ = _coverage_update(connection)
    # The acknowledgment survives only a PARTIAL result with identical details.
    assert "$2 = 'PARTIAL' AND coverage_details = $3::jsonb" in query
    assert "OR ($2 <> 'PARTIAL'" not in query


def test_no_module_treasury_is_unknown_not_partial() -> None:
    connection = FakeConnection(None)

    asyncio.run(safe_config_module._refresh_coverage(connection, TREASURY_ID))

    _, args = _coverage_update(connection)
    assert args[1] == "UNKNOWN"
    assert "no registered Safes" in args[2]


def test_malformed_provider_response_marks_coverage_unknown(monkeypatch: Any) -> None:
    wallet = {
        "wallet_id": WALLET_ID,
        "org_id": ORG_ID,
        "treasury_id": TREASURY_ID,
        "safe_address": bytes.fromhex(SAFE.removeprefix("0x")),
        "rpc_urls": ["https://rpc.example"],
    }
    connection = FakeConnection(None, fetch_rows=[wallet])

    async def create_pool(_url: str) -> FakePool:
        return FakePool(connection)

    class MalformedReader:
        async def safe_config(self, _address: str) -> SafeConfig:
            raise KeyError("number")

    monkeypatch.setattr(safe_config_module, "create_worker_pool", create_pool)

    assert (
        asyncio.run(
            refresh_safe_config_snapshots(
                "postgresql://test", reader_factory=lambda _urls: MalformedReader()
            )
        )
        == 0
    )
    assert any("coverage = 'UNKNOWN'" in query for query, _ in connection.executed)


def test_duplicate_block_still_re_evaluates_coverage() -> None:
    connection = FakeConnection(None, insert_result="INSERT 0 0")

    asyncio.run(
        _store_snapshot(
            FakePool(connection),
            {"wallet_id": WALLET_ID, "org_id": ORG_ID, "treasury_id": TREASURY_ID},
            snapshot(),
            event_publisher=lambda *_: asyncio.sleep(0),
        )
    )

    _coverage_update(connection)
