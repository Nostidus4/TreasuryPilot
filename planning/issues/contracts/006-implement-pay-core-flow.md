# [CONTRACTS] Implement pay() core flow

| Field | Value |
|---|---|
| **ID** | SC-006 |
| **Epic** | M04 · Smart Contracts |
| **Module** | `contracts` ([spec](../../../docs/modules/contracts/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | M (~1 day) |
| **Area** | contracts |
| **Status** | Ready for Review |
| **Traces to** | BR-001, BR-010, BR-024, FR-509, FR-510 |
| **Blocks** | SC-007, SC-008, SC-012 |
| **Submission cut** | A |

## Context

This ticket belongs to the epic **Smart Contracts**. It supports:

- F-063: PAY execution

Problem behind this work (from `docs/FEATURES.md`):

- **F-063** solves: The core job.

## Objective

Pay the approved amount to the approved payee from the paying Safe, exactly once.

## Scope

- pay() with executor-only access
- approval verification
- payee active check
- request id unused check and mark used
- token transfer via execTransactionFromModuleReturnData with return-data check
- PaymentExecuted event
- reentrancy guard

## Out of scope

Limits (SC-007), buffer (SC-008), exception (SC-011), fingerprint (SC-012).

## Technical notes

Checks-effects-interactions. Treat a token returning false as failure.

## Dependencies

- SC-004: Implement the payee registry with cooling period
- SC-005: Implement approval signature verification

## Acceptance criteria

- [ ] A valid approved payment transfers the exact amount to the payee
- [ ] A second call with the same request id reverts
- [ ] A non-executor caller reverts
- [ ] A token that returns false causes a revert with no state change

## Testing requirements

- Unit: happy path, replay, access, false-returning token stub

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
