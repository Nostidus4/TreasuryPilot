# [IDENTITY] Implement RBAC dependencies and tenant isolation

| Field | Value |
|---|---|
| **ID** | IDN-006 |
| **Epic** | M01 · Identity & Access |
| **Module** | `identity` ([spec](../../../docs/modules/identity/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | M (~1 day) |
| **Area** | backend |
| **Status** | Ready for Review |
| **Traces to** | FR-008, FR-011, BR-093, NFR-PRIV-05 |
| **Blocks** | IDN-007, IDN-008, IDN-L02, TRS-004, ADM-L01 |

## Context

This ticket belongs to the epic **Identity & Access**. It supports:

- F-004: Member invitation & role management

Problem behind this work (from `docs/FEATURES.md`):

- **F-004** solves: Separation of duties and least privilege.

## Objective

Every endpoint enforces membership and role, and no data crosses organizations.

## Scope

- FastAPI dependencies require_member and require_role
- repository base class that always filters by org_id
- generic cross-tenant test that hits every org-scoped route as a non-member

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Non-members get 404, not 403.

## Dependencies

- IDN-005: Implement organization creation and onboarding checklist

## Acceptance criteria

- [ ] A non-member receives 404 on all org routes
- [ ] A member without the role receives 403
- [ ] The cross-tenant test enumerates routes automatically

## Testing requirements

- Security: cross-tenant test suite

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
