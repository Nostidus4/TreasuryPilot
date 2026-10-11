# [IDENTITY] Add OIDC single sign-on

| Field | Value |
|---|---|
| **ID** | IDN-L02 |
| **Epic** | M01 · Identity & Access |
| **Module** | `identity` ([spec](../../../docs/modules/identity/README.md)) |
| **Phase / Priority** | Later / - |
| **Size** | L (1.5–2 days; split if it grows) |
| **Area** | backend |
| **Status** | Needs Discussion |
| **Traces to** | FR-017 |
| **Blocks** | IDN-L03 |
| **Submission cut** | After submission |

> **Phase: Later.** This ticket is intentionally coarser than M1 tickets. It must be re-estimated and split before it is scheduled.

## Context

This ticket belongs to the epic **Identity & Access**. It supports:

- F-007: Enterprise SSO (OIDC/SAML)

Problem behind this work (from `docs/FEATURES.md`):

- **F-007** solves: Enterprise onboarding and offboarding.

## Objective

Enterprise login through the company identity provider.

## Scope

- OIDC login
- group-to-role mapping
- just-in-time provisioning

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- IDN-006: Implement RBAC dependencies and tenant isolation

## Acceptance criteria

- [ ] Login works with one OIDC provider
- [ ] Deprovisioning revokes sessions within 5 minutes

## Testing requirements

- Integration

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
