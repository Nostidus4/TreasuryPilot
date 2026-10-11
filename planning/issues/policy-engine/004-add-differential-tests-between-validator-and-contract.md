# [POLICY] Add differential tests between validator and contract

| Field | Value |
|---|---|
| **ID** | POL-004 |
| **Epic** | M08 · Policy Engine & Attestation |
| **Module** | `policy-engine` ([spec](../../../docs/modules/policy-engine/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | M (~1 day) |
| **Area** | backend |
| **Status** | Ready for Assignment |
| **Traces to** | NFR-SEC-01 |
| **Blocks** | — |
| **Submission cut** | After submission |

## Context

This ticket belongs to the epic **Policy Engine & Attestation**. It supports:

- F-055: Policy validation (ALLOW / NEEDS_APPROVAL / BLOCK)
- F-163: Security test suites

Problem behind this work (from `docs/FEATURES.md`):

- **F-055** solves: A single, auditable gate that mirrors the contract checks.
- **F-163** solves: Evidence for the Security criterion.

## Objective

Catch any drift between off-chain validation and on-chain enforcement.

## Scope

- Harness running the same cases through validate_step and the module on Anvil
- cases: all AT-05 variants, limit boundaries (exactly at cap, cap + 1), cooling edges, pause, expiry, refill bound, exceptions, duplicate allowance
- compare ALLOW vs success and decoded revert vs primary code

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Runs in CI integration stage.

## Dependencies

- POL-003: Validate limits, buffers, deadlines, coverage and unknown operations
- SC-013: Write the contract acceptance test suite (AT cases)

## Acceptance criteria

- [ ] For every case the validator's ALLOW/not-ALLOW equals contract success/revert
- [ ] For every revert the decoded code equals the validator's primary code
- [ ] A report lists the cases

## Testing requirements

- Integration: differential suite

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
