# [NOTIFY] Add notification preferences

| Field | Value |
|---|---|
| **ID** | NTF-L04 |
| **Epic** | M13 · Notifications |
| **Module** | `notifications` ([spec](../../../docs/modules/notifications/README.md)) |
| **Phase / Priority** | Later / - |
| **Size** | S (≤ 0.5 day) |
| **Area** | backend |
| **Status** | Needs Discussion |
| **Traces to** | FR-903 |
| **Blocks** | — |

> **Phase: Later.** This ticket is intentionally coarser than M1 tickets. It must be re-estimated and split before it is scheduled.

## Context

This ticket belongs to the epic **Notifications**. It supports:

- F-105: Notification preferences

Problem behind this work (from `docs/FEATURES.md`):

- **F-105** solves: Noise.

## Objective

Per-user preferences.

## Scope

- Channel and category settings
- quiet hours
- mandatory categories

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- NTF-002: Expose in-app notifications and the SSE stream

## Acceptance criteria

- [ ] Mandatory categories cannot be muted

## Testing requirements

- Integration

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
