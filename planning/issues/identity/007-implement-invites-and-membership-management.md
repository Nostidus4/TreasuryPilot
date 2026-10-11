# [IDENTITY] Implement invites and membership management

| Field | Value |
|---|---|
| **ID** | IDN-007 |
| **Epic** | M01 · Identity & Access |
| **Module** | `identity` ([spec](../../../docs/modules/identity/README.md)) |
| **Phase / Priority** | M1 / P1 |
| **Size** | M (~1 day) |
| **Area** | backend |
| **Status** | Ready for Assignment |
| **Traces to** | FR-010, FR-012–013 |
| **Blocks** | WEB-017 |
| **Submission cut** | After submission |

## Context

This ticket belongs to the epic **Identity & Access**. It supports:

- F-004: Member invitation & role management

Problem behind this work (from `docs/FEATURES.md`):

- **F-004** solves: Separation of duties and least privilege.

## Objective

OrgAdmins can add people and assign the eight roles.

## Scope

- Invite create/accept endpoints with expiring hashed tokens
- role change and member removal
- last-admin and last-owner guards
- signer roles inactive until a wallet is linked

## Out of scope

Invite emails beyond a simple link.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- IDN-006: Implement RBAC dependencies and tenant isolation

## Acceptance criteria

- [ ] Accepted invite creates a membership with the roles
- [ ] Removing the last OrgAdmin or Owner is refused
- [ ] A signer role without a linked wallet cannot sign

## Testing requirements

- Integration

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
