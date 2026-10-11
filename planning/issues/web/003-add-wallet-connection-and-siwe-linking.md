# [WEB] Add wallet connection and SIWE linking

| Field | Value |
|---|---|
| **ID** | WEB-003 |
| **Epic** | M16 · Web Application |
| **Module** | `web` ([spec](../../../docs/modules/web/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | S (≤ 0.5 day) |
| **Area** | frontend |
| **Status** | Ready for Review |
| **Traces to** | FR-004 |
| **Blocks** | WEB-004 |
| **Submission cut** | A |

## Context

This ticket belongs to the epic **Web Application**. It supports:

- F-002: Wallet linking via Sign-In With Ethereum

Problem behind this work (from `docs/FEATURES.md`):

- **F-002** solves: Approvals and exceptions must be signed by keys the contract recognizes. Logging in to the app is not the same as on-chain authority (GA p.11).

## Objective

Signer roles link their wallet from the browser.

## Scope

- wagmi + RainbowKit setup for the configured chain
- SIWE message signing and submit
- linked-wallet list and unlink
- wrong-network prompt

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- WEB-002: Build login, org selection and onboarding checklist
- IDN-004: Implement SIWE wallet linking

## Acceptance criteria

- [ ] A connected wallet can be linked and appears in the profile
- [ ] A wrong network shows a switch prompt

## Testing requirements

- E2E with a mock wallet

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
