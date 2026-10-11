# [ENGINE] Add property tests for buffer and limit safety

| Field | Value |
|---|---|
| **ID** | ENG-004 |
| **Epic** | M07 · Financial Engine (py-core) |
| **Module** | `financial-engine` ([spec](../../../docs/modules/financial-engine/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | S (≤ 0.5 day) |
| **Area** | backend |
| **Status** | Ready for Review |
| **Traces to** | NFR-MAINT-03, BR-030 |
| **Blocks** | — |
| **Submission cut** | After submission |

## Context

This ticket belongs to the epic **Financial Engine (py-core)**. It supports:

- F-051: Liquidity calculator

Problem behind this work (from `docs/FEATURES.md`):

- **F-051** solves: Amounts are never computed by the LLM (BR-034).

## Objective

Prove with random inputs that engine outputs never breach buffers or limits.

## Scope

- hypothesis strategies for wallet states, policies and requests
- properties: post-plan balances ≥ buffer, refill ≤ Cap, no negative amounts

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- ENG-003: Implement the refill decision table

## Acceptance criteria

- [ ] Properties pass with at least 1,000 examples each
- [ ] A seeded failing example is reproduced deterministically

## Testing requirements

- Unit: property tests

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
