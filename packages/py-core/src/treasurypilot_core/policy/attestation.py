"""PlanAttestation issue and verification (M08 §6.3, POL-006). Signing keys and storage stay with callers."""

from __future__ import annotations

import secrets
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timedelta
from typing import Any

from eth_account.messages import encode_typed_data
from eth_account.signers.local import LocalAccount

from treasurypilot_core.eip712 import (
    PAY,
    REFILL,
    SUPPLY,
    WITHDRAW,
    plan_attestation_typed_data,
    plan_hash,
    step_id,
    verify_signature,
)
from treasurypilot_core.policy.decision import Decision
from treasurypilot_core.policy.reason_codes import PolicyReasonCode

ATTESTATION_TTL = timedelta(minutes=15)  # M08-D2
_POLICY_DOMAIN = "TreasuryPilot Policy"
_ZERO_REQUEST_ID = "0x" + "00" * 32
# M08 §8.4 stepId wallet per action: the step's side that is the TreasuryPilot wallet.
_STEP_ID_WALLET = {PAY: "from", REFILL: "to", SUPPLY: "from", WITHDRAW: "to"}

# (nonce, planHash) -> the planHash the nonce is bound to after the call. The signer binds an
# unseen nonce atomically (INSERT ... ON CONFLICT DO NOTHING on a unique nonce, in the same
# transaction that records the signing) and returns the stored planHash.
BindNonce = Callable[[int, str], str]


def _plan_hash(plan: Mapping[str, Any]) -> str:
    return (
        "0x" + plan_hash(plan["requestId"], plan["treasury"], plan["chainId"], plan["steps"]).hex()
    )


def _aware(now: datetime) -> datetime:
    # A naive datetime's .timestamp() uses the host timezone and would move the expiry.
    if now.tzinfo is None:
        raise ValueError("now must carry a timezone")
    return now


def _check_step_ids(plan: Mapping[str, Any], liquidity_cycle_id: str | None) -> None:
    liquidity = plan["requestId"].lower() == _ZERO_REQUEST_ID
    if liquidity != (liquidity_cycle_id is not None):
        raise ValueError(
            "liquidity_cycle_id is required exactly for a liquidity plan (requestId 0x0)"
        )
    key = liquidity_cycle_id if liquidity_cycle_id is not None else plan["requestId"]
    for step in plan["steps"]:
        action = int(step["action"])
        if action not in _STEP_ID_WALLET:
            raise ValueError(f"step {step['seq']} has an action that plans cannot carry: {action}")
        expected = "0x" + step_id(key, action, step[_STEP_ID_WALLET[action]]).hex()
        if step["stepId"].lower() != expected:
            raise ValueError(f"stepId of step {step['seq']} does not follow M08 §8.4")


def attestation_typed_data(
    plan: Mapping[str, Any],
    decision: Decision,
    *,
    executor: str,
    evidence_digest: str,
    now: datetime,
    liquidity_cycle_id: str | None = None,
) -> dict[str, Any]:
    """Typed data for a plan the validator allowed at stage PLAN; anything else is refused.

    The domain's verifyingContract is ``plan["treasury"]``, the module clone.
    """
    if decision.decision != "ALLOW" or decision.stage != "PLAN":
        raise ValueError(
            f"only ALLOW at stage PLAN is attested, got {decision.decision} at {decision.stage}"
        )
    _check_step_ids(plan, liquidity_cycle_id)
    steps: Sequence[Mapping[str, Any]] = plan["steps"]
    return plan_attestation_typed_data(
        {
            "planHash": _plan_hash(plan),
            "requestId": plan["requestId"],
            "stepIds": [step["stepId"] for step in steps],
            # The contract checks the amount each step moves against this, not only the plan hash.
            "stepAmounts": [int(step["amount"]) for step in steps],
            "policyVersion": "0x" + decision.policy_version.hex(),
            "executor": executor,
            "validUntil": int((_aware(now) + ATTESTATION_TTL).timestamp()),
            "nonce": secrets.randbits(128),
            "evidenceDigest": evidence_digest,
        },
        chain_id=plan["chainId"],
        verifying_contract=plan["treasury"],
    )


def sign_attestation(typed_data: Mapping[str, Any], policy_key: LocalAccount) -> bytes:
    return bytes(
        policy_key.sign_message(encode_typed_data(full_message=dict(typed_data))).signature
    )


def verify_attestation(
    typed_data: Mapping[str, Any],
    signature: bytes,
    *,
    plan: Mapping[str, Any],
    executor: str,
    trusted_signers: Sequence[str],
    now: datetime,
    bind_nonce: BindNonce,
) -> PolicyReasonCode | None:
    """The signer's attestation checks (§6.3 steps 1, 2, 4 and the nonce binding); None means valid.

    The expected domain comes from ``plan`` (chainId, treasury = module clone), never from the
    attestation. ``trusted_signers`` holds the current and previous policy address during a
    rotation. ``bind_nonce`` runs last, only for an otherwise valid attestation.
    """
    message = typed_data["message"]
    domain = typed_data["domain"]
    if (
        typed_data.get("primaryType") != "PlanAttestation"
        or set(domain) != {"name", "version", "chainId", "verifyingContract"}
        or domain["name"] != _POLICY_DOMAIN
        or domain["version"] != "1"
        or int(domain["chainId"]) != int(plan["chainId"])
        or domain["verifyingContract"].lower() != plan["treasury"].lower()
        or not any(verify_signature(typed_data, signer, signature) for signer in trusted_signers)
    ):
        return PolicyReasonCode.ATTESTATION_INVALID
    if _aware(now).timestamp() > message["validUntil"]:
        return PolicyReasonCode.ATTESTATION_EXPIRED
    if (
        message["planHash"].lower() != _plan_hash(plan)
        or message["requestId"].lower() != plan["requestId"].lower()
        or [s.lower() for s in message["stepIds"]] != [s["stepId"].lower() for s in plan["steps"]]
        or [int(a) for a in message["stepAmounts"]] != [int(s["amount"]) for s in plan["steps"]]
        or message["executor"].lower() != executor.lower()
    ):
        return PolicyReasonCode.ATTESTATION_INVALID
    bound = bind_nonce(int(message["nonce"]), message["planHash"].lower())
    if bound.lower() != message["planHash"].lower():
        return PolicyReasonCode.NONCE_REUSED
    return None
