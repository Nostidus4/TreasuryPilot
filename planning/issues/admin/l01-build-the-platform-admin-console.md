# [ADMIN] Build the platform admin console

| Field | Value |
|---|---|
| **ID** | ADM-L01 |
| **Epic** | M18 · Platform Admin & Billing |
| **Module** | `admin` ([spec](../../../docs/modules/admin/README.md)) |
| **Phase / Priority** | Later / - |
| **Size** | L (1.5–2 days; split if it grows) |
| **Area** | backend |
| **Status** | Accepted |
| **Traces to** | FR-924, BR-094 |
| **Blocks** | — |
| **Submission cut** | After submission |

> **Phase: Later.** Re-estimated as L (2 days) and split before scheduling:
>
> - Slice A — tenant operations and staff audit (M, ~1 day)
> - Slice B — consented read support and audit (M, ~1 day; depends on A)

## Context

This ticket belongs to the epic **Platform Admin & Billing**. It supports:

- F-150: Platform admin: tenant management

Problem behind this work (from `docs/FEATURES.md`):

- **F-150** solves: Operating a multi-tenant SaaS.

## Objective

Operate tenants and provide bounded, consented support access.

## Scope

- Slice A (M, ~1 day): tenant list, health and suspend endpoints with append-only staff events
- Slice B (M, ~1 day, after A): tenant-admin consent and revocation for time-limited read scope
- staff support summary requires a matching live grant and writes an access event

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Platform admin access stays on a separate staff credential and socket-peer IP allowlist;support reads expose tenant metadata and health counts only;customer fund movement and signing remain unavailable

## Dependencies

- IDN-006: Implement RBAC dependencies and tenant isolation

## Acceptance criteria

- [ ] No admin endpoint can move funds or sign
- [ ] No support read succeeds without tenant consent
- [ ] Expired or revoked grants deny access
- [ ] Grant and support-read actions are auditable

## Testing requirements

- Security tests for route surface and grant expiry
- API tests for consent and support access

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
