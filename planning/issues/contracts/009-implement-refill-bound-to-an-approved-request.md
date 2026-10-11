# [CONTRACTS] Implement refill() bound to an approved request

| Field | Value |
|---|---|
| **ID** | SC-009 |
| **Epic** | M04 · Smart Contracts |
| **Module** | `contracts` ([spec](../../../docs/modules/contracts/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | M (~1 day) |
| **Area** | contracts |
| **Status** | Ready for Assignment |
| **Traces to** | BR-010, BR-012, BR-023, FR-508 |
| **Blocks** | SC-013, SC-018, SC-L06, SC-022 |
| **Submission cut** | A |

## Context

This ticket belongs to the epic **Smart Contracts**. It supports:

- F-062: REFILL execution

Problem behind this work (from `docs/FEATURES.md`):

- **F-062** solves: P1.

## Objective

Move stablecoin from Safe T to an operational Safe only for an approved request, along an allowed path.

## Scope

- refill(approval, sig, stepId, toWallet, amount) per §6.4 checks 1–13
- toWallet must equal the approval's paying wallet
- one refill per request per wallet
- post-refill balance ≤ approval.amount + target(toWallet)
- refill limits and counter
- source buffer
- balance-delta check
- RefillExecuted event

## Out of scope

Refill between operational wallets (Later).

## Technical notes

Refill does not consume the PAY budget (BR-023).

## Dependencies

- SC-005: Implement approval signature verification
- SC-007: Implement per-request limits and UTC daily counters
- SC-008: Enforce minimum buffers on pay and refill

## Acceptance criteria

- [ ] A refill within all bounds succeeds
- [ ] A second refill for the same request and wallet reverts AlreadyRefilledForRequest
- [ ] A refill that would push the wallet above amount + target reverts RefillExceedsNeed
- [ ] A refill to a wallet other than the approval's paying wallet reverts WrongRefillTarget
- [ ] Safe T below its buffer after refill reverts SourceBufferBreach

## Testing requirements

- Unit: bound, replay and path tests
- invariant I10 added in SC-014

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
