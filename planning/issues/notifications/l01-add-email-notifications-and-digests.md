# [NOTIFY] Add email notifications and digests

| Field | Value |
|---|---|
| **ID** | NTF-L01 |
| **Epic** | M13 · Notifications |
| **Module** | `notifications` ([spec](../../../docs/modules/notifications/README.md)) |
| **Phase / Priority** | Later / - |
| **Size** | M (~1 day) |
| **Area** | backend |
| **Status** | Needs Discussion |
| **Traces to** | FR-903 |
| **Blocks** | — |
| **Submission cut** | After submission |

> **Phase: Later.** This ticket is intentionally coarser than M1 tickets. It must be re-estimated and split before it is scheduled.

## Context

This ticket belongs to the epic **Notifications**. It supports:

- F-102: Email notifications

Problem behind this work (from `docs/FEATURES.md`):

- **F-102** solves: Reach users without the app open.

## Objective

Email channel.

## Scope

- Templates
- digest job
- unsubscribe except security

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- NTF-001: Create the domain event bus and notification routing

## Acceptance criteria

- [ ] Security events cannot be unsubscribed

## Testing requirements

- Integration

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
