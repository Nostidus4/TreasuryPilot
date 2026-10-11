# [IDENTITY] Add SAML and SCIM provisioning

| Field | Value |
|---|---|
| **ID** | IDN-L03 |
| **Epic** | M01 · Identity & Access |
| **Module** | `identity` ([spec](../../../docs/modules/identity/README.md)) |
| **Phase / Priority** | Later / - |
| **Size** | L (1.5–2 days; split if it grows) |
| **Area** | backend |
| **Status** | Accepted |
| **Traces to** | FR-017 |
| **Blocks** | — |
| **Submission cut** | After submission |

> **Phase: Later.** This ticket is intentionally coarser than M1 tickets. It must be re-estimated and split before it is scheduled.

## Context

This ticket belongs to the epic **Identity & Access**. It supports:

- F-007: Enterprise SSO (OIDC/SAML)

Problem behind this work (from `docs/FEATURES.md`):

- **F-007** solves: Enterprise onboarding and offboarding.

## Objective

Support SAML identity providers and automated provisioning.

## Scope

- SAML SP
- SCIM users and groups

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- IDN-L02: Add OIDC single sign-on

## Acceptance criteria

- [ ] SCIM deprovision removes access

## Testing requirements

- Integration

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
