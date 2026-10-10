# [IDENTITY] Rate-limit authentication endpoints

| Field | Value |
|---|---|
| **ID** | IDN-003 |
| **Epic** | M01 · Identity & Access |
| **Module** | `identity` ([spec](../../../docs/modules/identity/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | S (≤ 0.5 day) |
| **Area** | backend |
| **Status** | Ready for Review |
| **Traces to** | FR-002, NFR-SEC-09 |
| **Blocks** | — |

## Context

This ticket belongs to the epic **Identity & Access**. It supports:

- F-001: Account sign-up & login

Problem behind this work (from `docs/FEATURES.md`):

- **F-001** solves: A multi-tenant product needs human identities that are independent of keys. Finance and Auditor users may not hold wallets at all.

## Objective

Stop brute force and email flooding.

## Scope

- Per-IP and per-email limits on magic-link and verify using Redis
- 429 with RATE_LIMITED and Retry-After

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- IDN-002: Implement magic-link login, sessions and CSRF

## Acceptance criteria

- [ ] Exceeding the limit returns 429
- [ ] Limits reset after the window

## Testing requirements

- Integration: limit test

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
