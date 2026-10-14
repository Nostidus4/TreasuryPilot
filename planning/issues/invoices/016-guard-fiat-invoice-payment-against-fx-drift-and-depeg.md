# [INVOICES] Guard fiat invoice payment against FX drift and depeg

| Field | Value |
|---|---|
| **ID** | INV-016 |
| **Epic** | M05 · Invoices & Payment Requests |
| **Module** | `invoices` ([spec](../../../docs/modules/invoices/README.md)) |
| **Phase / Priority** | Later / - |
| **Size** | S (≤ 0.5 day) |
| **Area** | backend |
| **Status** | Accepted |
| **Traces to** | FR-322 |
| **Blocks** | INV-L04 |
| **Submission cut** | After submission |

> **Phase: Later.** This ticket is intentionally coarser than M1 tickets. It must be re-estimated and split before it is scheduled.

## Context

This ticket belongs to the epic **Invoices & Payment Requests**. It supports:

- F-041: Fiat-denominated invoices with FX & depeg checks

Problem behind this work (from `docs/FEATURES.md`):

- **F-041** solves: Real invoices are usually fiat-denominated.

## Objective

Recompute the payable stablecoin amount from a fresh quote immediately before execution.

## Scope

- FX provider boundary
- freshness, source, pair, drift and USD peg checks
- integer ceiling conversion
- block above approved max

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- INV-015: Model fiat invoice amounts and approval caps
- ENG-016: Guard fiat conversion against FX drift, depeg and approved caps

## Acceptance criteria

- [ ] Stale, mismatched, depegged or over-cap quotes return no payment amount
- [ ] safe proposals never exceed the approved maximum

## Testing requirements

- Integration

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
