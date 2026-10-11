# [CONTRACTS] Add the duplicate-invoice fingerprint registry and owner override

| Field | Value |
|---|---|
| **ID** | SC-012 |
| **Epic** | M04 · Smart Contracts |
| **Module** | `contracts` ([spec](../../../docs/modules/contracts/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | S (≤ 0.5 day) |
| **Area** | contracts |
| **Status** | Ready for Assignment |
| **Traces to** | BR-071, FR-315 |
| **Blocks** | SC-013 |
| **Submission cut** | A |

## Context

This ticket belongs to the epic **Smart Contracts**. It supports:

- F-037: Duplicate-invoice fingerprint

Problem behind this work (from `docs/FEATURES.md`):

- **F-037** solves: The same invoice entered under two request IDs (a gap the source admits in UC-04).

## Objective

The same invoice cannot be paid twice under different request ids.

## Scope

- fingerprintPaid map set in pay()
- allowDuplicate(fingerprint, requestId) callable only by Safe T
- override consumed by exactly that request
- DuplicateAllowed event

## Out of scope

Fingerprint computation (off-chain, ENG-009).

## Technical notes

M04-D3: override is a governance call, not a flag inside the approval.

## Dependencies

- SC-006: Implement pay() core flow

## Acceptance criteria

- [ ] A second pay with the same fingerprint and a new request id reverts DuplicateFingerprint
- [ ] After allowDuplicate for request R, R can pay once and any other request still reverts

## Testing requirements

- Unit: duplicate and override tests

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
