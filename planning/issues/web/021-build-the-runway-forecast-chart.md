# [WEB] Build the runway forecast chart

| Field | Value |
|---|---|
| **ID** | WEB-021 |
| **Epic** | M16 · Web Application |
| **Module** | `web` ([spec](../../../docs/modules/web/README.md)) |
| **Phase / Priority** | M1 / P2 |
| **Size** | S (≤ 0.5 day) |
| **Area** | frontend |
| **Status** | Ready for Review |
| **Traces to** | FR-415 |
| **Blocks** | — |
| **Submission cut** | After submission |

## Context

This ticket belongs to the epic **Web Application**. It supports:

- F-058: Liquidity forecast & runway

Problem behind this work (from `docs/FEATURES.md`):

- **F-058** solves: Proactive rather than last-minute refills.

## Objective

See when wallets will hit their buffer.

## Scope

- 7-day chart per wallet with buffer line
- suggested refills
- include-drafts toggle

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- WEB-010: Build the treasury dashboard
- ENG-011: Implement the 7-day liquidity forecast

## Acceptance criteria

- [ ] The chart matches the forecast API

## Testing requirements

- E2E

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
