# [WEB] Build metrics and savings pages

| Field | Value |
|---|---|
| **ID** | WEB-018 |
| **Epic** | M16 · Web Application |
| **Module** | `web` ([spec](../../../docs/modules/web/README.md)) |
| **Phase / Priority** | M1 / P1 |
| **Size** | M (~1 day) |
| **Area** | frontend |
| **Status** | Ready for Assignment |
| **Traces to** | FR-921–922 |
| **Blocks** | — |
| **Submission cut** | After submission |

## Context

This ticket belongs to the epic **Web Application**. It supports:

- F-140: Operational metrics
- F-141: Savings report

Problem behind this work (from `docs/FEATURES.md`):

- **F-140** solves: Measurable value. Honest reporting.
- **F-141** solves: Shows the AI's value in money.

## Objective

Show operational results and savings.

## Scope

- Charts (Recharts) for completion, on-time, interventions, fees
- savings vs B1 with methodology note

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- WEB-010: Build the treasury dashboard
- OBS-005: Compute the savings report

## Acceptance criteria

- [ ] Numbers match the API
- [ ] Negative savings render correctly

## Testing requirements

- E2E

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
