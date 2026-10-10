# [IDENTITY] Add MFA and step-up authentication

| Field | Value |
|---|---|
| **ID** | IDN-L01 |
| **Epic** | M01 · Identity & Access |
| **Module** | `identity` ([spec](../../../docs/modules/identity/README.md)) |
| **Phase / Priority** | Later / - |
| **Size** | L (1.5–2 days; split if it grows) |
| **Area** | backend |
| **Status** | Needs Discussion |
| **Traces to** | FR-016 |
| **Blocks** | — |

> **Phase: Later.** This ticket is intentionally coarser than M1 tickets. It must be re-estimated and split before it is scheduled.

## Context

This ticket belongs to the epic **Identity & Access**. It supports:

- F-006: MFA & session security

Problem behind this work (from `docs/FEATURES.md`):

- **F-006** solves: Account takeover leading to approvals or policy changes.

## Objective

Protect signer accounts with a second factor.

## Scope

- TOTP and WebAuthn enrolment
- step-up for approve, exception, mandate edits
- recovery codes

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- IDN-002: Implement magic-link login, sessions and CSRF

## Acceptance criteria

- [ ] Sensitive endpoints reject sessions without a fresh second factor

## Testing requirements

- Integration + security

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
