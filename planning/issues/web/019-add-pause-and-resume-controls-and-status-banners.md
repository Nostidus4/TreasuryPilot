# [WEB] Add pause and resume controls and status banners

| Field | Value |
|---|---|
| **ID** | WEB-019 |
| **Epic** | M16 · Web Application |
| **Module** | `web` ([spec](../../../docs/modules/web/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | S (≤ 0.5 day) |
| **Area** | frontend |
| **Status** | Ready for Review |
| **Traces to** | FR-221 |
| **Blocks** | — |

## Context

This ticket belongs to the epic **Web Application**. It supports:

- F-026: Pause, resume & revoke

Problem behind this work (from `docs/FEATURES.md`):

- **F-026** solves: Emergency stop.

## Objective

Stop the agent from the UI and always see its state.

## Scope

- Pause button for Owner and Guardian with reason
- Owner resume flow
- banners for pause requested, paused on-chain, partial coverage, expired mandate
- pending transactions list

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- WEB-010: Build the treasury dashboard
- MDT-007: Implement pause and resume (backend and transactions)

## Acceptance criteria

- [ ] The banner distinguishes requested from effective
- [ ] A Guardian sees no resume action

## Testing requirements

- E2E on Anvil

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
