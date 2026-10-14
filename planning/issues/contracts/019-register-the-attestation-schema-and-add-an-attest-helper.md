# [CONTRACTS] Register the attestation schema and add an attest helper

| Field | Value |
|---|---|
| **ID** | SC-019 |
| **Epic** | M04 · Smart Contracts |
| **Module** | `contracts` ([spec](../../../docs/modules/contracts/README.md)) |
| **Phase / Priority** | M1 / P1 |
| **Size** | S (≤ 0.5 day) |
| **Area** | contracts |
| **Status** | Ready for Assignment |
| **Traces to** | FR-608, ADR-018, PH-11 |
| **Blocks** | REC-005 |
| **Submission cut** | A |

## Context

This ticket belongs to the epic **Smart Contracts**. It supports:

- F-074: On-chain payment attestation

Problem behind this work (from `docs/FEATURES.md`):

- **F-074** solves: Third-party-verifiable proof of payment (helps the on-chain bonus).

## Objective

Publish a verifiable on-chain record for each paid request.

## Scope

- EAS schema 'TreasuryPilot Payment Receipt v1' (requestId, invoiceHash, approvalHash, planHash, payTxHash, payee, amount, policyVersion), non-revocable
- script to register it on Sepolia
- Python attest helper
- schema UID in the manifest

## Out of scope

Worker integration (REC-005).

## Technical notes

ADR-018. Only hashes and addresses — no personal data.

## Dependencies

- DOM-001: Verify Ethereum Sepolia infrastructure (owner: Nostidus4)

## Acceptance criteria

- [ ] Schema UID recorded in the deployments manifest
- [ ] A sample attestation resolves on easscan (Sepolia)
- [ ] The helper refuses any field that is not in the schema

## Testing requirements

- Integration: testnet smoke

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
