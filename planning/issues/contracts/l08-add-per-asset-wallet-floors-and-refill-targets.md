# [CONTRACTS] Add per-asset wallet floors and refill targets

| Field | Value |
|---|---|
| **ID** | SC-L08 |
| **Epic** | M04 · Smart Contracts |
| **Module** | `contracts` ([spec](../../../docs/modules/contracts/README.md)) |
| **Phase / Priority** | Later / - |
| **Size** | M (~1 day) |
| **Area** | contracts |
| **Status** | Accepted |
| **Traces to** | FR-111 |
| **Blocks** | — |
| **Submission cut** | After submission |

> **Phase: Later.** This ticket is intentionally coarser than M1 tickets. It must be re-estimated and split before it is scheduled.

## Context

This ticket belongs to the epic **Smart Contracts**. It supports:

- F-015: Multiple stablecoins per treasury

Problem behind this work (from `docs/FEATURES.md`):

- **F-015** solves: Vendors may require different stablecoins.

## Objective

Apply independent wallet balance floors and refill targets to each allowed payment asset.

## Scope

- Per-asset buffers and targets
- refill and payment floor enforcement for the selected asset

## Out of scope

Parent: SC-L05.

## Technical notes

Part 2 of the SC-L05 split.

## Dependencies

- SC-L07: Add asset allowlist and independent payment limits

## Acceptance criteria

- [ ] Each asset's payments and refills preserve only that asset's configured wallet floors and targets

## Testing requirements

- Contract tests

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
