# [CONTRACTS] Implement pause, resume, revoke and guardian

| Field | Value |
|---|---|
| **ID** | SC-010 |
| **Epic** | M04 · Smart Contracts |
| **Module** | `contracts` ([spec](../../../docs/modules/contracts/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | S (≤ 0.5 day) |
| **Area** | contracts |
| **Status** | Ready for Review |
| **Traces to** | BR-062, BR-064, FR-219–220 |
| **Blocks** | SC-013, SC-016 |
| **Submission cut** | A |

## Context

This ticket belongs to the epic **Smart Contracts**. It supports:

- F-026: Pause, resume & revoke

Problem behind this work (from `docs/FEATURES.md`):

- **F-026** solves: Emergency stop.

## Objective

Emergency stop that only the Owner can lift.

## Scope

- pause() callable by Safe T or guardian (idempotent)
- resume() and revoke() only Safe T
- whenActive modifier on executor functions
- events

## Out of scope

Backend pause flag.

## Technical notes

Revoke is permanent for this module instance.

## Dependencies

- SC-003: Implement mandate governance and versioning

## Acceptance criteria

- [ ] Executor calls revert while paused
- [ ] Guardian can pause but cannot resume
- [ ] After revoke every executor call reverts permanently

## Testing requirements

- Unit: role matrix test

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
