# [CONTRACTS] Publish EIP-712 golden vectors

| Field | Value |
|---|---|
| **ID** | SC-017 |
| **Epic** | M04 · Smart Contracts |
| **Module** | `contracts` ([spec](../../../docs/modules/contracts/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | S (≤ 0.5 day) |
| **Area** | contracts |
| **Status** | Ready for Review |
| **Traces to** | ADR-003 |
| **Blocks** | SC-L04, ENG-010 |

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

- contracts/test/vectors/*.json: sample PaymentApproval, OneTimeException and PlanAttestation with domain, struct hash, digest and signature
- Foundry test that checks them

## Out of scope

Python and TS consumers (ENG-010, WEB-009).

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- SC-005: Implement approval signature verification

## Acceptance criteria

- [ ] Vectors verified by a Foundry test
- [ ] File format documented for the Python and TS tests

## Testing requirements

- Unit: vector verification

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
