from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from eth_account import Account

from treasurypilot_core.eip712 import payment_approval_typed_data
from treasurypilot_core.policy import Decision, PolicyReasonCode
from treasurypilot_core.policy.attestation import (
    attestation_typed_data,
    sign_attestation,
    verify_attestation,
)

VECTORS = Path(__file__).resolve().parents[3] / "contracts" / "test" / "vectors"
_PLANS = {p["name"]: p for p in json.loads((VECTORS / "plan-hash.json").read_text())["plans"]}
_REQUEST_PLAN = _PLANS["request"]


def _plan(vector: dict[str, Any]) -> dict[str, Any]:
    return {
        "requestId": vector["requestId"],
        "treasury": vector["treasury"],
        "chainId": vector["chainId"],
        "steps": [
            {k: v for k, v in s.items() if k not in ("stepIdSource", "stepIdWallet")}
            for s in vector["steps"]
        ],
    }


PLAN = _plan(_REQUEST_PLAN)
POLICY_KEY = Account.from_key(bytes(31) + b"\x08")  # public fixture identity 8
EXECUTOR = "0x22223333444455556666777788889999aaaabbbb"
NOW = datetime(2027, 1, 15, 9, 0, tzinfo=UTC)


def _decision(**changes: Any) -> Decision:
    fields: dict[str, Any] = {
        "decision": "ALLOW",
        "primary": None,
        "codes": [],
        "warnings": [],
        "checks": [],
        "stage": "PLAN",
        "step_seq": None,
        "policy_version": bytes.fromhex("11" * 32),
        "snapshot_block": 7,
    }
    return Decision(**{**fields, **changes})


def _attest(**overrides: Any) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "executor": EXECUTOR,
        "evidence_digest": "0x" + "ee" * 32,
        "now": NOW,
    }
    plan = overrides.pop("plan", PLAN)
    return attestation_typed_data(plan, _decision(), **{**kwargs, **overrides})


def _verify(typed: dict[str, Any], signature: bytes, **overrides: Any) -> object:
    kwargs: dict[str, Any] = {
        "plan": PLAN,
        "executor": EXECUTOR,
        "trusted_signers": [POLICY_KEY.address],
        "now": NOW,
        "bind_nonce": lambda nonce, plan_hash: plan_hash,
    }
    return verify_attestation(typed, signature, **{**kwargs, **overrides})


def test_an_allowed_plan_is_attested_for_fifteen_minutes_and_verifies() -> None:
    typed = _attest()
    message = typed["message"]

    assert message["planHash"] == _REQUEST_PLAN["planHash"]
    assert message["stepIds"] == [s["stepId"] for s in _REQUEST_PLAN["steps"]]
    assert message["validUntil"] == int((NOW + timedelta(minutes=15)).timestamp())
    assert typed["domain"]["verifyingContract"] == PLAN["treasury"]  # the module clone
    assert 0 <= message["nonce"] < 2**128
    assert message["nonce"] != _attest()["message"]["nonce"]
    assert _verify(typed, sign_attestation(typed, POLICY_KEY)) is None


def test_an_attestation_over_a_modified_plan_fails() -> None:
    typed = _attest()
    signature = sign_attestation(typed, POLICY_KEY)
    pay = {**PLAN["steps"][-1], "amount": str(int(PLAN["steps"][-1]["amount"]) + 1)}
    modified_plan = {**PLAN, "steps": [*PLAN["steps"][:-1], pay]}
    forged = {**typed, "message": {**typed["message"], "planHash": "0x" + "ab" * 32}}

    assert _verify(typed, signature, plan=modified_plan) is PolicyReasonCode.ATTESTATION_INVALID
    assert _verify(forged, signature) is PolicyReasonCode.ATTESTATION_INVALID


def test_an_expired_attestation_fails() -> None:
    typed = _attest()
    signature = sign_attestation(typed, POLICY_KEY)

    assert _verify(typed, signature, now=NOW + timedelta(minutes=15)) is None
    assert (
        _verify(typed, signature, now=NOW + timedelta(minutes=15, seconds=1))
        is PolicyReasonCode.ATTESTATION_EXPIRED
    )


def test_a_nonce_reused_for_a_different_plan_hash_is_rejected() -> None:
    typed = _attest()
    signature = sign_attestation(typed, POLICY_KEY)
    nonce, plan_hash = typed["message"]["nonce"], typed["message"]["planHash"]
    other: dict[int, str] = {nonce: "0x" + "ab" * 32}
    fresh: dict[int, str] = {}

    assert _verify(typed, signature, bind_nonce=other.setdefault) is PolicyReasonCode.NONCE_REUSED
    # The first use binds the nonce; the same attestation again (gas bump) still verifies.
    assert _verify(typed, signature, bind_nonce=fresh.setdefault) is None
    assert fresh == {nonce: plan_hash}
    assert _verify(typed, signature, bind_nonce=fresh.setdefault) is None


