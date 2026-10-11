# [MANDATE] Sync mandate expiry and status

| Field | Value |
|---|---|
| **ID** | MDT-008 |
| **Epic** | M03 · Mandate, Payees, Exceptions & Pause |
| **Module** | `mandate` ([spec](../../../docs/modules/mandate/README.md)) |
| **Phase / Priority** | M1 / P1 |
| **Size** | S (≤ 0.5 day) |
| **Area** | backend |
| **Status** | Ready for Assignment |
| **Traces to** | FR-207 |
| **Blocks** | — |
| **Submission cut** | After submission |

## Context

This ticket belongs to the epic **Mandate, Payees, Exceptions & Pause**. It supports:

- F-021: Mandate activation, versioning & lifecycle

Problem behind this work (from `docs/FEATURES.md`):

- **F-021** solves: Policy must exist where it is enforced. A database copy is only a cache (GA p.11).

## Objective

Expired mandates stop planning before the contract has to reject.

## Scope

- Periodic task marking mandates Expired at expiresAt
- notifications to the Owner 7 d, 48 h and 1 h before expiry
- renewal shortcut = clone with a new expiry

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- MDT-003: Implement mandate activation and read-back

## Acceptance criteria

- [ ] A mandate past expiry is Expired and the trigger skips the treasury
- [ ] Warnings are emitted before expiry

## Testing requirements

- Integration

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
