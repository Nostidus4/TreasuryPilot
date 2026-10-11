# [ENGINE] Build EIP-712 typed data for approvals, exceptions and attestations

| Field | Value |
|---|---|
| **ID** | ENG-010 |
| **Epic** | M07 · Financial Engine (py-core) |
| **Module** | `financial-engine` ([spec](../../../docs/modules/financial-engine/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | M (~1 day) |
| **Area** | backend |
| **Status** | Ready for Review |
| **Traces to** | ADR-003 |
| **Blocks** | POL-002, POL-005, MDT-006, INV-010 |
| **Submission cut** | A |

## Context

This ticket belongs to the epic **Financial Engine (py-core)**. It supports:

- F-038: Invoice approval via EIP-712 signature
- F-025: One-time exception
- F-056: Plan attestation

Problem behind this work (from `docs/FEATURES.md`):

- **F-038** solves: Approval is cryptographic and bound to exact fields, not a backend flag.
- **F-025** solves: Occasional large payments without loosening the general mandate.
- **F-056** solves: Prevents the payload being altered between validation and execution (plan drift).

## Objective

Python produces and verifies the same digests as the contract.

## Scope

- Builders for the three typed structs
- verify_signature helpers including ERC-1271 call hook
- tests against the golden vectors

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Use eth-account. Never sign JSON directly.

## Dependencies

- SC-017: Publish EIP-712 golden vectors
- ENG-001: Create py-core money types and domain models

## Acceptance criteria

- [ ] All golden vectors pass
- [ ] A one-field mutation changes the digest

## Testing requirements

- Unit: vector tests

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
