# [CONTRACTS] Publish EIP-712 golden vectors

| Field | Value |
|---|---|
| **ID** | SC-017 |
| **Epic** | M04 · Smart Contracts |
| **Module** | `contracts` ([spec](../../../docs/modules/contracts/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | S (≤ 0.5 day) |
| **Area** | contracts |
| **Status** | Ready for Assignment |
| **Traces to** | ADR-003, ADR-019 |
| **Blocks** | SC-L04, ENG-010 |
| **Submission cut** | A |

## Context

This ticket belongs to the epic **Smart Contracts**. It supports:

- F-038: Invoice approval via EIP-712 signature
- F-056: Plan attestation

Problem behind this work (from `docs/FEATURES.md`):

- **F-038** solves: Approval is cryptographic and bound to exact fields, not a backend flag.
- **F-056** solves: Prevents the payload being altered between validation and execution (plan drift).

## Objective

Python and TypeScript sign and hash exactly what the contract verifies.

## Scope

- contracts/test/vectors/*.json: PaymentApproval and signer-side PlanAttestation with canonical domains, struct hash, digest and signature
- Foundry test that checks them
- golden vectors for the 13-field PaymentApproval

## Out of scope

Python and TS consumers (ENG-010, WEB-009).

## Technical notes

M04-D3 removes OneTimeException typed signatures (governance only). PlanAttestation remains signer-side in M1 under the TreasuryPilot Policy domain (M08 section 6.3). No module PlanAttestation verifier is added.

## Dependencies

- SC-005: Implement approval signature verification

## Acceptance criteria

- [ ] Vectors verified by a Foundry test
- [ ] File format documented for the Python and TS tests
- [ ] PlanAttestation vectors cover a dynamic stepIds array and a nonce above JavaScript's safe-integer range
- [ ] Policy and approval domains cannot be interchanged

## Testing requirements

- Unit: vector verification

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
