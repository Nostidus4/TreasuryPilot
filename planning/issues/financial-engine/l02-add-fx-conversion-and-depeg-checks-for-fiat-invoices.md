# [ENGINE] Add FX conversion and depeg checks for fiat invoices

| Field | Value |
|---|---|
| **ID** | ENG-L02 |
| **Epic** | M07 · Financial Engine (py-core) |
| **Module** | `financial-engine` ([spec](../../../docs/modules/financial-engine/README.md)) |
| **Phase / Priority** | Later / - |
| **Size** | M (~1 day) |
| **Area** | backend |
| **Status** | Accepted |
| **Traces to** | FR-322 |
| **Blocks** | INV-L04 |
| **Submission cut** | After submission |

> **Phase: Later.** This ticket is intentionally coarser than M1 tickets. It must be re-estimated and split before it is scheduled.

## Context

This ticket belongs to the epic **Financial Engine (py-core)**. It supports:

- F-041: Fiat-denominated invoices with FX & depeg checks

Problem behind this work (from `docs/FEATURES.md`):

- **F-041** solves: Real invoices are usually fiat-denominated.

## Objective

Schedule and pay fiat-denominated invoices safely.

## Scope

- FX rate model with tolerance
- max stablecoin amount
- depeg threshold check

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- ENG-005: Model payment terms and their value function

## Acceptance criteria

- [ ] Never proposes more than the approved maximum stablecoin amount

## Testing requirements

- Unit

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
