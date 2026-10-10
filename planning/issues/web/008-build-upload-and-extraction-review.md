# [WEB] Build upload and extraction review

| Field | Value |
|---|---|
| **ID** | WEB-008 |
| **Epic** | M16 · Web Application |
| **Module** | `web` ([spec](../../../docs/modules/web/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | L (1.5–2 days; split if it grows) |
| **Area** | frontend |
| **Status** | Ready for Review |
| **Traces to** | FR-303, FR-310 |
| **Blocks** | WEB-009 |

## Context

This ticket belongs to the epic **Web Application**. It supports:

- F-031: PDF/image invoice upload & AI extraction
- F-035: Payment-terms extraction

Problem behind this work (from `docs/FEATURES.md`):

- **F-031** solves: Manual data entry and missed terms.
- **F-035** solves: Terms drive the value of the scheduler (P4).

## Objective

Operators check AI-extracted fields against the document before submitting.

## Scope

- Upload component with progress
- side-by-side document viewer and extracted fields with provenance highlights
- terms confirmation form
- flags panel
- manual fallback state

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- WEB-007: Build the request list and manual entry form
- AGT-005: Extract and validate payment terms

## Acceptance criteria

- [ ] Clicking a field highlights its source in the document
- [ ] Terms must be confirmed before submit
- [ ] A failed extraction shows the manual form with the document

## Testing requirements

- E2E with recorded extraction

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
