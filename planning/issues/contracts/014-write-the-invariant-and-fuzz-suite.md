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
| **Traces to** | NFR-SEC-02, BR-001/013/022/024/030/041/062, ADR-019 |
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

- Handler contract driving pay/refill/pause/configure/grantException/cancelRequest with bounded random inputs
- invariants I1–I11 from docs/modules/contracts §10 (I10 = refill bound, I11 = cancelled never pays)
- 10k-run configuration
- invariants I12–I14 (supply floor, fixed Aave targets with zero allowance after, exact payment option)

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Use ghost variables to track expected totals.

## Dependencies

- SC-013: Write the contract acceptance test suite (AT cases)
- SC-022: Add on-chain request cancellation

## Acceptance criteria

- [ ] Invariants I1–I11 pass at 10k runs
- [ ] Each invariant is mapped to its BR in a comment
- [ ] A deliberately broken check makes the matching invariant fail
- [ ] I12–I14 pass at 10k runs

## Testing requirements

- Contract: invariant suite

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
