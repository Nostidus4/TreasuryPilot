"""Reliability run harness (DEV-009): run `demo-main` N times and write an evidence report.

`make reliability` runs it 30 times on Anvil and `TESTNET_RUNS` (default 0) times on Sepolia,
using the scenario runner (DEV-007). Per run it keeps status, a failure category, per-phase
latency (runner `phaseMs`) and the fee from receipts (gasUsed x effectiveGasPrice). Failed runs
are always listed with their category, never dropped. `main` exits 0 even when runs failed; the
CI grep on the report gates it. `tx:*` rows nest inside the step rows (e.g. refill_then_pay).
shortcut: demo-main's steps are Anvil-only (unlocked demo accounts, chain id 31337), so a testnet
run is attempted and recorded as a categorised failure until the runner can sign for Sepolia, so the
testnet section reads 0% by construction.
"""

from __future__ import annotations

import argparse
import os
import statistics
import sys
import tempfile
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scenario import REPO_ROOT, load_scenarios, run_scenario
from scenario_steps import ScenarioError

SCENARIO = "demo-main"
SEPOLIA_RPC_ENV = "TP_SEPOLIA_RPC_URL"


def categorize(error: BaseException) -> str:
    if isinstance(error, ScenarioError):
        text = str(error)
        if "cannot reach RPC" in text:
            return "RPC_UNREACHABLE"
        if "cannot read" in text:
            return "SETUP"
        if "chain" in text and ("refusing" in text or "targets" in text or "not in the" in text):
            return "CHAIN_MISMATCH"
        return "ASSERTION_FAILED"
    if isinstance(error, RuntimeError):
        return "RPC_ERROR"
    if isinstance(error, OSError):
        return "RPC_UNREACHABLE"
    return "UNEXPECTED"


def execute(scenario: dict[str, Any], n: int, **kwargs: Any) -> list[dict[str, Any]]:
    runs: list[dict[str, Any]] = []
    for i in range(1, n + 1):
        try:
            result = run_scenario(scenario, **kwargs)
            runs.append(
                {"n": i, "ok": True, "phaseMs": result["phaseMs"], "feeWei": result["feeWei"]}
            )
        except Exception as error:  # noqa: BLE001 - every failure is categorised, never dropped
            runs.append({"n": i, "ok": False, "category": categorize(error), "error": str(error)})
    return runs


def aggregate(runs: list[dict[str, Any]]) -> dict[str, Any]:
    passed = [r for r in runs if r["ok"]]
    phases: dict[str, list[float]] = {}
    for r in passed:
        for phase, ms in r["phaseMs"].items():
            phases.setdefault(phase, []).append(ms)
    fees = [r["feeWei"] for r in passed]
    return {
        "total": len(runs),
        "passed": len(passed),
        "completionPct": round(100 * len(passed) / len(runs), 1) if runs else None,
        "medianMs": {p: round(statistics.median(v), 1) for p, v in phases.items()},
        "medianFeeWei": int(statistics.median(fees)) if fees else None,
        "totalFeeWei": sum(fees),
        "failures": dict(Counter(r["category"] for r in runs if not r["ok"])),
    }


def render(sections: dict[str, list[dict[str, Any]]], date: str) -> str:
    out = [
        f"# Reliability report {date}",
        "",
        f"Scenario `{SCENARIO}`; fees in wei (gasUsed x effectiveGasPrice).",
        "",
    ]
    for label, runs in sections.items():
        a = aggregate(runs)
        out += [f"## {label}", ""]
        if not runs:
            out += ["Not run (0 runs requested).", ""]
            continue
        out += [
            f"- Runs: {a['total']}, completed: {a['passed']}, completion: {a['completionPct']}%",
            f"- Median fee per run: {a['medianFeeWei']} wei; total: {a['totalFeeWei']} wei",
            f"- Failure categories: {a['failures'] or 'none'}",
            "",
            "`tx:*` rows are individual transactions nested inside the step rows.",
            "",
            "| Phase | Median latency (ms) |",
            "|---|---|",
            *(f"| {p} | {ms} |" for p, ms in a["medianMs"].items()),
            "",
        ]
        failed = [r for r in runs if not r["ok"]]
        if failed:
            out += ["| Run | Category | Error |", "|---|---|---|"]
            out += [
                f"| {r['n']} | {r['category']} | {r['error'].replace('|', '/')[:200]} |"
                for r in failed
            ]
            out.append("")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--local-runs", type=int, default=30)
    parser.add_argument("--testnet-runs", type=int, default=0)
    parser.add_argument("--rpc-url", default="http://127.0.0.1:8545")
    parser.add_argument("--manifest", type=Path, default=REPO_ROOT / "deployments" / "31337.json")
    parser.add_argument("--out-dir", type=Path, default=REPO_ROOT / "docs" / "evidence")
    args = parser.parse_args(argv)
    sepolia_url = os.environ.get(SEPOLIA_RPC_ENV, "")
    if args.testnet_runs > 0 and not sepolia_url:
        print(
            f"error: --testnet-runs {args.testnet_runs} needs {SEPOLIA_RPC_ENV} (Sepolia RPC URL)",
            file=sys.stderr,
        )
        return 1
    try:
        scenario = load_scenarios(REPO_ROOT / "scenarios")[SCENARIO]
    except (ScenarioError, KeyError) as error:
        print(f"error: cannot load {SCENARIO}: {error}", file=sys.stderr)
        return 1
    with tempfile.TemporaryDirectory() as tmp:
        common = {"manifest_path": args.manifest, "out_dir": Path(tmp)}
        sections = {
            "Anvil (local)": execute(scenario, args.local_runs, rpc_url=args.rpc_url, **common),
            "Sepolia (testnet)": execute(
                scenario, args.testnet_runs, rpc_url=sepolia_url, **common
            ),
        }
    date = datetime.now(UTC).strftime("%Y-%m-%d")
    args.out_dir.mkdir(parents=True, exist_ok=True)
    path = args.out_dir / f"reliability-{date}.md"
    path.write_text(render(sections, date) + "\n")
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
