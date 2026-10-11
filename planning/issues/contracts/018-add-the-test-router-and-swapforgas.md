# [CONTRACTS] Add the test router and swapForGas

| Field | Value |
|---|---|
| **ID** | SC-018 |
| **Epic** | M04 · Smart Contracts |
| **Module** | `contracts` ([spec](../../../docs/modules/contracts/README.md)) |
| **Phase / Priority** | M1 / P2 |
| **Size** | M (~1 day) |
| **Area** | contracts |
| **Status** | Ready for Assignment |
| **Traces to** | BR-081, BR-082, FR-511–512 |
| **Blocks** | SC-L03, EXE-011 |
| **Submission cut** | After submission |

## Context

This ticket belongs to the epic **Smart Contracts**. It supports:

- F-064: SWAP via allowlisted adapter (labelled test router)

Problem behind this work (from `docs/FEATURES.md`):

- **F-064** solves: Gas shortages (AT-03/04).

## Objective

Demonstrate a bounded swap from stablecoin to gas on a clearly labelled test router.

## Scope

- TestRouter with a fixed rate
- swapForGas with router and pair allowlist, swap budget, minOut, exact approve then approve(0)
- event

## Out of scope

Real DEX integration.

## Technical notes

Name and NatSpec must say TEST ROUTER.

## Dependencies

- SC-009: Implement refill() bound to an approved request

## Acceptance criteria

- [ ] Swap succeeds within budget and minOut
- [ ] Allowance is 0 after the call
- [ ] A router not in the allowlist reverts

## Testing requirements

- Unit: AT-04, AT-13 swap cases

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
