# [CONTRACTS] Implement per-request limits and UTC daily counters

| Field | Value |
|---|---|
| **ID** | SC-007 |
| **Epic** | M04 · Smart Contracts |
| **Module** | `contracts` ([spec](../../../docs/modules/contracts/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | M (~1 day) |
| **Area** | contracts |
| **Status** | Ready for Assignment |
| **Traces to** | BR-020–BR-026, FR-212–214 |
| **Blocks** | SC-009, SC-011, SC-L05 |
| **Submission cut** | A |

## Context

This ticket belongs to the epic **Smart Contracts**. It supports:

- F-023: Spending limits & treasury-wide UTC daily counters

Problem behind this work (from `docs/FEATURES.md`):

- **F-023** solves: Bounds the maximum loss and blocks split-to-evade attacks.

## Objective

Bound total spend per action, asset and UTC day across the whole treasury.

## Scope

- counter mapping keyed by (action, asset, day)
- day = block.timestamp / 86400
- per-request and daily checks in pay and refill
- increment only on success
- counter view

## Out of scope

Exception lifting the per-request cap (SC-011).

## Technical notes

Counters are in the module (one per treasury), so they are shared by O1 and O2. Version changes must not touch them.

## Dependencies

- SC-006: Implement pay() core flow

## Acceptance criteria

- [ ] Sum of successful pays in a day never exceeds the daily limit
- [ ] Paying from O1 then O2 uses the same counter
- [ ] configureMandate does not reset counters
- [ ] A pay just after UTC midnight uses the new day's budget

## Testing requirements

- Unit: boundary and midnight tests
- fuzz on amounts

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
