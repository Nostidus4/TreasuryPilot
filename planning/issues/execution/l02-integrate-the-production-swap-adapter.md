# [EXECUTION] Integrate the production swap adapter

| Field | Value |
|---|---|
| **ID** | EXE-L02 |
| **Epic** | M10 · Orchestration & Execution |
| **Module** | `execution` ([spec](../../../docs/modules/execution/README.md)) |
| **Phase / Priority** | Later / - |
| **Size** | M (~1 day) |
| **Area** | backend |
| **Status** | Needs Discussion |
| **Traces to** | FR-513 |
| **Blocks** | — |

> **Phase: Later.** This ticket is intentionally coarser than M1 tickets. It must be re-estimated and split before it is scheduled.

## Context

This ticket belongs to the epic **Orchestration & Execution**. It supports:

- F-065: Real DEX/aggregator swap with verified quotes

Problem behind this work (from `docs/FEATURES.md`):

- **F-065** solves: Real liquidity and real price protection.

## Objective

Execute real DEX swaps with verified quotes.

## Scope

- Quote source adapter
- plan step integration

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- EXE-011: Execute the swap-for-gas step on the test router
- SC-L03: Add a production swap adapter with signed quotes

## Acceptance criteria

- [ ] A stale or forged quote stops the plan

## Testing requirements

- Integration on a fork

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
