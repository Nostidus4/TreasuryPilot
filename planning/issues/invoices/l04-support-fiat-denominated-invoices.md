# [INVOICES] Support fiat-denominated invoices

| Field | Value |
|---|---|
| **ID** | INV-L04 |
| **Epic** | M05 · Invoices & Payment Requests |
| **Module** | `invoices` ([spec](../../../docs/modules/invoices/README.md)) |
| **Phase / Priority** | Later / - |
| **Size** | L (1.5–2 days; split if it grows) |
| **Area** | backend |
| **Status** | Accepted |
| **Traces to** | FR-322 |
| **Blocks** | — |
| **Submission cut** | After submission |

> **Phase: Later.** This ticket is intentionally coarser than M1 tickets. It must be re-estimated and split before it is scheduled.

## Context

This ticket belongs to the epic **Invoices & Payment Requests**. It supports:

- F-041: Fiat-denominated invoices with FX & depeg checks

Problem behind this work (from `docs/FEATURES.md`):

- **F-041** solves: Real invoices are usually fiat-denominated.

## Objective

Accept invoices in fiat with FX conversion.

## Scope

- Two independently schedulable pieces: persist and approve a fiat invoice cap, then safely obtain and validate a fresh execution quote

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- INV-015: Model fiat invoice amounts and approval caps
- INV-016: Guard fiat invoice payment against FX drift and depeg

## Acceptance criteria

- [ ] Payment never exceeds the approved maximum stablecoin amount

## Testing requirements

- Integration

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
