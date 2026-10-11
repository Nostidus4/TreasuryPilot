# [WEB] Build the fee policy and fee acceptance UI

| Field | Value |
|---|---|
| **ID** | WEB-024 |
| **Epic** | M16 · Web Application |
| **Module** | `web` ([spec](../../../docs/modules/web/README.md)) |
| **Phase / Priority** | M1 / P1 |
| **Size** | S (≤ 0.5 day) |
| **Area** | frontend |
| **Status** | Ready for Assignment |
| **Traces to** | FR-517, FR-518 |
| **Blocks** | — |
| **Submission cut** | B |

## Context

This ticket belongs to the epic **Web Application**. It supports:

- F-066: Gas management

Problem behind this work (from `docs/FEATURES.md`):

- **F-066** solves: "USDC but no gas" failures (E3).

## Objective

Owners accept the proposed fee limits; Finance accepts held plans.

## Scope

- Fee policy card with the system proposal and basis (avg, p90, plans per day) and Accept / choose preset
- held-plan banner with 'Pay now at X' / 'Defer'
- history of accepted fees

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- WEB-010: Build the treasury dashboard
- EXE-012: Implement the fee policy, fee holds and fee acceptance

## Acceptance criteria

- [ ] The Owner can accept a proposal in two clicks
- [ ] A held plan shows the estimated fee and the deadline

## Testing requirements

- E2E

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
