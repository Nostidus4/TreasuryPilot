# [EXECUTION] Execute the swap-for-gas step on the test router

| Field | Value |
|---|---|
| **ID** | EXE-011 |
| **Epic** | M10 · Orchestration & Execution |
| **Module** | `execution` ([spec](../../../docs/modules/execution/README.md)) |
| **Phase / Priority** | M1 / P2 |
| **Size** | S (≤ 0.5 day) |
| **Area** | backend |
| **Status** | Ready for Review |
| **Traces to** | FR-511–512 |
| **Blocks** | EXE-L02 |

## Context

This ticket belongs to the epic **Orchestration & Execution**. It supports:

- F-064: SWAP via allowlisted adapter (labelled test router)

Problem behind this work (from `docs/FEATURES.md`):

- **F-064** solves: Gas shortages (AT-03/04).

## Objective

Show a bounded swap inside a plan.

## Scope

- Plan step type SWAP
- quote from the configured test source
- minOut computed by the engine
- labelled TEST ROUTER in records

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- EXE-008: Sequence steps with re-read and re-validation
- SC-018: Add the test router and swapForGas

## Acceptance criteria

- [ ] A plan with a gas shortage includes a swap step and completes
- [ ] Records and UI label the router as test

## Testing requirements

- Integration: AT-04

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
