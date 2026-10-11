# [INVOICES] Implement payment-terms confirmation

| Field | Value |
|---|---|
| **ID** | INV-008 |
| **Epic** | M05 · Invoices & Payment Requests |
| **Module** | `invoices` ([spec](../../../docs/modules/invoices/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | S (≤ 0.5 day) |
| **Area** | backend |
| **Status** | Ready for Assignment |
| **Traces to** | FR-310–311, BR-075, ADR-019 |
| **Blocks** | INV-009 |
| **Submission cut** | A |

## Context

This ticket belongs to the epic **Invoices & Payment Requests**. It supports:

- F-035: Payment-terms extraction

Problem behind this work (from `docs/FEATURES.md`):

- **F-035** solves: Terms drive the value of the scheduler (P4).

## Objective

Only human-confirmed terms reach the scheduler.

## Scope

- POST /requests/{id}/terms/confirm validating with the ENG-005 model
- store terms and terms_hash
- mark confirmed_by
- derive earlyAmount and earlyPayBy from confirmed discount terms

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- INV-003: Implement manual request creation and editing
- ENG-005: Model payment terms and their value function

## Acceptance criteria

- [ ] Invalid terms return TERMS_INVALID
- [ ] Unconfirmed terms are not visible to the scheduler query

## Testing requirements

- Integration

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
