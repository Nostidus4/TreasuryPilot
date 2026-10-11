# [RECON] Publish on-chain payment attestations

| Field | Value |
|---|---|
| **ID** | REC-005 |
| **Epic** | M11 · Verification & Reconciliation |
| **Module** | `reconciliation` ([spec](../../../docs/modules/reconciliation/README.md)) |
| **Phase / Priority** | M1 / P1 |
| **Size** | S (≤ 0.5 day) |
| **Area** | backend |
| **Status** | Ready for Assignment |
| **Traces to** | FR-608, ADR-018, BR-074, M11-D8 |
| **Blocks** | — |
| **Submission cut** | A |

## Context

This ticket belongs to the epic **Verification & Reconciliation**. It supports:

- F-074: On-chain payment attestation

Problem behind this work (from `docs/FEATURES.md`):

- **F-074** solves: Third-party-verifiable proof of payment (helps the on-chain bonus).

## Objective

A third party can verify a payment without access to the app.

## Scope

- Task that attests as soon as the request is Paid and the PAY block is finalized (M11-D8, does not wait for matching)
- dedicated receipt key in the core worker with low-gas alert
- store attestation UID
- retry with backoff without affecting payment status
- easscan link in the request detail and evidence bundle

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- REC-002: Build reconciliation records with classification
- SC-019: Register the attestation schema and add an attest helper

## Acceptance criteria

- [ ] The UID resolves on easscan
- [ ] The attestation contains no personal data
- [ ] An EAS failure leaves the payment Paid and is retried

## Testing requirements

- Integration on testnet

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
