"""Scenario runner (DEV-007): `scenario list` and `scenario run <name>`.

Scenarios are YAML files in `scenarios/`. A run refuses chains outside the allowlist (BR-095),
reports scenarios whose required capabilities are not wired yet as NOT_RUNNABLE instead of faking
them, and writes `run.json` plus an evidence-bundle.v1 file per run.
shortcut: the bundle is built locally from the scenario subject (a seeded TEST request) and the
chain transactions it produced, not read from the database; upgrade when the execution pipeline
persists scenario requests.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from eth_utils import keccak
from seed_local import ANVIL, rpc, sid

from treasurypilot_api import __version__
from treasurypilot_api.audit.evidence import (
    EvidenceBundle,
    TransactionEvidence,
    build_evidence_bundle,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
ALLOWED_CHAIN_IDS = frozenset({31337, 11155111})
# Capabilities wired in the platform but not yet driven by any step here; a scenario needing one is
# NOT_RUNNABLE. Unknown names (typos) are rejected at load time.
PENDING = frozenset(
    {
        "planner", "sequencer", "executor-pipeline", "ai-extraction", "outbox-recovery",
        "chain-reader-alerts", "fee-policy-runtime", "aave-adapter", "borrow-authorization",
    }
)  # fmt: skip
EXIT_FAILED, EXIT_NOT_RUNNABLE = 1, 2


class ScenarioError(Exception):
    """Bad scenario file, refused chain, or failed precondition."""


def load_scenarios(directory: Path) -> dict[str, dict[str, Any]]:
    scenarios: dict[str, dict[str, Any]] = {}
    for path in sorted(directory.glob("*.yaml")):
        data = yaml.safe_load(path.read_text())
        if not isinstance(data, dict) or data.get("name") != path.stem:
            raise ScenarioError(f"{path.name}: `name` must equal the file name")
        if type(data.get("chain_id")) is not int:
            raise ScenarioError(f"{path.name}: `chain_id` must be an integer")
        for key in ("requires", "must_show"):
            if not isinstance(data.get(key), list) or not data[key]:
                raise ScenarioError(f"{path.name}: `{key}` must be a non-empty list")
        check_declared_chain(data)  # before capabilities, so a NOT_RUNNABLE file cannot hide it
        if not set(data["requires"]) <= AVAILABLE | PENDING:
            unknown = sorted(set(data["requires"]) - AVAILABLE - PENDING)
            raise ScenarioError(f"{path.name}: unknown capability {unknown}")
        steps = data.get("steps", [])
        if not isinstance(steps, list) or not set(steps) <= set(STEPS):
            raise ScenarioError(f"{path.name}: unknown step in {steps}")
        if not missing_capabilities(data):
            if not steps:
                raise ScenarioError(f"{path.name}: a runnable scenario needs non-empty `steps`")
            provided = set().union(*(STEPS[step][1] for step in steps))
            if not set(data["requires"]) <= provided:
                raise ScenarioError(f"{path.name}: steps do not provide {data['requires']}")
        scenarios[data["name"]] = data
    return scenarios


def missing_capabilities(scenario: dict[str, Any]) -> list[str]:
    return [c for c in scenario["requires"] if c not in AVAILABLE]


def check_declared_chain(scenario: dict[str, Any]) -> None:
    if scenario["chain_id"] not in ALLOWED_CHAIN_IDS:
        raise ScenarioError(
            f"{scenario['name']}: chain id {scenario['chain_id']} is not in the scenario "
            f"allowlist {sorted(ALLOWED_CHAIN_IDS)}"
        )


def check_chain(scenario: dict[str, Any], rpc_url: str) -> int:
    """Refuse non-allowlisted chain ids, both declared and live."""
    check_declared_chain(scenario)
    declared = scenario["chain_id"]
    try:
        live = int(rpc(rpc_url, "eth_chainId", []), 16)
    except OSError as error:
        raise ScenarioError(f"cannot reach RPC at {rpc_url} ({error}); run `make dev`") from None
    if live not in ALLOWED_CHAIN_IDS:
        raise ScenarioError(
            f"refusing to run: RPC serves chain id {live}, allowed {sorted(ALLOWED_CHAIN_IDS)}"
        )
    if live != declared:
        raise ScenarioError(f"scenario targets chain {declared} but the RPC serves chain {live}")
    return live


def _module_status(rpc_url: str, module: str) -> int:
    data = "0x" + keccak(text="status()")[:4].hex()
    return int(rpc(rpc_url, "eth_call", [{"to": module, "data": data}, "latest"]), 16)


def step_guardian_pause(ctx: dict[str, Any]) -> dict[str, Any]:
    rpc_url, module = ctx["rpc_url"], ctx["manifest"]["module"]
    if ctx["chain_id"] != 31337:  # the guardian sender is an unlocked Anvil account
        raise ScenarioError(
            "guardian_pause needs a local Anvil (chain 31337) with unlocked accounts"
        )
    if rpc(rpc_url, "eth_getCode", [module, "latest"]) in ("0x", ""):
        raise ScenarioError(f"module {module} has no code; run `make deploy-local`")
    if _module_status(rpc_url, module) != 0:
        raise ScenarioError("module is not Active (already paused?); run `make deploy-local`")
    tx = rpc(
        rpc_url,
        "eth_sendTransaction",
        [{"from": ANVIL[3], "to": module, "data": "0x" + keccak(text="pause()")[:4].hex()}],
    )
    receipt = None
    for _ in range(50):  # Anvil may mine a moment after the send returns
        if (receipt := rpc(rpc_url, "eth_getTransactionReceipt", [tx])) is not None:
            break
        time.sleep(0.2)
    if receipt is None or receipt["status"] != "0x1":
        raise ScenarioError(f"pause transaction {tx} failed")
    ctx["transactions"].append(receipt)
    status = _module_status(rpc_url, module)
    if status != 1:
        raise ScenarioError(f"module status is {status} after pause, expected 1 (Paused)")
    return {"step": "guardian_pause", "txHash": tx, "moduleStatus": "Paused"}


# step name -> (function, capabilities it provides); AVAILABLE is derived from this.
STEPS = {"guardian_pause": (step_guardian_pause, frozenset({"anvil", "deployment"}))}
AVAILABLE = frozenset().union(*(caps for _, caps in STEPS.values()))


async def _bundle(
    ctx: dict[str, Any], name: str, operations: list[dict[str, Any]]
) -> EvidenceBundle:
    request_id = sid("request:INV-TEST-003")  # seeded TEST invoice, Approved, 800 tUSDC
    transactions = [
        {
            "tx_hash": r["transactionHash"],
            "chain_id": ctx["chain_id"],
            "block_number": int(r["blockNumber"], 16),
            "fee_base_units": str(int(r["gasUsed"], 16) * int(r["effectiveGasPrice"], 16)),
        }
        for r in ctx["transactions"]
    ]

    async def resolves(tx: TransactionEvidence) -> bool:
        receipt = await asyncio.to_thread(
            rpc, ctx["rpc_url"], "eth_getTransactionReceipt", [tx.tx_hash]
        )
        return receipt is not None and receipt["status"] == "0x1"

    return await build_evidence_bundle(
        organization_id=sid("org"),
        request_id=request_id,
        source={
            "request": {
                "id": request_id,
                "vendor_display_name": "Globex Services (TEST)",
                "amount": str(800 * 10**6),
                "currency": "tUSDC",
            },
            "operations": operations,
            "transactions": transactions,
            "coverage": {
                "scenario": name,
                "source": "scenario-runner",
                "note": "Subject request is a seeded TEST invoice; plan and approval not recorded.",
            },
            "fixture_labels": ["TEST", "SCENARIO"],
            "app_version": __version__,
        },
        transaction_resolves=resolves,
    )


def run_scenario(
    scenario: dict[str, Any], *, rpc_url: str, manifest_path: Path, out_dir: Path
) -> dict[str, Any]:
    name = scenario["name"]
    started = datetime.now(UTC)
    result: dict[str, Any] = {
        "scenario": name,
        "startedAt": started.isoformat(),
        "mustShow": scenario["must_show"],
    }
    check_declared_chain(scenario)
    if missing := missing_capabilities(scenario):
        return {**result, "status": "NOT_RUNNABLE", "missing": missing}
    ctx: dict[str, Any] = {"rpc_url": rpc_url, "transactions": []}
    ctx["chain_id"] = check_chain(scenario, rpc_url)
    try:
        ctx["manifest"] = json.loads(manifest_path.read_text())
    except (OSError, ValueError):
        raise ScenarioError(f"cannot read {manifest_path}; run `make deploy-local`") from None
    operations = [STEPS[step][0](ctx) for step in scenario.get("steps", [])]
    bundle = asyncio.run(_bundle(ctx, name, operations))
    run_dir = out_dir / f"{name}-{started:%Y%m%dT%H%M%SZ}"
    run_dir.mkdir(parents=True)
    text = bundle.model_dump_json(by_alias=True, exclude_none=True, indent=2)
    EvidenceBundle.model_validate_json(text)  # round-trip check before it is written
    (run_dir / "evidence-bundle.json").write_text(text + "\n")
    result |= {"status": "PASSED", "operations": operations, "bundleSha256": bundle.sha256}
    (run_dir / "run.json").write_text(json.dumps(result, indent=2) + "\n")
    return {**result, "runDir": str(run_dir)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenarios-dir", type=Path, default=REPO_ROOT / "scenarios")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list")
    run = sub.add_parser("run")
    run.add_argument("name")
    run.add_argument("--rpc-url", default="http://127.0.0.1:8545")
    run.add_argument("--manifest", type=Path, default=REPO_ROOT / "deployments" / "31337.json")
    run.add_argument("--out", type=Path, default=REPO_ROOT / "docs" / "evidence" / "scenarios")
    args = parser.parse_args(argv)
    try:
        scenarios = load_scenarios(args.scenarios_dir)
        if args.command == "list":
            for s in scenarios.values():
                state = "runnable" if not missing_capabilities(s) else "not runnable yet"
                print(f"{s['name']:20} {s['adr019']:6} chain {s['chain_id']}  {state}")
            return 0
        if args.name not in scenarios:
            raise ScenarioError(f"unknown scenario {args.name!r}; known: {', '.join(scenarios)}")
        result = run_scenario(
            scenarios[args.name],
            rpc_url=args.rpc_url,
            manifest_path=args.manifest,
            out_dir=args.out,
        )
    except (ScenarioError, OSError, RuntimeError) as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_FAILED
    print(json.dumps(result, indent=2))
    return EXIT_NOT_RUNNABLE if result["status"] == "NOT_RUNNABLE" else 0


if __name__ == "__main__":
    raise SystemExit(main())
