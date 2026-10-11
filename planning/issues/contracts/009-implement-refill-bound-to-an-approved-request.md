# [CONTRACTS] Implement refill() bound to an approved request

| Field | Value |
|---|---|
| **ID** | SC-009 |
| **Epic** | M04 · Smart Contracts |
| **Module** | `contracts` ([spec](../../../docs/modules/contracts/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | M (~1 day) |
| **Area** | contracts |
| **Status** | Ready for Review |
| **Traces to** | BR-010, BR-012, BR-023, FR-508 |
| **Blocks** | SC-013, SC-018, SC-L06 |
| **Submission cut** | A |

## Context

This ticket belongs to the epic **Smart Contracts**. It supports:

- F-062: REFILL execution

Problem behind this work (from `docs/FEATURES.md`):

- **F-062** solves: P1.

## Objective

Move stablecoin from Safe T to an operational Safe only for an approved request, along an allowed path.

## Scope

- refill(approval, sig, stepId, toWallet, amount)
- path allowlist check
- toWallet must equal approval.payingWallet
- step id unused then marked used
- refill limits and counter
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

- [ ] Refill along an allowed path succeeds with a valid approval
- [ ] A step id cannot be executed twice
- [ ] A path not in the mandate reverts
- [ ] toWallet different from the approval's paying wallet reverts

## Testing requirements

- Unit: path, replay, limit tests

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
