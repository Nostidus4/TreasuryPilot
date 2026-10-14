# [INVOICES] Model fiat invoice amounts and approval caps

| Field | Value |
|---|---|
| **ID** | INV-015 |
| **Epic** | M05 · Invoices & Payment Requests |
| **Module** | `invoices` ([spec](../../../docs/modules/invoices/README.md)) |
| **Phase / Priority** | Later / - |
| **Size** | S (≤ 0.5 day) |
| **Area** | backend |
| **Status** | Accepted |
| **Traces to** | FR-322 |
| **Blocks** | INV-L04, INV-016 |
| **Submission cut** | After submission |

> **Phase: Later.** This ticket is intentionally coarser than M1 tickets. It must be re-estimated and split before it is scheduled.

## Context

This ticket belongs to the epic **Invoices & Payment Requests**. It supports:

- F-041: Fiat-denominated invoices with FX & depeg checks

Problem behind this work (from `docs/FEATURES.md`):

- **F-041** solves: Real invoices are usually fiat-denominated.

## Objective

Represent the invoice's fiat value and the approver's stablecoin ceiling in the request revision.

## Scope

- Fiat minor-unit amount and ISO currency fields
- capture and persist a reference FX quote
- include all FX approval inputs in revision snapshots and invoice hash
- expose the stablecoin ceiling explicitly

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- INV-003: Implement manual request creation and editing
- ENG-015: Model fiat FX approvals, rates and quote policy

## Acceptance criteria

- [ ] Changing fiat value, currency, reference quote or cap creates a revision and invalidates prior approvals
- [ ] approval typed data binds the maximum stablecoin base units

## Testing requirements

- Integration

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
