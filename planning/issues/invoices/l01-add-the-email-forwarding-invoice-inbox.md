# [INVOICES] Add the email-forwarding invoice inbox

| Field | Value |
|---|---|
| **ID** | INV-L01 |
| **Epic** | M05 · Invoices & Payment Requests |
| **Module** | `invoices` ([spec](../../../docs/modules/invoices/README.md)) |
| **Phase / Priority** | Later / - |
| **Size** | L (1.5–2 days; split if it grows) |
| **Area** | backend |
| **Status** | Needs Discussion |
| **Traces to** | FR-308 |
| **Blocks** | — |

> **Phase: Later.** This ticket is intentionally coarser than M1 tickets. It must be re-estimated and split before it is scheduled.

## Context

This ticket belongs to the epic **Invoices & Payment Requests**. It supports:

- F-033: Email-forwarding inbox

Problem behind this work (from `docs/FEATURES.md`):

- **F-033** solves: Removes the upload step entirely.

## Objective

Create drafts from forwarded emails.

## Scope

- Per-org inbound address
- SPF/DKIM checks
- attachment extraction into the upload pipeline

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- INV-004: Implement document upload to private storage
- AGT-004: Implement invoice extraction

## Acceptance criteria

- [ ] A spoofed sender is flagged
- [ ] No draft is auto-approved

## Testing requirements

- Integration

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
