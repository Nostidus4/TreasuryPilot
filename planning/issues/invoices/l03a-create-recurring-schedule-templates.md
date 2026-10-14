# [INVOICES] Create recurring schedule templates

| Field | Value |
|---|---|
| **ID** | INV-L03A |
| **Epic** | M05 · Invoices & Payment Requests |
| **Module** | `invoices` ([spec](../../../docs/modules/invoices/README.md)) |
| **Phase / Priority** | Later / - |
| **Size** | M (~1 day) |
| **Area** | backend |
| **Status** | Accepted |
| **Traces to** | FR-321, BR-002 |
| **Blocks** | INV-L03B, INV-L03C |
| **Submission cut** | After submission |

> **Phase: Later.** This is a separately estimated delivery slice.

## Context

This ticket belongs to the epic **Invoices & Payment Requests**. It supports:

- F-040: Recurring payment schedules

Problem behind this work (from `docs/FEATURES.md`):

- **F-040** solves: Repetitive entry.

## Objective

Operators can define and maintain a recurring obligation template.

## Scope

- Recurring schedule schema and API
- validate treasury, vendor, payee, asset, wallet, amount and dates
- cadence and invoice-number period token
- pause and resume
- edits affect future periods only

## Out of scope

Draft generation and skipping periods.

## Technical notes

No template action approves a request.

## Dependencies

- INV-003: Implement manual request creation and editing

## Acceptance criteria

- [ ] Invalid payee or asset cannot be saved
- [ ] Template updates affect only future drafts
- [ ] Creator and last editor cannot approve generated requests

## Testing requirements

- Integration with PostgreSQL

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
