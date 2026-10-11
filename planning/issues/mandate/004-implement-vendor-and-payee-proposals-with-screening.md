# [MANDATE] Implement vendor and payee proposals with screening

| Field | Value |
|---|---|
| **ID** | MDT-004 |
| **Epic** | M03 · Mandate, Payees, Exceptions & Pause |
| **Module** | `mandate` ([spec](../../../docs/modules/mandate/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | M (~1 day) |
| **Area** | backend |
| **Status** | Ready for Review |
| **Traces to** | FR-211, BR-085 |
| **Blocks** | MDT-005, INV-003 |
| **Submission cut** | A |

## Context

This ticket belongs to the epic **Mandate, Payees, Exceptions & Pause**. It supports:

- F-022: Payee registry with screening & cooling period

Problem behind this work (from `docs/FEATURES.md`):

- **F-022** solves: Vendor/BEC fraud. An attacker who changes an address in an invoice cannot get paid quickly, and the Owner has time to notice (P3).

## Objective

Operators can propose payees; nothing becomes payable without screening and the Owner.

## Scope

- Vendor CRUD (minimal)
- POST /payees creating a payee in Screening and running the screening adapter
- result stored
- hit → blocked

## Out of scope

On-chain registration (MDT-005).

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- MDT-001: Create mandate, payee and exception schema
- CMP-001: Build the screening adapter and fixture provider

## Acceptance criteria

- [ ] A screening hit returns SCREENING_HIT and the payee cannot proceed
- [ ] Provider error blocks registration
- [ ] Duplicate address is rejected

## Testing requirements

- Integration with the fixture provider

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
