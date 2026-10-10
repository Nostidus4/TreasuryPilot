# [ADMIN] Build the platform admin console

| Field | Value |
|---|---|
| **ID** | ADM-L01 |
| **Epic** | M18 · Platform Admin & Billing |
| **Module** | `admin` ([spec](../../../docs/modules/admin/README.md)) |
| **Phase / Priority** | Later / - |
| **Size** | L (1.5–2 days; split if it grows) |
| **Area** | backend |
| **Status** | Needs Discussion |
| **Traces to** | FR-924, BR-094 |
| **Blocks** | — |

> **Phase: Later.** This ticket is intentionally coarser than M1 tickets. It must be re-estimated and split before it is scheduled.

## Context

This ticket belongs to the epic **Platform Admin & Billing**. It supports:

- F-150: Platform admin: tenant management

Problem behind this work (from `docs/FEATURES.md`):

- **F-150** solves: Operating a multi-tenant SaaS.

## Objective

Operate tenants.

## Scope

- Tenant list, suspend, health
- read-only support access with consent and audit

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- IDN-006: Implement RBAC dependencies and tenant isolation

## Acceptance criteria

- [ ] No admin endpoint can move funds or sign

## Testing requirements

- Security review

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
