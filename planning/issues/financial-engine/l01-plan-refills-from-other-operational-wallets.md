# [ENGINE] Plan refills from other operational wallets

| Field | Value |
|---|---|
| **ID** | ENG-L01 |
| **Epic** | M07 · Financial Engine (py-core) |
| **Module** | `financial-engine` ([spec](../../../docs/modules/financial-engine/README.md)) |
| **Phase / Priority** | Later / - |
| **Size** | M (~1 day) |
| **Area** | backend |
| **Status** | Needs Discussion |
| **Traces to** | FR-416 |
| **Blocks** | — |
| **Submission cut** | After submission |

> **Phase: Later.** This ticket is intentionally coarser than M1 tickets. It must be re-estimated and split before it is scheduled.

## Context

This ticket belongs to the epic **Financial Engine (py-core)**. It supports:

- F-059: Refill from other operational wallets

Problem behind this work (from `docs/FEATURES.md`):

- **F-059** solves: Funds stranded in one operational wallet.

## Objective

Use surplus in one operational wallet to fund another.

## Scope

- Extend source selection
- protect the source wallet's own obligations

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- ENG-007: Implement the terms-aware scheduler
- SC-L06: Allow refill paths between operational wallets

## Acceptance criteria

- [ ] Source wallet obligations remain funded (property test)

## Testing requirements

- Unit + property

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
