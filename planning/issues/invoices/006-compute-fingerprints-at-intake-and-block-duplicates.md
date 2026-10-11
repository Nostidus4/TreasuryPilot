# [INVOICES] Compute fingerprints at intake and block duplicates

| Field | Value |
|---|---|
| **ID** | INV-006 |
| **Epic** | M05 · Invoices & Payment Requests |
| **Module** | `invoices` ([spec](../../../docs/modules/invoices/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | S (≤ 0.5 day) |
| **Area** | backend |
| **Status** | Ready for Review |
| **Traces to** | BR-071, FR-314 |
| **Blocks** | INV-007 |
| **Submission cut** | A |

## Context

This ticket belongs to the epic **Invoices & Payment Requests**. It supports:

- F-037: Duplicate-invoice fingerprint

Problem behind this work (from `docs/FEATURES.md`):

- **F-037** solves: The same invoice entered under two request IDs (a gap the source admits in UC-04).

## Objective

Duplicates are caught before approval.

## Scope

- Fingerprint on create and edit
- duplicate check within the treasury
- DUPLICATE_FINGERPRINT blocks submit
- link to the existing request in the error

## Out of scope

On-chain registry (SC-012).

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- INV-003: Implement manual request creation and editing
- ENG-009: Implement invoice fingerprint normalization and hashing

## Acceptance criteria

- [ ] A second request with an equivalent invoice number cannot be submitted
- [ ] The error identifies the original request

## Testing requirements

- Integration

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
