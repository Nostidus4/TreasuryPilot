# [INVOICES] Add the inbound invoice API with scoped keys

| Field | Value |
|---|---|
| **ID** | INV-L02 |
| **Epic** | M05 · Invoices & Payment Requests |
| **Module** | `invoices` ([spec](../../../docs/modules/invoices/README.md)) |
| **Phase / Priority** | Later / - |
| **Size** | L (1.5–2 days; split if it grows) |
| **Area** | backend |
| **Status** | Accepted |
| **Traces to** | FR-309 |
| **Blocks** | — |
| **Submission cut** | After submission |

> **Phase: Later.** This ticket is intentionally coarser than M1 tickets. It must be re-estimated and split before it is scheduled.

## Context

This ticket belongs to the epic **Invoices & Payment Requests**. It supports:

- F-034: Inbound API / webhook intake

Problem behind this work (from `docs/FEATURES.md`):

- **F-034** solves: Integration with existing AP flows.

## Objective

Let other systems create drafts.

## Scope

- Issue, list and revoke organization-scoped API keys with invoices:create only
- hash secrets and enforce expiry and per-key rate limits
- Add key-authenticated idempotent single and bulk draft creation with per-row results

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Re-estimate L (~1.5–2 days). Before scheduling, split into key lifecycle and authorization (S), then inbound create and bulk ingestion (M).

## Dependencies

- INV-003: Implement manual request creation and editing

## Acceptance criteria

- [ ] A key without invoices:create is refused
- [ ] Keys cannot approve
- [ ] Retries with identical idempotency keys return the original row
- [ ] One invalid or conflicting bulk row does not prevent later rows from receiving a result

## Testing requirements

- Integration

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
