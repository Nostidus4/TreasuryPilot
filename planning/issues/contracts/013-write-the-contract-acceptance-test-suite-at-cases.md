# [CONTRACTS] Write the contract acceptance test suite (AT cases)

| Field | Value |
|---|---|
| **ID** | SC-013 |
| **Epic** | M04 · Smart Contracts |
| **Module** | `contracts` ([spec](../../../docs/modules/contracts/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | M (~1 day) |
| **Area** | contracts |
| **Status** | Ready for Assignment |
| **Traces to** | AT-01–AT-13 (source doc) |
| **Blocks** | SC-014, SC-015, SC-020, POL-004 |
| **Submission cut** | A |

## Context

This ticket belongs to the epic **Smart Contracts**. It supports:

- F-163: Security test suites

Problem behind this work (from `docs/FEATURES.md`):

- **F-163** solves: Evidence for the Security criterion.

## Objective

Encode the source document's acceptance scenarios that are enforceable on-chain as Foundry tests.

## Scope

- Tests for AT-01, 02, 05, 06, 07, 08, 10, 11 (after SC-011), 12
- shared fixture: 3 Safes, module, TestUSDC, approver and executor keys

## Out of scope

Off-chain parts of the AT cases.

## Technical notes

Name tests `test_AT05_*` so reports map to the source cases.

## Dependencies

- SC-009: Implement refill() bound to an approved request
- SC-010: Implement pause, resume, revoke and guardian
- SC-012: Add the duplicate-invoice fingerprint registry and owner override

## Acceptance criteria

- [ ] Each listed AT case has at least one passing test
- [ ] The test report lists AT ids

## Testing requirements

- Contract: this ticket is the tests

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
