"""PlanAttestation issue and verification (M08 §6.3, POL-006). Signing keys and storage stay with callers."""

from __future__ import annotations

import secrets
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timedelta
from typing import Any

from eth_account.messages import encode_typed_data
from eth_account.signers.local import LocalAccount

from treasurypilot_core.eip712 import plan_attestation_typed_data, plan_hash, verify_signature
from treasurypilot_core.policy.decision import Decision
from treasurypilot_core.policy.reason_codes import PolicyReasonCode

ATTESTATION_TTL = timedelta(minutes=15)  # M08-D2
_POLICY_DOMAIN = "TreasuryPilot Policy"

# nonce -> the planHash it was first used with, or None if unseen (signer's attestation_uses).
NoncePlanHash = Callable[[int], str | None]


def _plan_hash(plan: Mapping[str, Any]) -> str:
    return (
        "0x" + plan_hash(plan["requestId"], plan["treasury"], plan["chainId"], plan["steps"]).hex()
    )


def attestation_typed_data(
    plan: Mapping[str, Any],
    decision: Decision,
    *,
    executor: str,
    evidence_digest: str,
    module: str,
    now: datetime,
) -> dict[str, Any]:
    """Typed data for a plan the validator allowed at stage PLAN; anything else is refused."""
    if decision.decision != "ALLOW" or decision.stage != "PLAN":
        raise ValueError(
            f"only ALLOW at stage PLAN is attested, got {decision.decision} at {decision.stage}"
        )
    steps: Sequence[Mapping[str, Any]] = plan["steps"]
    return plan_attestation_typed_data(
        {
            "planHash": _plan_hash(plan),
            "requestId": plan["requestId"],
            "stepIds": [step["stepId"] for step in steps],
            "policyVersion": "0x" + decision.policy_version.hex(),
            "executor": executor,
            "validUntil": int((now + ATTESTATION_TTL).timestamp()),
            "nonce": secrets.randbits(128),
            "evidenceDigest": evidence_digest,
        },
        chain_id=plan["chainId"],
        verifying_contract=module,
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
    trusted_signers: Sequence[str],
    now: datetime,
    nonce_plan_hash: NoncePlanHash,
) -> PolicyReasonCode | None:
    """The signer's attestation checks (§6.3 steps 1, 2, 4 and the nonce binding); None means valid.

    ``trusted_signers`` holds the current and previous policy address during a rotation.
    """
    message = typed_data["message"]
    if (
        typed_data.get("primaryType") != "PlanAttestation"
        or typed_data["domain"]["name"] != _POLICY_DOMAIN
        or not any(verify_signature(typed_data, signer, signature) for signer in trusted_signers)
    ):
        return PolicyReasonCode.ATTESTATION_INVALID
    if now.timestamp() > message["validUntil"]:
        return PolicyReasonCode.ATTESTATION_EXPIRED
    if (
        message["planHash"].lower() != _plan_hash(plan)
        or message["requestId"].lower() != plan["requestId"].lower()
        or [s.lower() for s in message["stepIds"]] != [s["stepId"].lower() for s in plan["steps"]]
        or int(typed_data["domain"]["chainId"]) != int(plan["chainId"])
    ):
        return PolicyReasonCode.ATTESTATION_INVALID
    seen = nonce_plan_hash(int(message["nonce"]))
    if seen is not None and seen.lower() != message["planHash"].lower():
        return PolicyReasonCode.NONCE_REUSED
    return None
