# [CONTRACTS] Write the invariant and fuzz suite

| Field | Value |
|---|---|
| **ID** | SC-014 |
| **Epic** | M04 · Smart Contracts |
| **Module** | `contracts` ([spec](../../../docs/modules/contracts/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | M (~1 day) |
| **Area** | contracts |
| **Status** | Ready for Assignment |
| **Traces to** | NFR-SEC-02, BR-001/013/022/024/030/041/062 |
| **Blocks** | SC-L01 |
| **Submission cut** | A |

## Context

This ticket belongs to the epic **Smart Contracts**. It supports:

- F-163: Security test suites

Problem behind this work (from `docs/FEATURES.md`):

- **F-163** solves: Evidence for the Security criterion.

## Objective

Prove the nine invariants in the module spec hold under random call sequences.

## Scope

- Handler contract driving pay/refill/pause/configure/grantException with bounded random inputs
- invariants I1–I10 from docs/modules/contracts §10 (I10 = refill bound)
- 10k-run configuration

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Use ghost variables to track expected totals.

## Dependencies

- SC-013: Write the contract acceptance test suite (AT cases)

## Acceptance criteria

- [ ] Invariants I1–I10 pass at 10k runs
- [ ] Each invariant is mapped to its BR in a comment
- [ ] A deliberately broken check makes the matching invariant fail

## Testing requirements

- Contract: invariant suite

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
