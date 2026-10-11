# [ENGINE] Implement the liquidity calculator

| Field | Value |
|---|---|
| **ID** | ENG-002 |
| **Epic** | M07 · Financial Engine (py-core) |
| **Module** | `financial-engine` ([spec](../../../docs/modules/financial-engine/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | M (~1 day) |
| **Area** | backend |
| **Status** | Ready for Assignment |
| **Traces to** | BR-032, BR-034, FR-403 |
| **Blocks** | ENG-003 |
| **Submission cut** | A |

## Context

This ticket belongs to the epic **Financial Engine (py-core)**. It supports:

- F-051: Liquidity calculator

Problem behind this work (from `docs/FEATURES.md`):

- **F-051** solves: Amounts are never computed by the LLM (BR-034).

## Objective

Deterministic shortage and refill numbers exactly as the domain spec defines.

## Scope

- Functions available, funding_deficit, shortage, preferred_refill, source_capacity, refill_bound (amount + target − balance), cap per docs/modules/financial-engine §6
- gas term fixed at 0 in M1
- golden tests from §8.1

## Out of scope

Decision table (ENG-003).

## Technical notes

Formulas are in docs/BUSINESS_RULES.md BR-032.

## Dependencies

- ENG-001: Create py-core money types and domain models

## Acceptance criteria

- [ ] Domain §3.4 example: Shortage 250, PreferredRefill 350, Bound 250
- [ ] UC-02 example: Shortage, PreferredRefill and Bound all equal 90
- [ ] All arithmetic is integer

## Testing requirements

- Unit: golden tests

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
