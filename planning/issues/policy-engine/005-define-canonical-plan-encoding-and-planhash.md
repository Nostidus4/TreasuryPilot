# [POLICY] Define canonical plan encoding and planHash

| Field | Value |
|---|---|
| **ID** | POL-005 |
| **Epic** | M08 · Policy Engine & Attestation |
| **Module** | `policy-engine` ([spec](../../../docs/modules/policy-engine/README.md)) |
| **Phase / Priority** | M1 / P1 |
| **Size** | S (≤ 0.5 day) |
| **Area** | backend |
| **Status** | Ready for Review |
| **Traces to** | BR-059, FR-412 |
| **Blocks** | POL-006 |

## Context

This ticket belongs to the epic **Policy Engine & Attestation**. It supports:

- F-056: Plan attestation

Problem behind this work (from `docs/FEATURES.md`):

- **F-056** solves: Prevents the payload being altered between validation and execution (plan drift).

## Objective

A plan has exactly one hash regardless of language or field order.

## Scope

- Canonical ABI-style encoding of ordered steps (action, wallets, payee, amount, request id, step id)
- planHash function
- step id derivation (deterministic from request id, action, sequence)

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Do not hash JSON.

## Dependencies

- ENG-010: Build EIP-712 typed data for approvals, exceptions and attestations

## Acceptance criteria

- [ ] The same plan built twice has the same hash
- [ ] Changing any money-relevant field changes the hash

## Testing requirements

- Unit: hash stability tests

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
