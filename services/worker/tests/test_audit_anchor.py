from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from types import SimpleNamespace
from uuid import UUID

import pytest
from celery.exceptions import Retry
from pydantic import SecretStr

from treasurypilot_worker import tasks
from treasurypilot_worker.audit_anchor import (
    Web3AuditRootChain,
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
    utc_day = 20_000
    # This injected reader models the one REPEATABLE READ query in fetch_audit_heads.
    snapshots: list[Sequence[Mapping[str, object]]] = [
        [{"org_id": org_id, "last_hash": captured_head}]
    ]

    async def read_snapshot(_database_url: str) -> list[Mapping[str, object]]:
        return list(snapshots[0])

    chain = FakeChain()
    first = asyncio.run(
        publish_daily_audit_roots(
            "postgresql://test/db", chain, utc_day=utc_day, heads_reader=read_snapshot
        )
    )

    assert first == 1
    assert chain.roots[(org_id, utc_day)] == captured_head
    assert chain.writes == [(org_id, utc_day, captured_head)]

    # A changed DB head later that day cannot overwrite the immutable first anchor.
    snapshots[0] = [{"org_id": org_id, "last_hash": bytes.fromhex("b5" * 32)}]
    second = asyncio.run(
        publish_daily_audit_roots(
            "postgresql://test/db", chain, utc_day=utc_day, heads_reader=read_snapshot
        )
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


def test_one_org_failure_does_not_stop_later_orgs_and_is_raised_at_the_end() -> None:
    first, second = UUID(int=1), UUID(int=2)
    root = bytes.fromhex("a4" * 32)
    chain = FakeChain()
    real = chain.anchor_or_confirm

    def flaky(org_id: UUID, utc_day: int, root: bytes) -> bool:
        if org_id == first:
            raise RuntimeError("https://user:secret@rpc.example reverted")
        return real(org_id, utc_day, root)

    chain.anchor_or_confirm = flaky  # type: ignore[method-assign]
    heads = [{"org_id": first, "last_hash": root}, {"org_id": second, "last_hash": root}]

    with pytest.raises(RuntimeError, match="1 of 2") as raised:
        publish_snapshot(heads, utc_day=20_000, chain=chain)
    assert "secret" not in str(raised.value)
    assert chain.writes == [(second, 20_000, root)]


class _Call:
    def __init__(self, value: object) -> None:
        self.value = value

    def call(self) -> object:
        return self.value


def _reverting_chain(anchored_after_revert: bool) -> Web3AuditRootChain:
    anchored = iter([False, anchored_after_revert])
    functions = SimpleNamespace(
        isAnchored=lambda *_: _Call(next(anchored)),
        anchorRoot=lambda *_: SimpleNamespace(
            build_transaction=lambda _tx: {},
            estimate_gas=lambda _tx: 1,
        ),
    )
    eth = SimpleNamespace(
        get_transaction_count=lambda *_: 0,
        chain_id=1,
        gas_price=1,
        send_raw_transaction=lambda _raw: b"",
        wait_for_transaction_receipt=lambda *_, **__: {"status": 0},
    )
    chain = Web3AuditRootChain.__new__(Web3AuditRootChain)
    chain.web3 = SimpleNamespace(eth=eth)  # type: ignore[assignment]
    chain.account = SimpleNamespace(
        address="0x0", sign_transaction=lambda _tx: SimpleNamespace(raw_transaction=b"")
    )
    chain.contract = SimpleNamespace(functions=functions)  # type: ignore[assignment]
    return chain


def test_revert_after_concurrent_anchor_is_a_noop() -> None:
    assert _reverting_chain(True).anchor_or_confirm(UUID(int=1), 20_000, bytes(32)) is False


def test_revert_without_anchor_fails() -> None:
    with pytest.raises(RuntimeError, match="reverted"):
        _reverting_chain(False).anchor_or_confirm(UUID(int=1), 20_000, bytes(32))


def test_task_retries_with_fixed_day_and_redacted_error(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = SimpleNamespace(
        database_url="postgresql://test/db",
        audit_anchor_rpc_url="https://user:secret@rpc.example",
        audit_anchor_chain_id=1,
        audit_anchor_contract_address="0x0",
        audit_anchor_private_key=SecretStr("k"),
    )
    monkeypatch.setattr(tasks, "get_settings", lambda: settings)

    def refuse(**_: object) -> None:
        raise ConnectionError("https://user:secret@rpc.example refused")

    monkeypatch.setattr(tasks, "Web3AuditRootChain", refuse)
    retries: list[dict[str, object]] = []

    def fake_retry(**kwargs: object) -> Exception:
        retries.append(kwargs)
        return Retry()  # type: ignore[no-any-return]

    monkeypatch.setattr(tasks.publish_daily_audit_roots_task, "retry", fake_retry)
    with pytest.raises(Retry):
        tasks.publish_daily_audit_roots_task.run(utc_day=20_000)

    assert retries[0]["args"] == (20_000,)
    assert "secret" not in str(retries[0]["exc"])
