# [NOTIFY] Add Telegram linking and delivery

| Field | Value |
|---|---|
| **ID** | NTF-003 |
| **Epic** | M13 · Notifications |
| **Module** | `notifications` ([spec](../../../docs/modules/notifications/README.md)) |
| **Phase / Priority** | M1 / P2 |
| **Size** | M (~1 day) |
| **Area** | backend |
| **Status** | Ready for Assignment |
| **Traces to** | FR-902, M13-D7 |
| **Blocks** | — |
| **Submission cut** | After submission |

## Context

This ticket belongs to the epic **Notifications**. It supports:

- F-101: Telegram notifications with deep links

Problem behind this work (from `docs/FEATURES.md`):

- **F-101** solves: Fast reaction away from the desk.

## Objective

Reach users on Telegram with a link back to the app.

## Scope

- Link flow with a one-time code
- bot webhook with secret header
- sender with minimal content and deep links
- opt-in for amounts and addresses
- at most one Telegram message per user per 10 s, bursts merged (M13-D7)

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- NTF-001: Create the domain event bus and notification routing

## Acceptance criteria

- [ ] A linked user receives the message within 10 seconds
- [ ] No action can be completed from Telegram
- [ ] Amounts appear only after opt-in

## Testing requirements

- Integration with a test bot

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
