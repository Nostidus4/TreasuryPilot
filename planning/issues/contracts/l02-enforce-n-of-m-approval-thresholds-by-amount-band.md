# [CONTRACTS] Enforce n-of-m approval thresholds by amount band

| Field | Value |
|---|---|
| **ID** | SC-L02 |
| **Epic** | M04 · Smart Contracts |
| **Module** | `contracts` ([spec](../../../docs/modules/contracts/README.md)) |
| **Phase / Priority** | Later / - |
| **Size** | L (1.5–2 days; split if it grows) |
| **Area** | contracts |
| **Status** | Accepted |
| **Traces to** | FR-224 |
| **Blocks** | MDT-L01 |
| **Submission cut** | After submission |

> **Phase: Later.** This ticket is intentionally coarser than M1 tickets. It must be re-estimated and split before it is scheduled.

## Context

This ticket belongs to the epic **Smart Contracts**. It supports:

- F-029: Threshold-based multi-level approval (n-of-m)

Problem behind this work (from `docs/FEATURES.md`):

- **F-029** solves: Enterprise internal controls.

## Objective

Support enterprise approval policies on-chain.

## Scope

- Approval policy storage (bands, k)
- verify k distinct approver signatures over the same typed data

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- SC-005: Implement approval signature verification

## Acceptance criteria

- [ ] Each band enforces its k
- [ ] Duplicate signer counted once

## Testing requirements

- Contract: band matrix

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
