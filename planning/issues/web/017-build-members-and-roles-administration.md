# [WEB] Build members and roles administration

| Field | Value |
|---|---|
| **ID** | WEB-017 |
| **Epic** | M16 · Web Application |
| **Module** | `web` ([spec](../../../docs/modules/web/README.md)) |
| **Phase / Priority** | M1 / P1 |
| **Size** | M (~1 day) |
| **Area** | frontend |
| **Status** | Ready for Assignment |
| **Traces to** | FR-010–013 |
| **Blocks** | — |
| **Submission cut** | After submission |

## Context

This ticket belongs to the epic **Web Application**. It supports:

- F-004: Member invitation & role management

Problem behind this work (from `docs/FEATURES.md`):

- **F-004** solves: Separation of duties and least privilege.

## Objective

OrgAdmins manage people.

## Scope

- Member list
- invite form
- role editor
- wallet-link status for signer roles
- solo-mode toggle for the Owner with a warning

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- WEB-002: Build login, org selection and onboarding checklist
- IDN-007: Implement invites and membership management

## Acceptance criteria

- [ ] The last admin cannot be removed in the UI
- [ ] Signer roles without a wallet are marked inactive

## Testing requirements

- E2E

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
