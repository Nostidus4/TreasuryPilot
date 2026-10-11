# [ENGINE] Implement the 7-day liquidity forecast

| Field | Value |
|---|---|
| **ID** | ENG-011 |
| **Epic** | M07 · Financial Engine (py-core) |
| **Module** | `financial-engine` ([spec](../../../docs/modules/financial-engine/README.md)) |
| **Phase / Priority** | M1 / P2 |
| **Size** | S (≤ 0.5 day) |
| **Area** | backend |
| **Status** | Ready for Assignment |
| **Traces to** | FR-415 |
| **Blocks** | WEB-021 |
| **Submission cut** | After submission |

## Context

This ticket belongs to the epic **Financial Engine (py-core)**. It supports:

- F-058: Liquidity forecast & runway

Problem behind this work (from `docs/FEATURES.md`):

- **F-058** solves: Proactive rather than last-minute refills.

## Objective

Project per-wallet balances against approved obligations and suggest early refills.

## Scope

- forecast(snapshot, requests, policy, days=7) → daily projected balances per wallet, buffer-hit days, suggested refills within limits and the refill bound
- approved obligations only, drafts optional behind a flag

## Out of scope

UI chart (WEB-021).

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- ENG-003: Implement the refill decision table

## Acceptance criteria

- [ ] Projection matches a hand-computed example
- [ ] Suggested refills never exceed limits or the source buffer

## Testing requirements

- Unit: forecast tests

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
