# [CONTRACTS] Implement one-time exception verification and consumption

| Field | Value |
|---|---|
| **ID** | SC-011 |
| **Epic** | M04 · Smart Contracts |
| **Module** | `contracts` ([spec](../../../docs/modules/contracts/README.md)) |
| **Phase / Priority** | M1 / P1 |
| **Size** | M (~1 day) |
| **Area** | contracts |
| **Status** | Ready for Review |
| **Traces to** | BR-040–BR-043, FR-216–217 |
| **Blocks** | — |
| **Submission cut** | B |

## Context

This ticket belongs to the epic **Smart Contracts**. It supports:

- F-025: One-time exception

Problem behind this work (from `docs/FEATURES.md`):

- **F-025** solves: Occasional large payments without loosening the general mandate.

## Objective

Let the Owner authorize one over-cap payment without loosening anything else.

## Scope

- Hash and verify OneTimeException signed by the Safe T owner (ERC-1271 against Safe T)
- bind request id, mandate version, wallet, payee, asset, amount, expiry, nonce
- consume nonce in pay
- skip only the per-request check
- ExceptionConsumed event

## Out of scope

Any lifting of the daily cap, buffer or payee rules.

## Technical notes

The exception signer check uses Safe T's signature validation so a multi-owner Safe works.

## Dependencies

- SC-007: Implement per-request limits and UTC daily counters

## Acceptance criteria

- [ ] Over-cap pay with a valid exception succeeds once
- [ ] Replay on another request reverts
- [ ] A different mandate version invalidates it
- [ ] Daily cap still blocks

## Testing requirements

- Unit: AT-11 matrix

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
