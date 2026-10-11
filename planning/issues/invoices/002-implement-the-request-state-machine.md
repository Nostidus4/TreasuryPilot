# [INVOICES] Implement the request state machine

| Field | Value |
|---|---|
| **ID** | INV-002 |
| **Epic** | M05 · Invoices & Payment Requests |
| **Module** | `invoices` ([spec](../../../docs/modules/invoices/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | M (~1 day) |
| **Area** | backend |
| **Status** | Ready for Assignment |
| **Traces to** | FR-319–320 |
| **Blocks** | INV-003, RCV-004, NTF-001 |
| **Submission cut** | A |

## Context

This ticket belongs to the epic **Invoices & Payment Requests**. It supports:

- F-039: Payment request lifecycle & state machine

Problem behind this work (from `docs/FEATURES.md`):

- **F-039** solves: Unambiguous status. No single "Failed" state that erases history.

## Objective

Requests move only along legal transitions, and every move is recorded.

## Scope

- Transition table as data per docs/modules/invoices §5 (incl. withdraw, request-changes, renew, Expired, SYSTEM-only transitions)
- transition(request, to, actor) with role and guard checks
- request_status_events and audit writes
- refuse Cancelled while a PAY operation is NotSubmitted/Submitted/Pending/Unknown

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

No generic Failed state.

## Dependencies

- INV-001: Create invoice and request schema

## Acceptance criteria

- [ ] Every legal transition in §5 is allowed and every other pair is rejected
- [ ] SYSTEM transitions are refused for user actors
- [ ] Each transition writes a status event and an audit record
- [ ] Paid, Rejected and Cancelled are terminal

## Testing requirements

- Unit: full transition matrix

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
