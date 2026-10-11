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
| **Traces to** | FR-603–604, ADR-019 |
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

- Expected effects per step type (docs/modules/reconciliation §8.1)
- observed = state at block B minus B−1 via Multicall3, concurrent token movements subtracted
- verification PASSED / DISCREPANCY / UNKNOWN (after 3 read failures)
- DISCREPANCY → review item + circuit-breaker signal
- called by EXE-008 before the next step
- post-conditions for SUPPLY and WITHDRAW

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
