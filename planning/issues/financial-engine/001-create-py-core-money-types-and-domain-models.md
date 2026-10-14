# [ENGINE] Create py-core money types and domain models

| Field | Value |
|---|---|
| **ID** | ENG-001 |
| **Epic** | M07 · Financial Engine (py-core) |
| **Module** | `financial-engine` ([spec](../../../docs/modules/financial-engine/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | M (~1 day) |
| **Area** | backend |
| **Status** | Ready for Assignment |
| **Traces to** | ADR-014, BR-083, FR-109, ADR-019 |
| **Blocks** | ENG-002, ENG-005, ENG-009, ENG-010, ENG-015, POL-001, MDT-002, EXE-012 |
| **Submission cut** | A |

## Context

This ticket belongs to the epic **Financial Engine (py-core)**. It supports:

- F-013: Asset registry
- F-051: Liquidity calculator

Problem behind this work (from `docs/FEATURES.md`):

- **F-013** solves: Prevents token impersonation and decimal errors.
- **F-051** solves: Amounts are never computed by the LLM (BR-034).

## Objective

A typed, float-free foundation for all money logic.

## Scope

- BaseUnits type (non-negative int) with parse/format using decimals
- frozen Pydantic models per docs/modules/financial-engine §4: Asset, LateFee, PaymentTerms, WalletState, Limits, PolicyView, Snapshot, ApprovedRequest, RefillDecision, ScheduledItem, Infeasible, Schedule
- UTC day helpers (day number, 30-minute midnight cut-over, M07-D3)
- JSON serialization of amounts as decimal strings
- Snapshot fields safe_usdc, a_usdc, pool_available, supply_rate_bps, borrow_rate_bps, health_factor, debt

## Out of scope

Any I/O.

## Technical notes

Reject floats at the type level. No implicit conversion.

## Dependencies

- DEV-001: Initialize monorepo skeleton

## Acceptance criteria

- [ ] Constructing an amount from a float raises
- [ ] Round trip string→BaseUnits→string is exact for 6 and 18 decimals
- [ ] Models serialize amounts as strings

## Testing requirements

- Unit: type and serialization tests

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
