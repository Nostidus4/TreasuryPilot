# [WEB] Build the treasury position card

| Field | Value |
|---|---|
| **ID** | WEB-026 |
| **Epic** | M16 · Web Application |
| **Module** | `web` ([spec](../../../docs/modules/web/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | S (≤ 0.5 day) |
| **Area** | frontend |
| **Status** | Ready for Assignment |
| **Traces to** | FR-915, ADR-019 |
| **Blocks** | WEB-027 |
| **Submission cut** | A |

## Context

This ticket belongs to the epic **Web Application**. It supports:

- F-068: Idle-cash management on Aave V3 (SUPPLY / WITHDRAW)
- F-130: Treasury dashboard

Problem behind this work (from `docs/FEATURES.md`):

- **F-068** solves: idle cash earns nothing, while over-supplying risks missing a due payment.
- **F-130** solves: One glance at treasury health.

## Objective

Show where the money is and why it is (not) supplied.

## Scope

- Safe USDC, aUSDC, pool liquidity, RequiredSafeReserve breakdown, AvailableForSupply, supply APY (testnet label), last liquidity action with explanation

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- WEB-010: Build the treasury dashboard

## Acceptance criteria

- [ ] Numbers equal the engine output for the snapshot
- [ ] Testnet APY is labelled

## Testing requirements

- E2E

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
