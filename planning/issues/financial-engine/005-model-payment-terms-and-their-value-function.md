# [ENGINE] Model payment terms and their value function

| Field | Value |
|---|---|
| **ID** | ENG-005 |
| **Epic** | M07 · Financial Engine (py-core) |
| **Module** | `financial-engine` ([spec](../../../docs/modules/financial-engine/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | S (≤ 0.5 day) |
| **Area** | backend |
| **Status** | Ready for Assignment |
| **Traces to** | BR-052, BR-075 |
| **Blocks** | ENG-006, ENG-L02, INV-008, AGT-005 |
| **Submission cut** | A |

## Context

This ticket belongs to the epic **Financial Engine (py-core)**. It supports:

- F-035: Payment-terms extraction
- F-052: Terms-aware deterministic scheduler

Problem behind this work (from `docs/FEATURES.md`):

- **F-035** solves: Terms drive the value of the scheduler (P4).
- **F-052** solves: P4: rules like "earliest due first" leave money on the table.

## Objective

Compute what paying on a given date is worth in stablecoin.

## Scope

- PaymentTerms: discount pct and deadline, net due date, late-fee schedule, priority note
- value(pay_date) = discount captured − late fee incurred
- validation of ranges and date order

## Out of scope

Extraction of terms from text (AGT-005).

## Technical notes

Percentages as basis points (integers).

## Dependencies

- ENG-001: Create py-core money types and domain models

## Acceptance criteria

- [ ] '2/10 net 30' on a 1,000 unit invoice yields 20 units if paid by day 10 and 0 after
- [ ] A late fee of 1.5%/week accrues per started week
- [ ] Invalid terms raise typed errors

## Testing requirements

- Unit: terms tests

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
