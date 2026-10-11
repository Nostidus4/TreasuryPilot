# [EXECUTION] Track gas fees and alert on low executor gas

| Field | Value |
|---|---|
| **ID** | EXE-010 |
| **Epic** | M10 · Orchestration & Execution |
| **Module** | `execution` ([spec](../../../docs/modules/execution/README.md)) |
| **Phase / Priority** | M1 / P1 |
| **Size** | S (≤ 0.5 day) |
| **Area** | backend |
| **Status** | Ready for Assignment |
| **Traces to** | BR-025, BR-080, FR-514–515 |
| **Blocks** | — |
| **Submission cut** | After submission |

## Context

This ticket belongs to the epic **Orchestration & Execution**. It supports:

- F-066: Gas management

Problem behind this work (from `docs/FEATURES.md`):

- **F-066** solves: "USDC but no gas" failures (E3).

## Objective

Fees are visible and the executor does not silently run dry.

## Scope

- gas_ledger entry per transaction including reverts
- fee-envelope check before signing
- low-balance threshold alert
- clear stop reason when gas is insufficient

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- EXE-007: Implement the executor with outbox semantics

## Acceptance criteria

- [ ] Every transaction has a fee record
- [ ] Below the threshold an alert event is emitted
- [ ] With no gas the operation stops with INSUFFICIENT_GAS and nothing is marked paid

## Testing requirements

- Integration

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
