# [CONTRACTS] Add asset allowlist and independent payment limits

| Field | Value |
|---|---|
| **ID** | SC-L07 |
| **Epic** | M04 · Smart Contracts |
| **Module** | `contracts` ([spec](../../../docs/modules/contracts/README.md)) |
| **Phase / Priority** | Later / - |
| **Size** | M (~1 day) |
| **Area** | contracts |
| **Status** | Accepted |
| **Traces to** | FR-111 |
| **Blocks** | SC-L08 |
| **Submission cut** | After submission |

> **Phase: Later.** This ticket is intentionally coarser than M1 tickets. It must be re-estimated and split before it is scheduled.

## Context

This ticket belongs to the epic **Smart Contracts**. It supports:

- F-015: Multiple stablecoins per treasury

Problem behind this work (from `docs/FEATURES.md`):

- **F-015** solves: Vendors may require different stablecoins.

## Objective

Allow an owner-mandated second payment asset with independent PAY and REFILL caps and daily counters.

## Scope

- Asset policy allowlist
- approval validation
- per-asset daily counter keys
- preserve primary-asset compatibility views

## Out of scope

Parent: SC-L05.

## Technical notes

Part 1 of the SC-L05 split. Implement before per-asset wallet targets.

## Dependencies

- SC-007: Implement per-request limits and UTC daily counters

## Acceptance criteria

- [ ] Unlisted assets are rejected and usage of one asset does not consume another asset's daily budget

## Testing requirements

- Contract tests

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
