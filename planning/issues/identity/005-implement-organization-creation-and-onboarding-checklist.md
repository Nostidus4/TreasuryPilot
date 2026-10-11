# [IDENTITY] Implement organization creation and onboarding checklist

| Field | Value |
|---|---|
| **ID** | IDN-005 |
| **Epic** | M01 · Identity & Access |
| **Module** | `identity` ([spec](../../../docs/modules/identity/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | S (≤ 0.5 day) |
| **Area** | backend |
| **Status** | Ready for Assignment |
| **Traces to** | FR-007, FR-009 |
| **Blocks** | IDN-006, WEB-002 |
| **Submission cut** | A |

## Context

This ticket belongs to the epic **Identity & Access**. It supports:

- F-003: Organization creation & onboarding

Problem behind this work (from `docs/FEATURES.md`):

- **F-003** solves: Multi-tenant isolation; a clear starting point for J1.

## Objective

A user can create a tenant and see what to set up next.

## Scope

- POST /orgs (creator becomes OrgAdmin)
- GET /orgs/{id} with checklist computed from existing data
- PATCH settings

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- IDN-002: Implement magic-link login, sessions and CSRF

## Acceptance criteria

- [ ] Creator has the OrgAdmin role
- [ ] Checklist reflects real state (e.g. treasury exists)

## Testing requirements

- Integration

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
