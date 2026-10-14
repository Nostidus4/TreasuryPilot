# [ENGINE] Model fiat FX approvals, rates and quote policy

| Field | Value |
|---|---|
| **ID** | ENG-015 |
| **Epic** | M07 · Financial Engine (py-core) |
| **Module** | `financial-engine` ([spec](../../../docs/modules/financial-engine/README.md)) |
| **Phase / Priority** | Later / - |
| **Size** | S (≤ 0.5 day) |
| **Area** | backend |
| **Status** | Accepted |
| **Traces to** | FR-322 |
| **Blocks** | ENG-016 |
| **Submission cut** | After submission |

> **Phase: Later.** This ticket is intentionally coarser than M1 tickets. It must be re-estimated and split before it is scheduled.

## Context

This ticket belongs to the epic **Financial Engine (py-core)**. It supports:

- F-041: Fiat-denominated invoices with FX & depeg checks

Problem behind this work (from `docs/FEATURES.md`):

- **F-041** solves: Real invoices are usually fiat-denominated.

## Objective

Represent approved fiat amounts and observed FX inputs using validated integer models.

## Scope

- FiatApproval binds fiat minor units, reference rate, tolerance and maximum token base units
- FxRate stores an exact rational token-base-units/fiat-minor-unit pair
- FxQuote and FxPolicy carry source, observation time, USD peg price and freshness/depeg thresholds

## Out of scope

Conversion and payment orchestration

## Technical notes

Keep values integer-only and immutable; USD peg policy is scoped to the supported USD-pegged asset.

## Dependencies

- ENG-001: Create py-core money types and domain models
- ENG-005: Model payment terms and their value function

## Acceptance criteria

- [ ] Invalid or non-positive amounts/rates and out-of-range bps are rejected
- [ ] Amounts serialize without precision loss

## Testing requirements

- Unit

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
