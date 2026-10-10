# [MANDATE] Create mandate, payee and exception schema

| Field | Value |
|---|---|
| **ID** | MDT-001 |
| **Epic** | M03 · Mandate, Payees, Exceptions & Pause |
| **Module** | `mandate` ([spec](../../../docs/modules/mandate/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | S (≤ 0.5 day) |
| **Area** | backend |
| **Status** | Ready for Review |
| **Traces to** | DATA_MODEL §2.3 |
| **Blocks** | MDT-002, MDT-004, INV-001, CMP-001 |

## Context

This ticket belongs to the epic **Mandate, Payees, Exceptions & Pause**. It supports:

- F-020: Mandate configuration
- F-021: Mandate activation, versioning & lifecycle
- F-022: Payee registry with screening & cooling period
- F-023: Spending limits & treasury-wide UTC daily counters
- F-024: Minimum buffer & target balance protection
- F-025: One-time exception
- F-026: Pause, resume & revoke

Problem behind this work (from `docs/FEATURES.md`):

- **F-020** solves: Turns "trust the agent" into an explicit, enforceable, auditable grant (P2).
- **F-021** solves: Policy must exist where it is enforced. A database copy is only a cache (GA p.11).
- **F-022** solves: Vendor/BEC fraud. An attacker who changes an address in an invoice cannot get paid quickly, and the Owner has time to notice (P3).

## Objective

Tables for mandate versions and events, vendors, payees, screenings and exceptions.

## Scope

- Alembic migration and models
- immutability trigger on mandate_versions rows
- constraints from DATA_MODEL §2.3

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- TRS-001: Create treasury and chain schema

## Acceptance criteria

- [ ] Migration applies and downgrades
- [ ] Updating a mandate_versions config row is rejected by the database

## Testing requirements

- Integration: migration test

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
