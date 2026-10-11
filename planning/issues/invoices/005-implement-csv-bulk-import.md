# [INVOICES] Implement CSV bulk import

| Field | Value |
|---|---|
| **ID** | INV-005 |
| **Epic** | M05 · Invoices & Payment Requests |
| **Module** | `invoices` ([spec](../../../docs/modules/invoices/README.md)) |
| **Phase / Priority** | M1 / P1 |
| **Size** | M (~1 day) |
| **Area** | backend |
| **Status** | Ready for Assignment |
| **Traces to** | FR-306–307 |
| **Blocks** | WEB-020 |
| **Submission cut** | After submission |

## Context

This ticket belongs to the epic **Invoices & Payment Requests**. It supports:

- F-032: CSV bulk import

Problem behind this work (from `docs/FEATURES.md`):

- **F-032** solves: Batch payouts (e.g., 40+ contractors).

## Objective

Import many invoices at once with per-row feedback.

## Scope

- CSV template per docs/modules/invoices §7.2
- UTF-8 (BOM allowed) and exact header validation
- row-by-row validation (vendor by normalized_ref, payee must belong to vendor, amount precision, ISO dates)
- fingerprint check against DB and earlier rows
- flags per row
- dryRun mode
- csv_imports record
- downloadable error report with formula neutralization
- max 1,000 rows

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- INV-003: Implement manual request creation and editing

## Acceptance criteria

- [ ] 500 valid rows import in under 10 seconds
- [ ] Invalid rows are reported with row number, field and code
- [ ] Two rows with the same fingerprint: the second is rejected
- [ ] Cells starting with = + - @ are neutralized in the error report
- [ ] dryRun writes nothing

## Testing requirements

- Integration + performance test

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
