from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))
import reliability  # noqa: E402
from scenario_steps import ScenarioError  # noqa: E402


def ok(n: int, ms: float, fee: int) -> dict[str, object]:
    return {"n": n, "ok": True, "phaseMs": {"refill_then_pay": ms}, "feeWei": fee}


def bad(n: int, category: str) -> dict[str, object]:
    return {"n": n, "ok": False, "category": category, "error": "boom | x"}


def test_aggregate_counts_completion_median_and_failures() -> None:
    runs = [
        ok(1, 10, 100),
        ok(2, 30, 300),
        ok(3, 20, 200),
        bad(4, "RPC_ERROR"),
        bad(5, "RPC_ERROR"),
    ]
    a = reliability.aggregate(runs)
    assert (a["total"], a["passed"], a["completionPct"]) == (5, 3, 60.0)
    assert a["medianMs"] == {"refill_then_pay": 20} and a["medianFeeWei"] == 200
    assert a["failures"] == {"RPC_ERROR": 2}


def test_render_lists_every_failed_run_with_category() -> None:
    text = reliability.render(
        {"Anvil": [ok(1, 5, 1), bad(2, "ASSERTION_FAILED")], "Sepolia": []}, "d"
    )
    assert "completion: 50.0%" in text and "| 2 | ASSERTION_FAILED | boom / x |" in text
    assert "Not run" in text


def test_categorize() -> None:
    assert reliability.categorize(ScenarioError("expected X")) == "ASSERTION_FAILED"
    assert (
        reliability.categorize(ScenarioError("refusing to run: RPC serves chain id 1"))
        == "CHAIN_MISMATCH"
    )
    assert reliability.categorize(RuntimeError("rpc")) == "RPC_ERROR"
    assert reliability.categorize(ConnectionError()) == "RPC_UNREACHABLE"
    assert reliability.categorize(KeyError("x")) == "UNEXPECTED"


def test_testnet_runs_without_rpc_credentials_fail_fast(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv(reliability.SEPOLIA_RPC_ENV, raising=False)
    assert reliability.main(["--testnet-runs", "2"]) == 1
    assert reliability.SEPOLIA_RPC_ENV in capsys.readouterr().err
