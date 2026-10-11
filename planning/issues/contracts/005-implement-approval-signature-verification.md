# [CONTRACTS] Implement approval signature verification

| Field | Value |
|---|---|
| **ID** | SC-005 |
| **Epic** | M04 · Smart Contracts |
| **Module** | `contracts` ([spec](../../../docs/modules/contracts/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | M (~1 day) |
| **Area** | contracts |
| **Status** | Ready for Review |
| **Traces to** | BR-001, BR-003, BR-004, FR-318 |
| **Blocks** | SC-006, SC-009, SC-017, SC-L02 |
| **Submission cut** | A |

## Context

This ticket belongs to the epic **Smart Contracts**. It supports:

- F-038: Invoice approval via EIP-712 signature

Problem behind this work (from `docs/FEATURES.md`):

- **F-038** solves: Approval is cryptographic and bound to exact fields, not a backend flag.

## Objective

The contract accepts a payment approval only if a current approver signed exactly these fields.

## Scope

- Library to hash PaymentApproval and recover the signer
- ERC-1271 support via SignatureChecker
- check signer is in the current approver set
- check approval expiry and that treasury equals this module

## Out of scope

Calling it from pay/refill (SC-006, SC-009).

## Technical notes

Reject signatures for another chain or contract through the domain separator.

## Dependencies

- SC-002: Define module storage, structs, EIP-712 domain, errors and events

## Acceptance criteria

- [ ] Valid signature by a current approver passes
- [ ] A changed field, wrong chain, wrong contract, removed approver or expired approval each revert with a distinct error

## Testing requirements

- Unit: one test per rejection reason
- fuzz on field mutations

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
