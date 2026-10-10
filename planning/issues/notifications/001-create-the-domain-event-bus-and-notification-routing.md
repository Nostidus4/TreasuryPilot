# [NOTIFY] Create the domain event bus and notification routing

| Field | Value |
|---|---|
| **ID** | NTF-001 |
| **Epic** | M13 · Notifications |
| **Module** | `notifications` ([spec](../../../docs/modules/notifications/README.md)) |
| **Phase / Priority** | M1 / P1 |
| **Size** | M (~1 day) |
| **Area** | backend |
| **Status** | Ready for Review |
| **Traces to** | FR-901 |
| **Blocks** | NTF-002, NTF-003, NTF-L01, NTF-L02, NTF-L03 |

## Context

This ticket belongs to the epic **Notifications**. It supports:

- F-100: In-app notifications

Problem behind this work (from `docs/FEATURES.md`):

- **F-100** solves: Users act on time.

## Objective

Domain events reach the right people.

## Scope

- Event publisher (in-process + outbox table)
- routing table event type → roles
- notifications schema
- dedup by event id

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- INV-002: Implement the request state machine

## Acceptance criteria

- [ ] An approval-needed event creates notifications for Approvers only
- [ ] Duplicate events create one notification

## Testing requirements

- Unit + integration

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
