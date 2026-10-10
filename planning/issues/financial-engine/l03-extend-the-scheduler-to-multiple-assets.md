# [ENGINE] Extend the scheduler to multiple assets

| Field | Value |
|---|---|
| **ID** | ENG-L03 |
| **Epic** | M07 · Financial Engine (py-core) |
| **Module** | `financial-engine` ([spec](../../../docs/modules/financial-engine/README.md)) |
| **Phase / Priority** | Later / - |
| **Size** | M (~1 day) |
| **Area** | backend |
| **Status** | Needs Discussion |
| **Traces to** | FR-111 |
| **Blocks** | — |

> **Phase: Later.** This ticket is intentionally coarser than M1 tickets. It must be re-estimated and split before it is scheduled.

## Context

This ticket belongs to the epic **Financial Engine (py-core)**. It supports:

- F-015: Multiple stablecoins per treasury

Problem behind this work (from `docs/FEATURES.md`):

- **F-015** solves: Vendors may require different stablecoins.

## Objective

Schedule across more than one stablecoin.

## Scope

- Per-asset budgets and balances in the objective

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- ENG-007: Implement the terms-aware scheduler

## Acceptance criteria

- [ ] Per-asset limits respected in all schedules

## Testing requirements

- Unit + property

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
