# [AGENT] Implement invoice extraction

| Field | Value |
|---|---|
| **ID** | AGT-004 |
| **Epic** | M09 · AI Agent |
| **Module** | `agent` ([spec](../../../docs/modules/agent/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | M (~1 day) |
| **Area** | ai |
| **Status** | Ready for Review |
| **Traces to** | FR-303–305 |
| **Blocks** | INV-L01, AGT-005, AGT-006 |
| **Submission cut** | A |

## Context

This ticket belongs to the epic **AI Agent**. It supports:

- F-031: PDF/image invoice upload & AI extraction

Problem behind this work (from `docs/FEATURES.md`):

- **F-031** solves: Manual data entry and missed terms.

## Objective

Turn an uploaded invoice into a draft with per-field provenance.

## Scope

- Celery task on the ai queue
- send the PDF/image to Claude
- InvoiceExtraction schema: vendor name, invoice number, amount, currency, due date, payee address as found, each with page and text span
- write extractions and prefill the draft
- on error mark the request for manual entry

## Out of scope

Terms (AGT-005) and instruction detection (AGT-006).

## Technical notes

The extracted address is only compared, never applied.

## Dependencies

- AGT-003: Implement untrusted-content wrapping and sanitization
- AGT-002: Log every AI call and fail closed
- INV-004: Implement document upload to private storage

## Acceptance criteria

- [ ] A sample invoice yields the expected fields with provenance
- [ ] Timeout leaves the request in manual-entry mode with no guessed values
- [ ] The registered payee address is never modified

## Testing requirements

- Integration with recorded responses

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
