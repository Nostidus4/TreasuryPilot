# [CONTRACTS] Support multiple stablecoins with per-asset limits

| Field | Value |
|---|---|
| **ID** | SC-L05 |
| **Epic** | M04 · Smart Contracts |
| **Module** | `contracts` ([spec](../../../docs/modules/contracts/README.md)) |
| **Phase / Priority** | Later / - |
| **Size** | M (~1 day) |
| **Area** | contracts |
| **Status** | Needs Discussion |
| **Traces to** | FR-111 |
| **Blocks** | TRS-L02 |
| **Submission cut** | After submission |

> **Phase: Later.** This ticket is intentionally coarser than M1 tickets. It must be re-estimated and split before it is scheduled.

## Context

This ticket belongs to the epic **Smart Contracts**. It supports:

- F-015: Multiple stablecoins per treasury

Problem behind this work (from `docs/FEATURES.md`):

- **F-015** solves: Vendors may require different stablecoins.

## Objective

Allow more than one payment asset in a treasury.

## Scope

- Per-asset limits and buffers
- asset allowlist in the mandate

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- SC-007: Implement per-request limits and UTC daily counters

## Acceptance criteria

- [ ] Limits are enforced independently per asset

## Testing requirements

- Contract tests

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
