# [EXECUTION] Implement the fee policy, fee holds and fee acceptance

| Field | Value |
|---|---|
| **ID** | EXE-012 |
| **Epic** | M10 · Orchestration & Execution |
| **Module** | `execution` ([spec](../../../docs/modules/execution/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | M (~1 day) |
| **Area** | backend |
| **Status** | Ready for Assignment |
| **Traces to** | BR-084, FR-517, FR-518, FEE-1, FEE-2, FEE-3, PH-7 |
| **Blocks** | EXE-004, WEB-024 |
| **Submission cut** | A |

## Context

This ticket belongs to the epic **Orchestration & Execution**. It supports:

- F-066: Gas management

Problem behind this work (from `docs/FEATURES.md`):

- **F-066** solves: "USDC but no gas" failures (E3).

## Objective

The agent spends gas automatically only within limits the Owner accepted, and waits or asks otherwise.

## Scope

- Fee proposal from 7-day history and eth_feeHistory (presets ECONOMY/NORMAL/FAST, per-plan threshold, daily budget) per docs/modules/mandate §8.6
- accept endpoint (Owner, no free-form numbers)
- plan fee estimate (estimateGas × maxFee over all steps)
- hold rules per §8.7: proceed, defer (FEE_ABOVE_THRESHOLD / FEE_BUDGET_EXHAUSTED) or AwaitingFeeAcceptance on the last safe day
- fee accept/defer endpoints for Finance/Operator/Owner
- daily spent-fee counter

## Out of scope

Sending transactions (EXE-007).

## Technical notes

Reference ETH price is a labelled treasury setting in M1; an oracle is Later.

## Dependencies

- MDT-001: Create mandate, payee and exception schema
- CHR-001: Build the RPC client with failover
- ENG-001: Create py-core money types and domain models

## Acceptance criteria

- [ ] The §8.7 example behaves as documented
- [ ] A held plan is deferred without a human while its deadline allows
- [ ] On the last safe day a FEE_APPROVAL review item is created
- [ ] An accepted fee cap is respected by the executor

## Testing requirements

- Unit + integration

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
