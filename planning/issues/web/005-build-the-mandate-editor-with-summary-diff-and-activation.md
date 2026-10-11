# [WEB] Build the mandate editor with summary, diff and activation

| Field | Value |
|---|---|
| **ID** | WEB-005 |
| **Epic** | M16 · Web Application |
| **Module** | `web` ([spec](../../../docs/modules/web/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | L (1.5–2 days; split if it grows) |
| **Area** | frontend |
| **Status** | Ready for Assignment |
| **Traces to** | FR-203–204 |
| **Blocks** | — |
| **Submission cut** | B |

## Context

This ticket belongs to the epic **Web Application**. It supports:

- F-134: Mandate & payee management UI
- F-020: Mandate configuration
- F-021: Mandate activation, versioning & lifecycle

Problem behind this work (from `docs/FEATURES.md`):

- **F-134** solves: Safe configuration by non-developers.
- **F-020** solves: Turns "trust the agent" into an explicit, enforceable, auditable grant (P2).
- **F-021** solves: Policy must exist where it is enforced. A database copy is only a cache (GA p.11).

## Objective

Owners author and sign a mandate knowing exactly what it allows.

## Scope

- Form for all mandate fields with bigint display/base unit conversion
- human-readable summary
- diff against the active version with looser/stricter markers and confirm for looser changes
- create the governance tx and hand off to the governance inbox
- status PendingActivation → Active / Discrepancy

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Split form and activation flow into two PRs if needed.

## Dependencies

- WEB-004: Build the treasury setup wizard
- MDT-003: Implement mandate activation and read-back
- WEB-025: Build the governance signing inbox

## Acceptance criteria

- [ ] The summary matches the values sent to the API
- [ ] Activation shows pending until confirmed
- [ ] Non-owners see read-only

## Testing requirements

- E2E on Anvil

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
