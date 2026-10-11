# [IDENTITY] Implement SIWE wallet linking

| Field | Value |
|---|---|
| **ID** | IDN-004 |
| **Epic** | M01 · Identity & Access |
| **Module** | `identity` ([spec](../../../docs/modules/identity/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | M (~1 day) |
| **Area** | backend |
| **Status** | Ready for Assignment |
| **Traces to** | FR-004–006, BR-006 |
| **Blocks** | WEB-003 |
| **Submission cut** | A |

## Context

This ticket belongs to the epic **Identity & Access**. It supports:

- F-002: Wallet linking via Sign-In With Ethereum

Problem behind this work (from `docs/FEATURES.md`):

- **F-002** solves: Approvals and exceptions must be signed by keys the contract recognizes. Logging in to the app is not the same as on-chain authority (GA p.11).

## Objective

Signer roles can prove control of their address.

## Scope

- GET /auth/siwe/nonce
- POST /me/wallets verifying the SIWE message (domain, chain id, nonce, expiry)
- ERC-1271 path for contract wallets
- DELETE /me/wallets/{address}
- audit entries

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Use the `siwe` library. Nonces are single use.

## Dependencies

- IDN-002: Implement magic-link login, sessions and CSRF

## Acceptance criteria

- [ ] A valid signature links the address
- [ ] Replayed nonce is rejected
- [ ] An address linked to another user returns ADDRESS_LINKED_ELSEWHERE
- [ ] Contract-wallet signatures verify through ERC-1271

## Testing requirements

- Unit + integration with a test key

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
