# [CONTRACTS] Support multiple stablecoins with per-asset limits

| Field | Value |
|---|---|
| **ID** | SC-L05 |
| **Epic** | M04 · Smart Contracts |
| **Module** | `contracts` ([spec](../../../docs/modules/contracts/README.md)) |
| **Phase / Priority** | Later / - |
| **Size** | L (1.5–2 days; split if it grows) |
| **Area** | contracts |
| **Status** | Accepted |
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

- Owner-managed asset allowlist
- independent PAY and REFILL caps and daily counters
- per-wallet floors and refill targets per asset

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Re-estimated L; split into SC-L07 (allowlist and caps/counters) and SC-L08 (per-asset floors and refill targets).

## Dependencies

- SC-007: Implement per-request limits and UTC daily counters

## Acceptance criteria

- [ ] Unlisted assets are rejected; enabling a secondary asset requires explicitly configured floors/targets for Safe T and every known operational wallet.
- [ ] Secondary-asset buffer setup can precede allowlisting, and contract calls fail closed until every required wallet buffer is configured.
- [ ] PAY/REFILL caps, daily counters, floors and refill targets are independent per asset.

## Testing requirements

- Contract tests

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
