from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from uuid import UUID

import pytest

from treasurypilot_worker.audit_anchor import (
    publish_daily_audit_roots,
    publish_snapshot,
)


class FakeChain:
    def __init__(self) -> None:
        self.roots: dict[tuple[UUID, int], bytes] = {}
        self.writes: list[tuple[UUID, int, bytes]] = []

    def anchor_or_confirm(self, org_id: UUID, utc_day: int, root: bytes) -> bool:
        existing = self.roots.get((org_id, utc_day))
        if existing is not None:
            return False
        self.roots[(org_id, utc_day)] = root
        self.writes.append((org_id, utc_day, root))
        return True


def test_daily_job_anchors_exact_repeatable_snapshot_and_is_idempotent() -> None:
    org_id = UUID("703199f4-37d8-4aeb-800e-3189fb9e0b01")
    captured_head = bytes.fromhex("a4" * 32)
    captured_at = datetime(2026, 10, 14, 0, 5, tzinfo=UTC)
    # This injected reader models the one REPEATABLE READ query in fetch_audit_heads.
    snapshots: list[Sequence[Mapping[str, object]]] = [
        [{"org_id": org_id, "last_hash": captured_head, "snapshot_at": captured_at}]
    ]

    async def read_snapshot(_database_url: str) -> list[Mapping[str, object]]:
        return list(snapshots[0])

    chain = FakeChain()
    first = asyncio.run(
        publish_daily_audit_roots("postgresql://test/db", chain, heads_reader=read_snapshot)
    )

    assert first == 1
    utc_day = int(captured_at.timestamp()) // 86_400
    assert chain.roots[(org_id, utc_day)] == captured_head
    assert chain.writes == [(org_id, utc_day, captured_head)]

    # A changed DB head later that day cannot overwrite the immutable first anchor.
    snapshots[0] = [
        {
            "org_id": org_id,
            "last_hash": bytes.fromhex("b5" * 32),
            "snapshot_at": captured_at,
        }
    ]
    second = asyncio.run(
        publish_daily_audit_roots("postgresql://test/db", chain, heads_reader=read_snapshot)
    )
    assert second == 0
    assert chain.roots[(org_id, utc_day)] == captured_head


def test_identical_existing_daily_anchor_is_a_noop() -> None:
    org_id = UUID("703199f4-37d8-4aeb-800e-3189fb9e0b01")
    root = bytes.fromhex("a4" * 32)
    chain = FakeChain()
    heads = [{"org_id": org_id, "last_hash": root}]

    assert publish_snapshot(heads, utc_day=20_000, chain=chain) == 1
    assert publish_snapshot(heads, utc_day=20_000, chain=chain) == 0
    assert chain.writes == [(org_id, 20_000, root)]


def test_invalid_snapshot_fails_before_any_chain_write() -> None:
    chain = FakeChain()
    with pytest.raises(ValueError, match="invalid audit head"):
        publish_snapshot(
            [{"org_id": UUID(int=1), "last_hash": b"short"}],
            utc_day=20_000,
            chain=chain,
        )
    assert chain.writes == []
