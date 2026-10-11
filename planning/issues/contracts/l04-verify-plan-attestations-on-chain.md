# [CONTRACTS] Verify plan attestations on-chain

| Field | Value |
|---|---|
| **ID** | SC-L04 |
| **Epic** | M04 · Smart Contracts |
| **Module** | `contracts` ([spec](../../../docs/modules/contracts/README.md)) |
| **Phase / Priority** | Later / - |
| **Size** | M (~1 day) |
| **Area** | contracts |
| **Status** | Accepted |
| **Traces to** | BR-059 |
| **Blocks** | — |
| **Submission cut** | After submission |

> **Phase: Later.** This ticket is intentionally coarser than M1 tickets. It must be re-estimated and split before it is scheduled.

## Context

This ticket belongs to the epic **Smart Contracts**. It supports:

- F-056: Plan attestation

Problem behind this work (from `docs/FEATURES.md`):

- **F-056** solves: Prevents the payload being altered between validation and execution (plan drift).

## Objective

Move attestation checking from the signer service to the contract.

## Scope

- Verify PlanAttestation signature and nonce in pay/refill

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- SC-017: Publish EIP-712 golden vectors

## Acceptance criteria

- [ ] A step with a missing or stale attestation reverts

## Testing requirements

- Contract tests

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
