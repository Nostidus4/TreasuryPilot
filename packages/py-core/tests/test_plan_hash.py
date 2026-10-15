from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from eth_hash.auto import keccak

from treasurypilot_core.eip712 import (
    PAY,
    PLAN_TYPE,
    REFILL,
    SUPPLY,
    WITHDRAW,
    liquidity_cycle_id,
    plan_hash,
    step_id,
)
from treasurypilot_core.money import BaseUnits
from treasurypilot_core.policy import Action, ExecutionPlan, PlanStep

VECTORS_DIR = Path(__file__).resolve().parents[3] / "contracts" / "test" / "vectors"
VECTORS = json.loads((VECTORS_DIR / "plan-hash.json").read_text())
PLANS = {plan["name"]: plan for plan in VECTORS["plans"]}


def _hash(plan: dict[str, Any]) -> str:
    steps = [
        {k: v for k, v in s.items() if k not in ("stepIdSource", "stepIdWallet")}
        for s in plan["steps"]
    ]
    return "0x" + plan_hash(plan["requestId"], plan["treasury"], plan["chainId"], steps).hex()


@pytest.mark.parametrize("name", PLANS)
def test_step_ids_match_the_typescript_oracle(name: str) -> None:
    for step in PLANS[name]["steps"]:
        key, action, wallet = step["stepIdSource"], step["action"], step["stepIdWallet"]
        assert "0x" + step_id(key, action, wallet).hex() == step["stepId"]


@pytest.mark.parametrize("name", PLANS)
def test_plan_hash_matches_the_typescript_oracle(name: str) -> None:
    assert _hash(PLANS[name]) == PLANS[name]["planHash"]


def test_plan_type_hash_matches_the_typescript_oracle() -> None:
    assert "0x" + keccak(PLAN_TYPE.encode()).hex() == VECTORS["planTypeHash"]


def test_the_same_plan_built_twice_has_the_same_hash() -> None:
    plan = PLANS["request"]
    assert _hash(json.loads(json.dumps(plan))) == _hash(plan) == plan["planHash"]


@pytest.mark.parametrize("name", PLANS)
def test_changing_any_field_changes_the_hash(name: str) -> None:
    original = PLANS[name]
    mutations: list[dict[str, Any]] = [
        {**original, "requestId": "0x" + "ab" * 32},
        {**original, "treasury": "0x" + "ab" * 20},
        {**original, "chainId": original["chainId"] + 1},
        {**original, "steps": original["steps"][:-1]},
    ]
    if len(original["steps"]) > 1:
        mutations.append({**original, "steps": original["steps"][::-1]})
    for i, step in enumerate(original["steps"]):
        for field, value in step.items():
            if field in ("stepIdSource", "stepIdWallet"):
                continue
            changed = (
                value[:-1] + ("1" if value[-1] == "0" else "0")
                if isinstance(value, str) and value.startswith("0x")
                else str(int(value) + 1)
            )
            steps = [*original["steps"]]
            steps[i] = {**step, field: changed}
            mutations.append({**original, "steps": steps})

    hashes = {_hash(m) for m in mutations}
    assert len(hashes) == len(mutations) and original["planHash"] not in hashes


def test_a_re_plan_of_the_remaining_steps_keeps_the_step_ids() -> None:
    plan = PLANS["request"]
    pay = plan["steps"][-1]
    # After WITHDRAW and REFILL ran, the re-plan holds only PAY (new seq) but must reuse its id.
    replanned = {
        **pay,
        "seq": 0,
        "stepId": "0x" + step_id(plan["requestId"], PAY, pay["stepIdWallet"]).hex(),
    }
    assert replanned["stepId"] == pay["stepId"]
    assert _hash({**plan, "steps": [replanned]}) != plan["planHash"]


def test_a_liquidity_step_id_is_keyed_on_a_cycle_id_that_retries_rebuild() -> None:
    plan = PLANS["liquidity"]
    cycle = plan["liquidityCycle"]
    rebuilt = liquidity_cycle_id(plan["treasury"], cycle["utcDay"], cycle["seq"])

    assert "0x" + rebuilt.hex() == plan["steps"][0]["stepIdSource"]
    assert liquidity_cycle_id(plan["treasury"], cycle["utcDay"], cycle["seq"] + 1) != rebuilt


def test_the_plan_treasury_is_the_module_clone_not_safe_t() -> None:
    approval = json.loads((VECTORS_DIR / "payment-approval.json").read_text())
    for plan in PLANS.values():
        assert plan["treasury"] == approval["domain"]["verifyingContract"]


def test_an_execution_plan_hashes_like_the_typescript_oracle() -> None:
    vector = PLANS["request"]
    actions = {WITHDRAW: Action.WITHDRAW, REFILL: Action.REFILL, PAY: Action.PAY}
    plan = ExecutionPlan(
        request_id=bytes.fromhex(vector["requestId"][2:]),
        treasury=vector["treasury"],
        chain_id=vector["chainId"],
        steps=[
            PlanStep(
                seq=s["seq"],
                step_id=bytes.fromhex(s["stepId"][2:]),
                action=actions[s["action"]],
                from_wallet=s["from"],
                to=s["to"],
                asset=s["asset"],
                amount=BaseUnits(int(s["amount"])),
            )
            for s in vector["steps"]
        ],
        planner_source="DETERMINISTIC",
        evidence_ids=[],
    )
    m = plan.message()

    assert (
        "0x" + plan_hash(m["requestId"], m["treasury"], m["chainId"], m["steps"]).hex()
        == (vector["planHash"])
    )


def test_a_liquidity_execution_plan_hashes_like_the_typescript_oracle() -> None:
    vector = PLANS["liquidity"]
    actions = {SUPPLY: Action.SUPPLY, WITHDRAW: Action.WITHDRAW}
    plan = ExecutionPlan(
        request_id=bytes.fromhex(vector["requestId"][2:]),
        treasury=vector["treasury"],
        chain_id=vector["chainId"],
        steps=[
            PlanStep(
                seq=s["seq"],
                step_id=bytes.fromhex(s["stepId"][2:]),
                action=actions[s["action"]],
                from_wallet=s["from"],
                to=s["to"],
                asset=s["asset"],
                amount=BaseUnits(int(s["amount"])),
            )
            for s in vector["steps"]
        ],
        planner_source="DETERMINISTIC",
        evidence_ids=[],
    )
    m = plan.message()

    assert (
        "0x" + plan_hash(m["requestId"], m["treasury"], m["chainId"], m["steps"]).hex()
        == vector["planHash"]
    )
