# [INVOICES] Skip a recurring payment period

| Field | Value |
|---|---|
| **ID** | INV-L03C |
| **Epic** | M05 · Invoices & Payment Requests |
| **Module** | `invoices` ([spec](../../../docs/modules/invoices/README.md)) |
| **Phase / Priority** | Later / - |
| **Size** | S (≤ 0.5 day) |
| **Area** | backend |
| **Status** | Accepted |
| **Traces to** | FR-321, BR-002 |
| **Blocks** | — |
| **Submission cut** | After submission |

> **Phase: Later.** This is a separately estimated delivery slice.

## Context

This ticket belongs to the epic **Invoices & Payment Requests**. It supports:

- F-040: Recurring payment schedules

Problem behind this work (from `docs/FEATURES.md`):

- **F-040** solves: Repetitive entry.

## Objective

An Operator can skip the next period while preserving the schedule history.

## Scope

- Org-scoped skip endpoint
- record the actor and period
- advance the anchored cadence
- complete schedules after their end date

## Out of scope

Skipping already generated periods.

## Technical notes

Skip leaves no payment request to approve.

## Dependencies

- INV-L03A: Create recurring schedule templates

## Acceptance criteria

- [ ] Only the next active period can be skipped
- [ ] A skipped period never generates a request
- [ ] The following period remains on the original cadence

## Testing requirements

- Integration with PostgreSQL

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
