# [TREASURY] Support multiple stablecoins per treasury

| Field | Value |
|---|---|
| **ID** | TRS-L02 |
| **Epic** | M02 · Treasury & Chain Configuration |
| **Module** | `treasury` ([spec](../../../docs/modules/treasury/README.md)) |
| **Phase / Priority** | Later / - |
| **Size** | L (1.5–2 days; split into two implementation phases) |
| **Area** | backend + web |
| **Status** | Accepted |
| **Traces to** | FR-111 |
| **Blocks** | — |
| **Submission cut** | After submission |

> **Phase: Later.** Re-estimated L and decomposed before scheduling into (1) mandate configuration and safe bundle previews, then (2) secondary-asset invoice requests with chain and mandate enforcement. The phases share the secondary asset policy schema and should land together for this ticket's acceptance.

## Context

This ticket belongs to the epic **Treasury & Chain Configuration**. It supports:

- F-015: Multiple stablecoins per treasury

Problem behind this work (from `docs/FEATURES.md`):

- **F-015** solves: Vendors may require different stablecoins.

## Objective

Hold and pay in more than one stablecoin.

## Scope

- Select additional configured ERC-20 assets on the treasury's chain in mandate setup.
- Configure independent PAY and REFILL limits, Safe T floors, and operational floors/targets per asset.
- Preview transactions that set every wallet's asset buffer before enabling that asset's contract policy.
- Permit requests in a selected secondary asset only when that asset belongs to the treasury chain and has an active mandate PAY policy; enforce its per-request amount in integer base units.

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- TRS-L01: Support multiple treasuries with a consolidated view
- SC-L05: Support multiple stablecoins with per-asset limits

## Acceptance criteria

- [ ] Mandate UI/API accept only configured assets on the treasury chain, with unique secondary asset IDs and independent PAY/REFILL limits and explicit per-wallet buffers.
- [ ] Bundle preview configures all secondary asset buffers before enabling its contract policy.
- [ ] A request in a secondary asset is accepted only when the treasury's active mandate enables it for PAY; request amount is checked against that asset's per-request limit and the asset is chain-scoped to the treasury.
- [ ] Primary-asset behavior remains compatible with existing mandates and requests.

## Testing requirements

- API tests cover asset-chain and treasury mandate scoping, missing policies, and per-asset amount boundaries.
- UI typecheck and contract tests cover independent counters and mandatory buffer configuration before allowlisting.

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
