# [INVOICES] Implement document upload to private storage

| Field | Value |
|---|---|
| **ID** | INV-004 |
| **Epic** | M05 · Invoices & Payment Requests |
| **Module** | `invoices` ([spec](../../../docs/modules/invoices/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | S (≤ 0.5 day) |
| **Area** | backend |
| **Status** | Ready for Assignment |
| **Traces to** | FR-303, BR-074, NFR-PRIV-02 |
| **Blocks** | INV-L01, AGT-004 |
| **Submission cut** | A |

## Context

This ticket belongs to the epic **Invoices & Payment Requests**. It supports:

- F-031: PDF/image invoice upload & AI extraction

Problem behind this work (from `docs/FEATURES.md`):

- **F-031** solves: Manual data entry and missed terms.

## Objective

Invoice files are stored privately and linked to a draft.

## Scope

- POST /requests/upload (PDF, PNG, JPG ≤ 10 MB, ≤ 20 pages, type checked by magic bytes)
- store in the private bucket with sha256
- documents record
- signed URL for viewing
- enqueue extraction on the ai queue
- POST extraction/confirm storing final fields and extraction_confirmed_by
- MULTI_INVOICE_DOCUMENT when M09 reports more than one invoice

## Out of scope

The extraction itself (AGT-004).

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- INV-003: Implement manual request creation and editing

## Acceptance criteria

- [ ] Unsupported type returns 415 and oversize returns 413
- [ ] A renamed executable with a .pdf name is refused
- [ ] Files are not publicly readable
- [ ] Submit is refused with EXTRACTION_UNCONFIRMED until the form is confirmed

## Testing requirements

- Integration with MinIO

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
