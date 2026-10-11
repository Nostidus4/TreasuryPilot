# [NOTIFY] Add Slack, Lark and WeCom channels

| Field | Value |
|---|---|
| **ID** | NTF-L03 |
| **Epic** | M13 · Notifications |
| **Module** | `notifications` ([spec](../../../docs/modules/notifications/README.md)) |
| **Phase / Priority** | Later / - |
| **Size** | L (1.5–2 days; split if it grows) |
| **Area** | backend |
| **Status** | Needs Discussion |
| **Traces to** | FR-905 |
| **Blocks** | — |
| **Submission cut** | After submission |

> **Phase: Later.** This ticket is intentionally coarser than M1 tickets. It must be re-estimated and split before it is scheduled.

## Context

This ticket belongs to the epic **Notifications**. It supports:

- F-104: Slack / Lark / WeCom notifications

Problem behind this work (from `docs/FEATURES.md`):

- **F-104** solves: Team workflows (including China-market chat tools).

## Objective

Chat-platform channels.

## Scope

- One adapter per platform

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- NTF-001: Create the domain event bus and notification routing

## Acceptance criteria

- [ ] Event parity with Telegram

## Testing requirements

- Integration

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
