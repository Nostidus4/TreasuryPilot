# [IDENTITY] Implement the maker-checker service and solo mode

| Field | Value |
|---|---|
| **ID** | IDN-008 |
| **Epic** | M01 · Identity & Access |
| **Module** | `identity` ([spec](../../../docs/modules/identity/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | S (≤ 0.5 day) |
| **Area** | backend |
| **Status** | Ready for Review |
| **Traces to** | BR-005, FR-014–015 |
| **Blocks** | INV-010 |
| **Submission cut** | A |

## Context

This ticket belongs to the epic **Identity & Access**. It supports:

- F-005: Maker-checker separation

Problem behind this work (from `docs/FEATURES.md`):

- **F-005** solves: Prevents a single person from creating and approving a payment.

## Objective

The creator or last editor of a request cannot approve it.

## Scope

- assert_maker_checker(request, user) used by the approval endpoints
- org solo_mode flag settable only by the Owner
- solo approvals marked on the record and in audit

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- IDN-006: Implement RBAC dependencies and tenant isolation

## Acceptance criteria

- [ ] Creator approving returns MAKER_CHECKER
- [ ] With solo mode on, the approval succeeds and is flagged
- [ ] Only the Owner can toggle solo mode

## Testing requirements

- Unit + integration

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
