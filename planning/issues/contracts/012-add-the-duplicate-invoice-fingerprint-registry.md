# [CONTRACTS] Add the duplicate-invoice fingerprint registry

| Field | Value |
|---|---|
| **ID** | SC-012 |
| **Epic** | M04 · Smart Contracts |
| **Module** | `contracts` ([spec](../../../docs/modules/contracts/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | S (≤ 0.5 day) |
| **Area** | contracts |
| **Status** | Ready for Review |
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

- used-fingerprint mapping checked and set in pay
- overrideDuplicate flag honoured only if the approval is signed with it and an Owner-level approver rule is met

## Out of scope

Fingerprint computation (off-chain, ENG-009).

## Technical notes

Document precisely who may sign an override (decision: approval must also be co-signed by Safe T).

## Dependencies

- SC-006: Implement pay() core flow

## Acceptance criteria

- [ ] Second pay with the same fingerprint and a new request id reverts
- [ ] Override path works only with the Owner co-signature

## Testing requirements

- Unit: duplicate and override tests

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
