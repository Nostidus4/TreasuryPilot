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


@pytest.mark.parametrize(
    ("message", "category"),
    [
        ("cannot reach RPC at http://x (refused); run `make dev`", "RPC_UNREACHABLE"),
        ("demo-main: chain id 1 is not in the scenario allowlist [31337]", "CHAIN_MISMATCH"),
        ("scenario targets chain 31337 but the RPC serves chain 11155111", "CHAIN_MISMATCH"),
        ("cannot read /x/31337.json; run `make deploy-local`", "SETUP"),
        ("balance mismatch", "ASSERTION_FAILED"),
    ],
)
def test_categorize_real_scenario_errors(message: str, category: str) -> None:
    assert reliability.categorize(ScenarioError(message)) == category


def test_execute_keeps_failed_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = iter(range(1, 4))

    def fake(_scenario: dict[str, object], **_kw: object) -> dict[str, object]:
        if next(calls) == 2:
            raise ScenarioError("cannot reach RPC at x")
        return {"phaseMs": {"p": 1.0}, "feeWei": 5}

    monkeypatch.setattr(reliability, "run_scenario", fake)
    runs = reliability.execute({}, 3)
    assert len(runs) == 3
    assert [r["ok"] for r in runs] == [True, False, True]
    assert runs[1]["category"] == "RPC_UNREACHABLE"
