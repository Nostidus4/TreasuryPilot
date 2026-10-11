# [ENGINE] Implement the refill decision table

| Field | Value |
|---|---|
| **ID** | ENG-003 |
| **Epic** | M07 · Financial Engine (py-core) |
| **Module** | `financial-engine` ([spec](../../../docs/modules/financial-engine/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | S (≤ 0.5 day) |
| **Area** | backend |
| **Status** | Ready for Assignment |
| **Traces to** | BR-031, BR-033, FR-404 |
| **Blocks** | ENG-004, ENG-006, ENG-011 |
| **Submission cut** | A |

## Context

This ticket belongs to the epic **Financial Engine (py-core)**. It supports:

- F-051: Liquidity calculator

Problem behind this work (from `docs/FEATURES.md`):

- **F-051** solves: Amounts are never computed by the LLM (BR-034).

## Objective

Turn calculator outputs into one of: no refill, refill preferred, refill shortage, stop.

## Scope

- decide_refill returning a typed decision with reason code
- no refill when Shortage is 0
- stop when Cap < Shortage

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Reason codes must come from the POL-001 catalogue.

## Dependencies

- ENG-002: Implement the liquidity calculator

## Acceptance criteria

- [ ] The three Domain §3.4 scenarios (350 / 250 / stop) return the documented decisions
- [ ] No refill is proposed only to reach target

## Testing requirements

- Unit: decision table tests

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
