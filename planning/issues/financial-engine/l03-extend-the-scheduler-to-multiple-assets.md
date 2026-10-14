# [ENGINE] Extend the scheduler to multiple assets

| Field | Value |
|---|---|
| **ID** | ENG-L03 |
| **Epic** | M07 · Financial Engine (py-core) |
| **Module** | `financial-engine` ([spec](../../../docs/modules/financial-engine/README.md)) |
| **Phase / Priority** | Later / - |
| **Size** | L (3 days) |
| **Area** | backend |
| **Status** | Accepted |
| **Traces to** | FR-111 |
| **Blocks** | — |
| **Submission cut** | After submission |

> **Phase: Later.** Split into the implementation slices below before scheduling. Estimates assume ENG-007 is available as the base branch.

## Context

This ticket belongs to the epic **Financial Engine (py-core)**. It supports F-015: multiple stablecoins per treasury, so vendors can be paid in their required assets.

## Objective

Schedule requests in multiple assets while applying each asset's own balances, source budget, and policy limits. Preserve integer base-unit arithmetic and return a deterministic combined schedule with asset identity on each payment.

## Scope

- [ENG-L03a](eng-l03/01-multi-asset-schedule-contract.md): define and validate the multi-asset schedule input/output contract (S, 0.5 day).
- [ENG-L03b](eng-l03/02-schedule-each-asset-with-isolated-limits.md): solve per asset with independent balances and limits, then aggregate schedules/objectives (M, 1.5 days).
- [ENG-L03c](eng-l03/03-verify-multi-asset-limits-and-base-units.md): unit and property coverage for per-asset limits, deterministic aggregation, and integer base units (S, 1 day).

## Out of scope

Cross-asset conversion, FX/depeg pricing, and cross-asset refills.

## Dependencies

- ENG-007: Implement the terms-aware scheduler with OR-Tools CP-SAT.

## Acceptance criteria

- [ ] Per-asset pay/refill limits and source/wallet balances are isolated and respected.
- [ ] Combined schedule and objective are deterministic across assets.
- [ ] Each scheduled item identifies its asset.
- [ ] All monetary values remain integer base units.

## Testing requirements

- Unit and property tests, as detailed in ENG-L03c.

## Definition of Done

- [ ] Code completed and merged through a reviewed PR.
- [ ] Tests pass in CI.
- [ ] Docs updated if behavior or design changed.
