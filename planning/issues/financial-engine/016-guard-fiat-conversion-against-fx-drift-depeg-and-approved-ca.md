# [ENGINE] Guard fiat conversion against FX drift, depeg and approved caps

| Field | Value |
|---|---|
| **ID** | ENG-016 |
| **Epic** | M07 · Financial Engine (py-core) |
| **Module** | `financial-engine` ([spec](../../../docs/modules/financial-engine/README.md)) |
| **Phase / Priority** | Later / - |
| **Size** | S (≤ 0.5 day) |
| **Area** | backend |
| **Status** | Accepted |
| **Traces to** | FR-322 |
| **Blocks** | INV-016 |
| **Submission cut** | After submission |

> **Phase: Later.** This ticket is intentionally coarser than M1 tickets. It must be re-estimated and split before it is scheduled.

## Context

This ticket belongs to the epic **Financial Engine (py-core)**. It supports:

- F-041: Fiat-denominated invoices with FX & depeg checks

Problem behind this work (from `docs/FEATURES.md`):

- **F-041** solves: Real invoices are usually fiat-denominated.

## Objective

Return a deterministic token amount only when a fresh quote satisfies the approval and safety policy.

## Scope

- Validate source/pair/freshness
- compare rational rates by integer cross multiplication
- check USD peg threshold
- round conversion up to token base units
- block instead of clipping if the rounded amount exceeds the approved maximum

## Out of scope

Fetching quotes, persisting invoices, signing approval and executing PAY

## Technical notes

Typed review-block reasons; recheck immediately before PAY and bind the returned amount to the approval.

## Dependencies

- ENG-015: Model fiat FX approvals, rates and quote policy
- ENG-005: Model payment terms and their value function

## Acceptance criteria

- [ ] Every returned amount is at most the approved maximum
- [ ] Boundary, malformed input, stale quote, depeg and randomized valid-rate cases are covered

## Testing requirements

- Unit + property

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
