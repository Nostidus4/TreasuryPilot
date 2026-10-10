# [RECON] Publish on-chain payment attestations

| Field | Value |
|---|---|
| **ID** | REC-005 |
| **Epic** | M11 · Verification & Reconciliation |
| **Module** | `reconciliation` ([spec](../../../docs/modules/reconciliation/README.md)) |
| **Phase / Priority** | M1 / P2 |
| **Size** | S (≤ 0.5 day) |
| **Area** | backend |
| **Status** | Ready for Review |
| **Traces to** | FR-608 |
| **Blocks** | — |

## Context

This ticket belongs to the epic **Verification & Reconciliation**. It supports:

- F-074: On-chain payment attestation

Problem behind this work (from `docs/FEATURES.md`):

- **F-074** solves: Third-party-verifiable proof of payment (helps the on-chain bonus).

## Objective

A third party can verify a payment without access to the app.

## Scope

- Task that attests after Matched (or Paid by setting)
- store UID
- retry without affecting payment status

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- REC-003: Implement match, discrepancy and auto-match
- SC-019: Register the attestation schema and add an attest helper

## Acceptance criteria

- [ ] The UID resolves on the explorer
- [ ] The attestation contains no personal data

## Testing requirements

- Integration on testnet

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
