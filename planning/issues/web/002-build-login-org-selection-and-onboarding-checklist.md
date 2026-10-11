# [WEB] Build login, org selection and onboarding checklist

| Field | Value |
|---|---|
| **ID** | WEB-002 |
| **Epic** | M16 · Web Application |
| **Module** | `web` ([spec](../../../docs/modules/web/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | M (~1 day) |
| **Area** | frontend |
| **Status** | Ready for Review |
| **Traces to** | FR-001, FR-009 |
| **Blocks** | WEB-003, WEB-007, WEB-017 |
| **Submission cut** | A |

## Context

This ticket belongs to the epic **Web Application**. It supports:

- F-001: Account sign-up & login
- F-003: Organization creation & onboarding

Problem behind this work (from `docs/FEATURES.md`):

- **F-001** solves: A multi-tenant product needs human identities that are independent of keys. Finance and Auditor users may not hold wallets at all.
- **F-003** solves: Multi-tenant isolation; a clear starting point for J1.

## Objective

Users can sign in and see what to set up.

## Scope

- Magic-link request and verify pages
- org create and switch
- checklist page driven by the API

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- WEB-001: Create the web app shell
- IDN-005: Implement organization creation and onboarding checklist

## Acceptance criteria

- [ ] A new user can sign in, create an org and see the checklist
- [ ] Errors from the API are shown clearly

## Testing requirements

- E2E smoke

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
