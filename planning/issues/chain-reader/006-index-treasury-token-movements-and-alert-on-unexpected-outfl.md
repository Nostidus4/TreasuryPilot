# [CHAIN] Index treasury token movements and alert on unexpected outflows

| Field | Value |
|---|---|
| **ID** | CHR-006 |
| **Epic** | M06 · Chain Reader & Tx Tracking |
| **Module** | `chain-reader` ([spec](../../../docs/modules/chain-reader/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | S (≤ 0.5 day) |
| **Area** | backend |
| **Status** | Ready for Assignment |
| **Traces to** | BR-069, FR-419, M06-D2, ADR-019 |
| **Blocks** | RCV-006 |
| **Submission cut** | A |

## Context

This ticket belongs to the epic **Chain Reader & Tx Tracking**. It supports:

- F-050: Chain state reader & fresh snapshots

Problem behind this work (from `docs/FEATURES.md`):

- **F-050** solves: Plans must use fresh, provable state, never an earlier snapshot after the state has changed.

## Objective

Know at once when money leaves a treasury wallet outside the agent.

## Scope

- TOKEN stream: asset Transfer logs with from or to in {T, O1, O2}
- token_movements with classification AGENT / INTERNAL_REFILL / INFLOW / UNEXPECTED_OUTFLOW (match by operation tx hash)
- alert Owner and Finance
- request immediate PRE_STEP re-validation for an in-progress plan
- signal to the circuit breaker
- acknowledge endpoint
- classify Safe T ↔ aToken transfers as LENDING, not unexpected outflow

## Out of scope

Circuit-breaker rule evaluation (RCV-006).

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- CHR-005: Index module and Safe events
- EXE-001: Create operations (outbox), transactions and gas ledger schema

## Acceptance criteria

- [ ] A Safe transaction moving 50 out of O1 is classified UNEXPECTED_OUTFLOW within two indexer cycles
- [ ] The example in docs/modules/chain-reader §8.4 blocks the pending PAY
- [ ] A refill by the agent is classified INTERNAL_REFILL, not an outflow

## Testing requirements

- Integration on Anvil

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
