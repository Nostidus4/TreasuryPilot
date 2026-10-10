# [ENGINE] Implement invoice fingerprint normalization and hashing

| Field | Value |
|---|---|
| **ID** | ENG-009 |
| **Epic** | M07 · Financial Engine (py-core) |
| **Module** | `financial-engine` ([spec](../../../docs/modules/financial-engine/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | S (≤ 0.5 day) |
| **Area** | backend |
| **Status** | Ready for Review |
| **Traces to** | BR-071, FR-314 |
| **Blocks** | INV-006 |

## Context

This ticket belongs to the epic **Financial Engine (py-core)**. It supports:

- F-037: Duplicate-invoice fingerprint

Problem behind this work (from `docs/FEATURES.md`):

- **F-037** solves: The same invoice entered under two request IDs (a gap the source admits in UC-04).

## Objective

One canonical fingerprint for an invoice, identical to what the contract stores.

## Scope

- normalize(vendor_id, invoice_no) (trim, case-fold, strip separators)
- keccak256 over the packed fields with amount and asset
- test vectors shared with contracts

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- ENG-001: Create py-core money types and domain models

## Acceptance criteria

- [ ] 'INV-001', 'inv 001' and 'INV001' produce the same fingerprint
- [ ] The value matches the Solidity computation in a shared vector

## Testing requirements

- Unit: normalization and vector tests

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
