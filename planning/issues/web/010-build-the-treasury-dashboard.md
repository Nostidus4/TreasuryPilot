# [WEB] Build the treasury dashboard

| Field | Value |
|---|---|
| **ID** | WEB-010 |
| **Epic** | M16 · Web Application |
| **Module** | `web` ([spec](../../../docs/modules/web/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | M (~1 day) |
| **Area** | frontend |
| **Status** | Ready for Review |
| **Traces to** | FR-915 |
| **Blocks** | WEB-011, WEB-014, WEB-016, WEB-018, WEB-019, WEB-021 |

## Context

This ticket belongs to the epic **Web Application**. It supports:

- F-130: Treasury dashboard

Problem behind this work (from `docs/FEATURES.md`):

- **F-130** solves: One glance at treasury health.

## Objective

Treasury health at a glance.

## Scope

- Wallet balances vs buffer and target
- today's budget used vs limits
- coverage and mandate status
- queue counts
- recent activity
- staleness banner
- TEST asset labels

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- WEB-004: Build the treasury setup wizard
- CHR-002: Implement block-consistent snapshots

## Acceptance criteria

- [ ] Values match the API
- [ ] A stale snapshot shows a banner
- [ ] Layout works at 1280 px and 390 px

## Testing requirements

- E2E + visual check

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
