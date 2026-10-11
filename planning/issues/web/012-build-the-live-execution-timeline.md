# [WEB] Build the live execution timeline

| Field | Value |
|---|---|
| **ID** | WEB-012 |
| **Epic** | M16 · Web Application |
| **Module** | `web` ([spec](../../../docs/modules/web/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | M (~1 day) |
| **Area** | frontend |
| **Status** | Ready for Assignment |
| **Traces to** | FR-917, NFR-PERF-04 |
| **Blocks** | WEB-023 |
| **Submission cut** | A |

## Context

This ticket belongs to the epic **Web Application**. It supports:

- F-132: Plan cards & live execution timeline

Problem behind this work (from `docs/FEATURES.md`):

- **F-132** solves: Explainability and real-time feedback.

## Objective

Watch steps go from submitted to confirmed in real time.

## Scope

- SSE subscription
- per-step status with explorer links
- verification result
- explicit 'checking chain…' state for Unknown
- partial completion view

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- WEB-011: Build plan cards and the Why panel
- NTF-002: Expose in-app notifications and the SSE stream

## Acceptance criteria

- [ ] A status change appears within 2 seconds
- [ ] Explorer links open the right transaction
- [ ] Unknown is never shown as failed

## Testing requirements

- E2E on Anvil

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
