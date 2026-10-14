# [INVOICES] Add recurring payment schedules

| Field | Value |
|---|---|
| **ID** | INV-L03 |
| **Epic** | M05 · Invoices & Payment Requests |
| **Module** | `invoices` ([spec](../../../docs/modules/invoices/README.md)) |
| **Phase / Priority** | Later / - |
| **Size** | L (1.5–2 days; split if it grows) |
| **Area** | backend |
| **Status** | Accepted |
| **Traces to** | FR-321, BR-002 |
| **Blocks** | — |
| **Submission cut** | After submission |

> **Phase: Later.** This ticket was re-estimated and split into the separately sized INV-L03A, INV-L03B and INV-L03C slices before scheduling.

## Context

This ticket belongs to the epic **Invoices & Payment Requests**. It supports:

- F-040: Recurring payment schedules

Problem behind this work (from `docs/FEATURES.md`):

- **F-040** solves: Repetitive entry.

## Objective

Generate periodic drafts.

## Scope

- Schedule templates
- draft generation job
- skip a period

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Re-estimated from M to L and split into template, generation, and skip work before scheduling.

## Dependencies

- INV-003: Implement manual request creation and editing

## Acceptance criteria

- [ ] Generated drafts require approval every period

## Testing requirements

- Integration

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
