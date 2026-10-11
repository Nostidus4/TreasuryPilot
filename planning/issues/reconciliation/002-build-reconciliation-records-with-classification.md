# [RECON] Build reconciliation records with classification

| Field | Value |
|---|---|
| **ID** | REC-002 |
| **Epic** | M11 · Verification & Reconciliation |
| **Module** | `reconciliation` ([spec](../../../docs/modules/reconciliation/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | M (~1 day) |
| **Area** | backend |
| **Status** | Ready for Assignment |
| **Traces to** | BR-096, FR-605 |
| **Blocks** | REC-003 |
| **Submission cut** | A |

## Context

This ticket belongs to the epic **Verification & Reconciliation**. It supports:

- F-072: Reconciliation (Paid vs Matched)

Problem behind this work (from `docs/FEATURES.md`):

- **F-072** solves: P5.

## Objective

Every paid request has a complete, classified transaction set.

## Scope

- Schema migration
- on Paid create a reconciliation with lines: refill = INTERNAL_TRANSFER, swap = CONVERSION, pay = EXTERNAL_EXPENSE, gas = FEE
- status Pending

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- REC-001: Verify post-conditions after each confirmed step

## Acceptance criteria

- [ ] A request with refill and pay has two lines plus fee lines with correct classes
- [ ] A refill without a successful pay shows no expense

## Testing requirements

- Integration

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
