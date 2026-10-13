from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from eth_hash.auto import keccak

from treasurypilot_core.eip712 import PAY, PLAN_TYPE, plan_hash, step_id

VECTORS = json.loads(
    (
        Path(__file__).resolve().parents[3] / "contracts" / "test" / "vectors" / "plan-hash.json"
    ).read_text()
)
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
