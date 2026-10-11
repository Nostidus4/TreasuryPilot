# [CONTRACTS] Enforce minimum buffers on pay and refill

| Field | Value |
|---|---|
| **ID** | SC-008 |
| **Epic** | M04 · Smart Contracts |
| **Module** | `contracts` ([spec](../../../docs/modules/contracts/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | S (≤ 0.5 day) |
| **Area** | contracts |
| **Status** | Ready for Assignment |
| **Traces to** | BR-030, FR-215 |
| **Blocks** | SC-009 |
| **Submission cut** | A |

## Context

This ticket belongs to the epic **Smart Contracts**. It supports:

- F-024: Minimum buffer & target balance protection

Problem behind this work (from `docs/FEATURES.md`):

- **F-024** solves: Keeps a wallet able to operate and protects funds set aside for other uses.

## Objective

No agent-path transaction leaves a wallet below its buffer.

## Scope

- buffer per (wallet, asset) in the mandate
- post-transfer balance check for the paying wallet in pay
- post-transfer check for Safe T in refill

## Out of scope

Target balance (off-chain soft goal).

## Technical notes

Check the balance after the transfer, in the same call.

## Dependencies

- SC-006: Implement pay() core flow

## Acceptance criteria

- [ ] A pay that would leave the paying wallet below its buffer reverts
- [ ] A refill that would leave Safe T below its buffer reverts
- [ ] Exactly-at-buffer succeeds

## Testing requirements

- Unit: boundary tests
- fuzz

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
