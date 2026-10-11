# [WEB] Build the reconciliation view and export

| Field | Value |
|---|---|
| **ID** | WEB-014 |
| **Epic** | M16 · Web Application |
| **Module** | `web` ([spec](../../../docs/modules/web/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | M (~1 day) |
| **Area** | frontend |
| **Status** | Ready for Assignment |
| **Traces to** | FR-918 |
| **Blocks** | WEB-022 |
| **Submission cut** | B |

## Context

This ticket belongs to the epic **Web Application**. It supports:

- F-133: Reconciliation view

Problem behind this work (from `docs/FEATURES.md`):

- **F-133** solves: P5.

## Objective

Finance matches payments and downloads files.

## Scope

- Table of requests, transactions, fees, classification and status
- filters
- mark matched and discrepancy notes
- export buttons
- evidence bundle download

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- WEB-010: Build the treasury dashboard
- REC-004: Export reconciliation CSV and journal lines

## Acceptance criteria

- [ ] A paid request can be marked Matched
- [ ] Export downloads a CSV whose totals match the table

## Testing requirements

- E2E

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