def test_an_approval_signature_never_verifies_as_an_attestation() -> None:
    approval = json.loads((VECTORS / "payment-approval.json").read_text())
    approval_typed = payment_approval_typed_data(
        approval["message"],
        chain_id=approval["domain"]["chainId"],
        verifying_contract=approval["domain"]["verifyingContract"],
    )
    approval_signature = bytes.fromhex(approval["signature"][2:])
    typed = _attest()
    # Same message under the approval domain name, signed by a trusted key.
    approval_domain = {**typed, "domain": {**typed["domain"], "name": "TreasuryPilot"}}
    trusted = [POLICY_KEY.address, approval["signer"]]

    assert (
        _verify(approval_typed, approval_signature, trusted_signers=trusted)
        is PolicyReasonCode.ATTESTATION_INVALID
    )
    assert (
        _verify(typed, approval_signature, trusted_signers=trusted)
        is PolicyReasonCode.ATTESTATION_INVALID
    )
    assert (
        _verify(approval_domain, sign_attestation(approval_domain, POLICY_KEY))
        is PolicyReasonCode.ATTESTATION_INVALID
    )


def test_both_rotation_keys_verify_and_any_other_key_fails() -> None:
    new_key = Account.from_key(bytes(31) + b"\x09")
    typed = _attest()
    old_signature = sign_attestation(typed, POLICY_KEY)
    rotating = [new_key.address, POLICY_KEY.address]

    assert _verify(typed, old_signature, trusted_signers=rotating) is None
    assert _verify(typed, sign_attestation(typed, new_key), trusted_signers=rotating) is None
    assert (
        _verify(typed, old_signature, trusted_signers=[new_key.address])
        is PolicyReasonCode.ATTESTATION_INVALID
    )


def _failing(decision: str, code: str) -> dict[str, Any]:
    check = {"name": code, "passed": False, "code": code, "expected": None, "observed": None}
    return {"decision": decision, "primary": code, "codes": [code], "checks": [check]}


@pytest.mark.parametrize(
    "changes",
    [
        _failing("NEEDS_APPROVAL", "OVER_PER_REQUEST_LIMIT"),
        _failing("BLOCK", "SNAPSHOT_STALE"),
        {"stage": "PRE_STEP", "step_seq": 0},
    ],
)
def test_only_an_allow_at_stage_plan_is_attested(changes: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match="only ALLOW at stage PLAN"):
        attestation_typed_data(
            PLAN,
            _decision(**changes),
            executor=EXECUTOR,
            evidence_digest="0x" + "ee" * 32,
            now=NOW,
        )


def test_an_attestation_only_verifies_for_its_own_module_domain_and_executor() -> None:
    typed = _attest()
    other_module = {**typed, "domain": {**typed["domain"], "verifyingContract": "0x" + "ab" * 20}}
    other_version = {**typed, "domain": {**typed["domain"], "version": "2"}}

    for forged in (other_module, other_version):
        assert (
            _verify(forged, sign_attestation(forged, POLICY_KEY))
            is PolicyReasonCode.ATTESTATION_INVALID
        )
    assert (
        _verify(typed, sign_attestation(typed, POLICY_KEY), executor="0x" + "ab" * 20)
        is PolicyReasonCode.ATTESTATION_INVALID
    )


def test_a_step_id_that_does_not_follow_section_8_4_is_never_attested() -> None:
    pay = {**PLAN["steps"][-1], "stepId": "0x" + "ab" * 32}

    with pytest.raises(ValueError, match="stepId of step 2"):
        _attest(plan={**PLAN, "steps": [*PLAN["steps"][:-1], pay]})


def test_a_liquidity_plan_is_attested_with_its_cycle_id() -> None:
    vector = _PLANS["liquidity"]
    plan = _plan(vector)
    cycle_id = vector["steps"][0]["stepIdSource"]

    typed = _attest(plan=plan, liquidity_cycle_id=cycle_id)
    assert typed["message"]["planHash"] == vector["planHash"]
    assert _verify(typed, sign_attestation(typed, POLICY_KEY), plan=plan) is None
    with pytest.raises(ValueError, match="liquidity_cycle_id"):
        _attest(plan=plan)
    with pytest.raises(ValueError, match="liquidity_cycle_id"):
        _attest(liquidity_cycle_id=cycle_id)


def test_a_naive_clock_is_refused() -> None:
    naive = datetime(2027, 1, 15, 9, 0)
    typed = _attest()

    with pytest.raises(ValueError, match="timezone"):
        _attest(now=naive)
    with pytest.raises(ValueError, match="timezone"):
        _verify(typed, sign_attestation(typed, POLICY_KEY), now=naive)
