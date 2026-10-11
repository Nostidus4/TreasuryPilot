# [WEB] Build the notifications center

| Field | Value |
|---|---|
| **ID** | WEB-015 |
| **Epic** | M16 · Web Application |
| **Module** | `web` ([spec](../../../docs/modules/web/README.md)) |
| **Phase / Priority** | M1 / P1 |
| **Size** | S (≤ 0.5 day) |
| **Area** | frontend |
| **Status** | Ready for Assignment |
| **Traces to** | FR-901 |
| **Blocks** | — |
| **Submission cut** | After submission |

## Context

This ticket belongs to the epic **Web Application**. It supports:

- F-100: In-app notifications

Problem behind this work (from `docs/FEATURES.md`):

- **F-100** solves: Users act on time.

## Objective

See and act on events.

## Scope

- Bell with unread count
- list with deep links
- mark read
- live updates

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- WEB-001: Create the web app shell
- NTF-002: Expose in-app notifications and the SSE stream

## Acceptance criteria

- [ ] A new event increases the badge without a reload

## Testing requirements

- E2E

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
