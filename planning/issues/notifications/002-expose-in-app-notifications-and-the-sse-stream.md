# [NOTIFY] Expose in-app notifications and the SSE stream

| Field | Value |
|---|---|
| **ID** | NTF-002 |
| **Epic** | M13 · Notifications |
| **Module** | `notifications` ([spec](../../../docs/modules/notifications/README.md)) |
| **Phase / Priority** | M1 / P1 |
| **Size** | M (~1 day) |
| **Area** | backend |
| **Status** | Ready for Assignment |
| **Traces to** | FR-901, ADR-010, M13-D3, M13-D4, M13-D8 |
| **Blocks** | NTF-L04, WEB-012, WEB-015 |
| **Submission cut** | A |

## Context

This ticket belongs to the epic **Notifications**. It supports:

- F-100: In-app notifications
- F-132: Plan cards & live execution timeline

Problem behind this work (from `docs/FEATURES.md`):

- **F-100** solves: Users act on time.
- **F-132** solves: Explainability and real-time feedback.

## Objective

Users see events live.

## Scope

- GET /notifications, POST read
- SSE endpoint /orgs/{o}/events with plan, operation, request and notification events
- auth and org scoping on the stream
- SSE resume with Last-Event-ID, heartbeat every 15 s, clients fall back to 10 s polling when pub/sub is down (M13-D3, M13-D8)
- payloads carry ids only (M13-D4)

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- NTF-001: Create the domain event bus and notification routing

## Acceptance criteria

- [ ] An operation status change reaches a connected client within 2 seconds
- [ ] A member of another org receives nothing
- [ ] A reconnecting client with Last-Event-ID receives the missed events

## Testing requirements

- Integration

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
