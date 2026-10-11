# [ENGINE] Implement the exhaustive oracle scheduler for tests

| Field | Value |
|---|---|
| **ID** | ENG-012 |
| **Epic** | M07 · Financial Engine (py-core) |
| **Module** | `financial-engine` ([spec](../../../docs/modules/financial-engine/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | S (≤ 0.5 day) |
| **Area** | backend |
| **Status** | Ready for Assignment |
| **Traces to** | BR-052, ADR-015, M07-D8 |
| **Blocks** | ENG-007 |
| **Submission cut** | A |

## Context

This ticket belongs to the epic **Financial Engine (py-core)**. It supports:

- F-052: Terms-aware deterministic scheduler
- F-092: AI evaluation harness (B1 vs B2)

Problem behind this work (from `docs/FEATURES.md`):

- **F-052** solves: P4: rules like "earliest due first" leave money on the table.
- **F-092** solves: Answers "why AI?" with data, honestly.

## Objective

A brute-force solver that proves the CP-SAT scheduler returns the true optimum on small cases.

## Scope

- schedule_oracle(requests, snapshot, policy) enumerating every day assignment for N ≤ 8 and horizon ≤ 5
- same constraint checks and score() as the other solvers
- hypothesis generator of small instances shared with ENG-007

## Out of scope

Use in production paths (tests and the benchmark only).

## Technical notes

Raises if N > 8 or horizon > 5. Shares the feasibility checker with EDF so all three solvers agree on what is feasible.

## Dependencies

- ENG-006: Implement the baseline scheduler B1 (earliest deadline first)

## Acceptance criteria

- [ ] On hand-computed cases it returns the known optimum
- [ ] It refuses inputs above its limits
- [ ] It runs 1,000 generated cases in under 60 s

## Testing requirements

- Unit: optimum cases
- generator smoke test

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
