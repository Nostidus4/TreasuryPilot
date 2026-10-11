# [WEB] Build the request list and manual entry form

| Field | Value |
|---|---|
| **ID** | WEB-007 |
| **Epic** | M16 · Web Application |
| **Module** | `web` ([spec](../../../docs/modules/web/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | M (~1 day) |
| **Area** | frontend |
| **Status** | Ready for Assignment |
| **Traces to** | FR-301 |
| **Blocks** | WEB-008, WEB-020 |
| **Submission cut** | A |

## Context

This ticket belongs to the epic **Web Application**. It supports:

- F-030: Manual invoice entry

Problem behind this work (from `docs/FEATURES.md`):

- **F-030** solves: The baseline intake channel.

## Objective

Operators create and find invoices.

## Scope

- Filterable list by status and due date
- vendor picker with payees of that vendor
- create and edit form with field errors (bound vs free fields, warning that a bound edit invalidates the approval)
- revision history
- duplicate warning with link
- cancel with reason and Cancel on-chain banner

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- WEB-002: Build login, org selection and onboarding checklist
- INV-003: Implement manual request creation and editing

## Acceptance criteria

- [ ] A request can be created, edited and found by status
- [ ] A duplicate shows a blocking warning

## Testing requirements

- E2E

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
