# [IDENTITY] Create identity database schema and migrations

| Field | Value |
|---|---|
| **ID** | IDN-001 |
| **Epic** | M01 · Identity & Access |
| **Module** | `identity` ([spec](../../../docs/modules/identity/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | S (≤ 0.5 day) |
| **Area** | backend |
| **Status** | Ready for Review |
| **Traces to** | DATA_MODEL §2.1 |
| **Blocks** | IDN-002, TRS-001, AUD-001 |
| **Submission cut** | A |

## Context

This ticket belongs to the epic **Identity & Access**. It supports:

- F-001: Account sign-up & login
- F-002: Wallet linking via Sign-In With Ethereum
- F-003: Organization creation & onboarding
- F-004: Member invitation & role management
- F-005: Maker-checker separation

Problem behind this work (from `docs/FEATURES.md`):

- **F-001** solves: A multi-tenant product needs human identities that are independent of keys. Finance and Auditor users may not hold wallets at all.
- **F-002** solves: Approvals and exceptions must be signed by keys the contract recognizes. Logging in to the app is not the same as on-chain authority (GA p.11).
- **F-003** solves: Multi-tenant isolation; a clear starting point for J1.

## Objective

Tables for users, sessions, magic links, wallet links, nonces, organizations, memberships and invites.

## Scope

- Alembic migration
- SQLAlchemy models
- partial unique index on wallet_links.address
- citext email

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- DEV-002: Create Docker Compose stack (local profile)

## Acceptance criteria

- [ ] Migration applies on an empty database and downgrades cleanly
- [ ] Constraints from DATA_MODEL §2.1 exist

## Testing requirements

- Integration: migration up/down test

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
