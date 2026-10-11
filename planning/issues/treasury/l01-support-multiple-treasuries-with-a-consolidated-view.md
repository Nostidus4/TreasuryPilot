# [TREASURY] Support multiple treasuries with a consolidated view

| Field | Value |
|---|---|
| **ID** | TRS-L01 |
| **Epic** | M02 · Treasury & Chain Configuration |
| **Module** | `treasury` ([spec](../../../docs/modules/treasury/README.md)) |
| **Phase / Priority** | Later / - |
| **Size** | M (~1 day) |
| **Area** | backend |
| **Status** | Accepted |
| **Traces to** | FR-110 |
| **Blocks** | TRS-L02, EXE-L03 |
| **Submission cut** | After submission |

> **Phase: Later.** This ticket is intentionally coarser than M1 tickets. It must be re-estimated and split before it is scheduled.

## Context

This ticket belongs to the epic **Treasury & Chain Configuration**. It supports:

- F-014: Multi-treasury & multi-chain

Problem behind this work (from `docs/FEATURES.md`):

- **F-014** solves: Real businesses operate across chains.

## Objective

Operate treasuries on several chains from one org.

## Scope

- Per-chain treasuries
- consolidated dashboard without cross-asset sums

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- TRS-004: Implement treasury creation with Safe verification

## Acceptance criteria

- [ ] Counters and mandates are isolated per treasury

## Testing requirements

- Integration

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
