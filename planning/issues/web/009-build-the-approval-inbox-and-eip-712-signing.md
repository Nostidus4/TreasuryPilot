# [WEB] Build the approval inbox and EIP-712 signing

| Field | Value |
|---|---|
| **ID** | WEB-009 |
| **Epic** | M16 · Web Application |
| **Module** | `web` ([spec](../../../docs/modules/web/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | L (1.5–2 days; split if it grows) |
| **Area** | frontend |
| **Status** | Ready for Review |
| **Traces to** | FR-313, FR-316, FR-916 |
| **Blocks** | — |

## Context

This ticket belongs to the epic **Web Application**. It supports:

- F-131: Approval inbox with diff & flags
- F-038: Invoice approval via EIP-712 signature

Problem behind this work (from `docs/FEATURES.md`):

- **F-131** solves: Fast, informed approvals (P3).
- **F-038** solves: Approval is cryptographic and bound to exact fields, not a backend flag.

## Objective

Approvers review, acknowledge flags and sign.

## Scope

- Inbox list
- detail with document, fields, history diff, flags with evidence, confirmed terms
- acknowledge high flags
- display the typed data and sign with the wallet
- reject with reason
- maker-checker message

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

The typed data shown must be the object passed to signTypedData.

## Dependencies

- WEB-008: Build upload and extraction review
- INV-010: Implement approval typed data and signature verification

## Acceptance criteria

- [ ] Signing is disabled until high flags are acknowledged
- [ ] After signing the request shows Approved
- [ ] The creator sees why they cannot approve

## Testing requirements

- E2E with a mock wallet

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
