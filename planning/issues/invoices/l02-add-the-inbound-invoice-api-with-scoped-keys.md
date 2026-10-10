# [INVOICES] Add the inbound invoice API with scoped keys

| Field | Value |
|---|---|
| **ID** | INV-L02 |
| **Epic** | M05 · Invoices & Payment Requests |
| **Module** | `invoices` ([spec](../../../docs/modules/invoices/README.md)) |
| **Phase / Priority** | Later / - |
| **Size** | M (~1 day) |
| **Area** | backend |
| **Status** | Needs Discussion |
| **Traces to** | FR-309 |
| **Blocks** | — |

> **Phase: Later.** This ticket is intentionally coarser than M1 tickets. It must be re-estimated and split before it is scheduled.

## Context

This ticket belongs to the epic **Invoices & Payment Requests**. It supports:

- F-034: Inbound API / webhook intake

Problem behind this work (from `docs/FEATURES.md`):

- **F-034** solves: Integration with existing AP flows.

## Objective

Let other systems create drafts.

## Scope

- API keys with scopes
- idempotent create and bulk endpoints

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- INV-003: Implement manual request creation and editing

## Acceptance criteria

- [ ] A key without invoices:create is refused
- [ ] Keys cannot approve

## Testing requirements

- Integration

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
