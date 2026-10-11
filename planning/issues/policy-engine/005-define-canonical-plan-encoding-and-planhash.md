# [POLICY] Define canonical plan encoding and planHash

| Field | Value |
|---|---|
| **ID** | POL-005 |
| **Epic** | M08 · Policy Engine & Attestation |
| **Module** | `policy-engine` ([spec](../../../docs/modules/policy-engine/README.md)) |
| **Phase / Priority** | M1 / P1 |
| **Size** | S (≤ 0.5 day) |
| **Area** | backend |
| **Status** | Ready for Assignment |
| **Traces to** | BR-059, BR-061, FR-412, M08-D10 |
| **Blocks** | POL-006 |
| **Submission cut** | A |

## Context

This ticket belongs to the epic **Policy Engine & Attestation**. It supports:

- F-056: Plan attestation

Problem behind this work (from `docs/FEATURES.md`):

- **F-056** solves: Prevents the payload being altered between validation and execution (plan drift).

## Objective

A plan has exactly one hash regardless of language or field order.

## Scope

- EIP-712 Step struct hash
- planHash = keccak(PLAN_TYPEHASH, requestId, treasury, chainId, keccak(stepHashes)) per docs/modules/policy-engine §8.3
- stepId = keccak('TP_STEP_V1', requestId, action, wallet) per §8.4
- golden vectors shared with TypeScript

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Do not hash JSON.

## Dependencies

- ENG-010: Build EIP-712 typed data for payment approvals and attestations

## Acceptance criteria

- [ ] The same plan built twice has the same hash
- [ ] Changing any money-relevant field changes the hash
- [ ] A re-plan of the remaining steps keeps the same stepIds
- [ ] Python and TypeScript agree on all vectors

## Testing requirements

- Unit: hash stability tests

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
