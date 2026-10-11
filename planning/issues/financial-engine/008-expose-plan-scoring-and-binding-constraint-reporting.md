# [ENGINE] Expose plan scoring and binding-constraint reporting

| Field | Value |
|---|---|
| **ID** | ENG-008 |
| **Epic** | M07 · Financial Engine (py-core) |
| **Module** | `financial-engine` ([spec](../../../docs/modules/financial-engine/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | S (≤ 0.5 day) |
| **Area** | backend |
| **Status** | Ready for Assignment |
| **Traces to** | FR-405, FR-407 |
| **Blocks** | EXE-004, AGT-007, AGT-009 |
| **Submission cut** | A |

## Context

This ticket belongs to the epic **Financial Engine (py-core)**. It supports:

- F-052: Terms-aware deterministic scheduler
- F-053: AI plan proposal & explanation

Problem behind this work (from `docs/FEATURES.md`):

- **F-052** solves: P4: rules like "earliest due first" leave money on the table.
- **F-053** solves: Handles judgment cases (vendor criticality notes, ambiguous priorities, multi-constraint trade-offs) and explains them.

## Objective

Score any candidate plan (AI or deterministic) with the same objective and explain what constrained it.

## Scope

- score(plan, requests, snapshot, policy) → (violations, missed feasible deadlines, −value, tx count)
- binding_constraints(plan) → list (daily pay cap, daily refill cap, buffer, source capacity, refill bound, cooling, deadline) with the binding numbers
- value lost by NEEDS_EXCEPTION items if granted (M07-D9)
- comparison helper used for AI proposals

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- ENG-007: Implement the terms-aware scheduler with OR-Tools CP-SAT

## Acceptance criteria

- [ ] Two plans can be compared deterministically
- [ ] Binding constraints are listed with the numbers that bind

## Testing requirements

- Unit: scoring tests

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
