# [TREASURY] Support multiple stablecoins per treasury

| Field | Value |
|---|---|
| **ID** | TRS-L02 |
| **Epic** | M02 · Treasury & Chain Configuration |
| **Module** | `treasury` ([spec](../../../docs/modules/treasury/README.md)) |
| **Phase / Priority** | Later / - |
| **Size** | M (~1 day) |
| **Area** | backend |
| **Status** | Needs Discussion |
| **Traces to** | FR-111 |
| **Blocks** | — |
| **Submission cut** | After submission |

> **Phase: Later.** This ticket is intentionally coarser than M1 tickets. It must be re-estimated and split before it is scheduled.

## Context

This ticket belongs to the epic **Treasury & Chain Configuration**. It supports:

- F-015: Multiple stablecoins per treasury

Problem behind this work (from `docs/FEATURES.md`):

- **F-015** solves: Vendors may require different stablecoins.

## Objective

Hold and pay in more than one stablecoin.

## Scope

- Asset list per treasury
- per-asset limits in the mandate UI and API

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- TRS-L01: Support multiple treasuries with a consolidated view
- SC-L05: Support multiple stablecoins with per-asset limits

## Acceptance criteria

- [ ] A request in a second asset is validated against that asset's limits

## Testing requirements

- Integration

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
