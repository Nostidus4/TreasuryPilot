# [IDENTITY] Implement magic-link login, sessions and CSRF

| Field | Value |
|---|---|
| **ID** | IDN-002 |
| **Epic** | M01 · Identity & Access |
| **Module** | `identity` ([spec](../../../docs/modules/identity/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | M (~1 day) |
| **Area** | backend |
| **Status** | Ready for Assignment |
| **Traces to** | FR-001, FR-003, ADR-009 |
| **Blocks** | IDN-003, IDN-004, IDN-005, IDN-L01 |
| **Submission cut** | A |

## Context

This ticket belongs to the epic **Identity & Access**. It supports:

- F-001: Account sign-up & login

Problem behind this work (from `docs/FEATURES.md`):

- **F-001** solves: A multi-tenant product needs human identities that are independent of keys. Finance and Auditor users may not hold wallets at all.

## Objective

Users can sign in by email and hold a secure session.

## Scope

- POST /auth/magic-link, /auth/magic-link/verify, /auth/logout, GET /me
- single-use 15-minute token stored hashed
- httpOnly Secure SameSite=Lax cookie with server-side session
- CSRF double-submit on mutations
- email via Resend, console in local

## Out of scope

Rate limiting (IDN-003).

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- IDN-001: Create identity database schema and migrations

## Acceptance criteria

- [ ] A valid token creates a session and cannot be reused
- [ ] Expired tokens return TOKEN_EXPIRED
- [ ] Mutations without the CSRF token are rejected
- [ ] Sessions expire on idle and absolute timeouts

## Testing requirements

- Unit + integration: auth flow tests

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
