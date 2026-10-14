# [NOTIFY] Build secure chat-channel registration and delivery

| Field | Value |
|---|---|
| **ID** | NTF-L03 |
| **Epic** | M13 · Notifications |
| **Module** | `notifications` ([spec](../../../docs/modules/notifications/README.md)) |
| **Phase / Priority** | Later / - |
| **Size** | M (~1 day) |
| **Area** | backend |
| **Status** | Accepted |
| **Traces to** | FR-905 |
| **Blocks** | NTF-L03a, NTF-L03b, NTF-L03c |
| **Submission cut** | After submission |

> **Phase: Later.** This ticket is intentionally coarser than M1 tickets. It must be re-estimated and split before it is scheduled.

## Context

This ticket belongs to the epic **Notifications**. It supports:

- F-104: Slack / Lark / WeCom notifications

Problem behind this work (from `docs/FEATURES.md`):

- **F-104** solves: Team workflows (including China-market chat tools).

## Objective

Shared secure delivery foundation for Slack, Lark and WeCom.

## Scope

- Encrypted provider webhook registration
- provider URL validation
- deduplicated delivery queue
- Telegram-equivalent severity filtering, content, opt-in, throttling and retries

## Out of scope

Provider-specific message adapters are tracked as NTF-L03a…NTF-L03c

## Technical notes

Re-estimated and split before scheduling: shared foundation M, each provider adapter S.

## Dependencies

- NTF-001: Create the domain event bus and notification routing
- NTF-003: Add Telegram linking and delivery

## Acceptance criteria

- [ ] Channel destinations are encrypted and SSRF-resistant
- [ ] eligible events receive identical content and delivery semantics across providers

## Testing requirements

- Integration

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
