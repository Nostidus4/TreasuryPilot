"""Align contract tickets with accepted M04/M08/ADR-019 decisions and their evidence."""

from ._base import TICKETS


def ticket(identifier):
    return next(item for item in TICKETS if item["id"] == identifier)


vectors = ticket("SC-017")
vectors["scope"][0] = (
    "contracts/test/vectors/*.json: PaymentApproval and signer-side PlanAttestation with canonical domains, struct hash, digest and signature"
)
vectors["notes"] = (
    "M04-D3 removes OneTimeException typed signatures (governance only). PlanAttestation remains signer-side in M1 under the TreasuryPilot Policy domain (M08 section 6.3). No module PlanAttestation verifier is added."
)
vectors["ac"] += [
    "PlanAttestation vectors cover a dynamic stepIds array and a nonce above JavaScript's safe-integer range",
    "Policy and approval domains cannot be interchanged",
]
signatures = ticket("SC-005")
signatures["ac"][1] = (
    "Changed fields, wrong chain and wrong contract revert ApprovalInvalid per M04 section 6.4; removed approver reverts NotApprover and expired approval reverts ApprovalExpired"
)
invariants = ticket("SC-014")
invariants["scope"] += [
    "P2 I15: borrow requires an unused, unexpired owner authorization",
    "Handler reuses successful stepIds with fresh requests and drives owner-authorized borrow/repay",
]
invariants["ac"] += [
    "I15 passes at 10k runs when P2 borrow execution is included",
    "Isolated step-guard and borrow-used-guard mutations fail I5 and I15 respectively",
]
deployment = ticket("SC-016")
deployment["scope"] = [
    value.replace(
        "enable module on T/O1/O2 via MultiSend",
        "enable module via MultiSend: T/O1/O2 locally, T/O1 in the Sepolia demo per ADR-019 V3-6",
    )
    for value in deployment["scope"]
]
deployment["ac"] += [
    "Publisher rejects reviewed chain, decimals, infrastructure and pinned aToken mismatches before modifying the manifest",
    "Sepolia demo operational list contains only O1; local tests keep O1/O2",
]
acceptance = ticket("SC-013")
acceptance["scope"] += ["Store forge gas report with compiler/profile/revision in CI evidence"]
acceptance["ac"] += ["CI uploads the gas report artifact"]
bypass = ticket("SC-020")
bypass["scope"] += [
    "Maintain C-rule to direct-call test and error-selector mapping in docs/security/contract-rule-test-mapping.md"
]
