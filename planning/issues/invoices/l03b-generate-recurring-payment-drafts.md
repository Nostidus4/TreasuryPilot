# [INVOICES] Generate recurring payment drafts

| Field | Value |
|---|---|
| **ID** | INV-L03B |
| **Epic** | M05 · Invoices & Payment Requests |
| **Module** | `invoices` ([spec](../../../docs/modules/invoices/README.md)) |
| **Phase / Priority** | Later / - |
| **Size** | M (~1 day) |
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

Due periods create exactly one ordinary payment request draft.

## Scope

- Daily UTC worker job
- transactional schedule-period claim
- idempotent generated request, revision, status event and deterministic flags
- integer base-unit amounts

## Out of scope

Automatic submit, approval, planning or payment.

## Technical notes

Generated source and period provenance are stored.

## Dependencies

- INV-L03A: Create recurring schedule templates

## Acceptance criteria

- [ ] Repeated delivery creates one Draft
- [ ] No approval or payment is created
- [ ] A changed template payee is used by the next period

## Testing requirements

- Integration with PostgreSQL and worker task

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
