# [EXECUTION] Add cross-chain bridging

| Field | Value |
|---|---|
| **ID** | EXE-L03 |
| **Epic** | M10 · Orchestration & Execution |
| **Module** | `execution` ([spec](../../../docs/modules/execution/README.md)) |
| **Phase / Priority** | Later / - |
| **Size** | L (1.5–2 days; split if it grows) |
| **Area** | backend |
| **Status** | Needs Discussion |
| **Traces to** | FR-516 |
| **Blocks** | — |

> **Phase: Later.** This ticket is intentionally coarser than M1 tickets. It must be re-estimated and split before it is scheduled.

## Context

This ticket belongs to the epic **Orchestration & Execution**. It supports:

- F-067: Cross-chain bridge

Problem behind this work (from `docs/FEATURES.md`):

- **F-067** solves: Liquidity stranded on another chain.

## Objective

Move liquidity between treasuries on different chains.

## Scope

- Bridge adapter
- in-flight accounting
- timeout handling

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- TRS-L01: Support multiple treasuries with a consolidated view

## Acceptance criteria

- [ ] No second bridge transfer is sent on timeout

## Testing requirements

- Integration

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
