# [RECON] Verify post-conditions after each confirmed step

| Field | Value |
|---|---|
| **ID** | REC-001 |
| **Epic** | M11 · Verification & Reconciliation |
| **Module** | `reconciliation` ([spec](../../../docs/modules/reconciliation/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | M (~1 day) |
| **Area** | backend |
| **Status** | Ready for Assignment |
| **Traces to** | FR-603–604 |
| **Blocks** | REC-002, RCV-006 |
| **Submission cut** | A |

## Context

This ticket belongs to the epic **Verification & Reconciliation**. It supports:

- F-071: Post-condition verification

Problem behind this work (from `docs/FEATURES.md`):

- **F-071** solves: "Not reverted" is not proof of correctness (GA p.2).

## Objective

Confirm the chain state matches what the plan expected.

## Scope

- Expected deltas per step type
- read post-state
- verification record PASSED, DISCREPANCY or UNKNOWN
- discrepancy creates a review item and a circuit-breaker signal

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- EXE-008: Sequence steps with re-read and re-validation

## Acceptance criteria

- [ ] A normal pay verifies PASSED
- [ ] An unexpected balance yields DISCREPANCY with expected and observed values

## Testing requirements

- Integration on Anvil

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
