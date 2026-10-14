from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from treasurypilot_api.treasury.models import Coverage
from treasurypilot_api.treasury.service import coverage_allows_execution, evaluate_coverage

NOW = datetime(2026, 10, 14, tzinfo=UTC)
MODULE = bytes.fromhex("11" * 20)
IMPLEMENTATION = bytes.fromhex("22" * 20)
FALLBACK = bytes.fromhex("33" * 20)
GUARD = bytes.fromhex("44" * 20)


def _fixture(
    *,
    modules: list[bytes] | None = None,
    target: str = "0x" + IMPLEMENTATION.hex(),
    guard: bytes | None = None,
    fallback: bytes = FALLBACK,
    observed_at: datetime = NOW,
) -> tuple[list[SimpleNamespace], dict[uuid.UUID, SimpleNamespace]]:
    wallet = SimpleNamespace(id=uuid.uuid4(), label="T")
    snapshot = SimpleNamespace(
        wallet_id=wallet.id,
        modules=modules or [MODULE],
        module_implementations={"0x" + MODULE.hex(): target},
        guard=guard,
        fallback_handler=fallback,
        observed_at=observed_at,
    )
    return [wallet], {wallet.id: snapshot}


def _evaluate(wallets: list[SimpleNamespace], snapshots: dict[uuid.UUID, SimpleNamespace]):
    return evaluate_coverage(
        wallets,
        snapshots,
        now=NOW,
        module_address=MODULE,
        module_implementation=IMPLEMENTATION,
        fallback_handler=FALLBACK,
    )


def test_exact_clone_without_guard_and_with_canonical_fallback_is_complete() -> None:
    wallets, snapshots = _fixture()

    result, details = _evaluate(wallets, snapshots)

    assert result is Coverage.COMPLETE
    assert "All registered Safes" in details[-1]


def test_extra_module_makes_coverage_partial() -> None:
    wallets, snapshots = _fixture(modules=[MODULE, bytes.fromhex("55" * 20)])

    result, _ = _evaluate(wallets, snapshots)

    assert result is Coverage.PARTIAL


def test_wrong_clone_target_guard_or_fallback_makes_coverage_partial() -> None:
    for overrides in (
        {"target": "0x" + bytes.fromhex("66" * 20).hex()},
        {"guard": GUARD},
        {"fallback": bytes.fromhex("77" * 20)},
    ):
        wallets, snapshots = _fixture(**overrides)
        result, _ = _evaluate(wallets, snapshots)
        assert result is Coverage.PARTIAL


def test_missing_or_stale_snapshot_is_unknown() -> None:
    wallets, snapshots = _fixture(observed_at=NOW - timedelta(minutes=13))

    result, _ = _evaluate(wallets, snapshots)

    assert result is Coverage.UNKNOWN


def test_missing_known_implementation_is_unknown() -> None:
    wallets, snapshots = _fixture()

    result, _ = evaluate_coverage(
        wallets,
        snapshots,
        now=NOW,
        module_address=MODULE,
        module_implementation=None,
        fallback_handler=FALLBACK,
    )

    assert result is Coverage.UNKNOWN


def test_execution_gate_fails_closed_for_unknown_and_unacknowledged_partial() -> None:
    assert not coverage_allows_execution(Coverage.UNKNOWN, acknowledged=True)
    assert not coverage_allows_execution(Coverage.PARTIAL, acknowledged=False)
    assert coverage_allows_execution(Coverage.PARTIAL, acknowledged=True)
    assert coverage_allows_execution(Coverage.COMPLETE, acknowledged=False)


def test_treasury_without_a_module_is_unknown_so_it_cannot_be_acknowledged() -> None:
    wallets, snapshots = _fixture()

    result, _ = evaluate_coverage(
        wallets,
        snapshots,
        now=NOW,
        module_address=None,
        module_implementation=IMPLEMENTATION,
        fallback_handler=FALLBACK,
    )

    assert result is Coverage.UNKNOWN
