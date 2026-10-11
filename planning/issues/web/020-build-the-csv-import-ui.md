# [WEB] Build the CSV import UI

| Field | Value |
|---|---|
| **ID** | WEB-020 |
| **Epic** | M16 · Web Application |
| **Module** | `web` ([spec](../../../docs/modules/web/README.md)) |
| **Phase / Priority** | M1 / P1 |
| **Size** | S (≤ 0.5 day) |
| **Area** | frontend |
| **Status** | Ready for Assignment |
| **Traces to** | FR-306 |
| **Blocks** | — |
| **Submission cut** | After submission |

## Context

This ticket belongs to the epic **Web Application**. It supports:

- F-032: CSV bulk import

Problem behind this work (from `docs/FEATURES.md`):

- **F-032** solves: Batch payouts (e.g., 40+ contractors).

## Objective

Import invoices in bulk.

## Scope

- Template download
- upload with preview
- per-row errors
- partial import confirmation

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- WEB-007: Build the request list and manual entry form
- INV-005: Implement CSV bulk import

## Acceptance criteria

- [ ] Row errors are shown with row numbers
- [ ] Valid rows are imported

## Testing requirements

- E2E

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
