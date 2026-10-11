# [MANDATE] Build governance transactions and collect owner signatures in the app

| Field | Value |
|---|---|
| **ID** | MDT-009 |
| **Epic** | M03 · Mandate, Payees, Exceptions & Pause |
| **Module** | `mandate` ([spec](../../../docs/modules/mandate/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | L (1.5–2 days; split if it grows) |
| **Area** | backend |
| **Status** | Ready for Assignment |
| **Traces to** | FR-225, BR-008, ADR-017, M03-D1, M03-D5 |
| **Blocks** | TRS-006, MDT-003, MDT-005, MDT-006, MDT-007, INV-011, MDT-010, WEB-025, MDT-011 |
| **Submission cut** | A |

## Context

This ticket belongs to the epic **Mandate, Payees, Exceptions & Pause**. It supports:

- F-020: Mandate configuration
- F-021: Mandate activation, versioning & lifecycle
- F-022: Payee registry with screening & cooling period
- F-025: One-time exception
- F-026: Pause, resume & revoke

Problem behind this work (from `docs/FEATURES.md`):

- **F-020** solves: Turns "trust the agent" into an explicit, enforceable, auditable grant (P2).
- **F-021** solves: Policy must exist where it is enforced. A database copy is only a cache (GA p.11).
- **F-022** solves: Vendor/BEC fraud. An attacker who changes an address in an invoice cannot get paid quickly, and the Owner has time to notice (P3).

## Objective

Every Owner change becomes one Safe transaction that owners sign in TreasuryPilot and one owner executes.

## Scope

- SafeTx builder (direct call or MultiSendCallOnly v1.4.1 bundle) with decoded calls and a human summary
- Safe nonce allocation (one open tx per nonce, queue the rest)
- EIP-712 SafeTx typed data
- POST signatures verified against the Safe's on-chain owners
- packed signatures and the execTransaction call for the executing owner
- submitted tx tracking via ExecutionSuccess/ExecutionFailure
- Superseded detection
- optional Safe Transaction Service proposal link

## Out of scope

Contract-specific payloads (MDT-003/005/006/007, TRS-006, INV-011 use this).

## Technical notes

Never store or ask for an owner key. Owners sign with their own wallets.

## Dependencies

- MDT-001: Create mandate, payee and exception schema
- TRS-005: Read and snapshot Safe configuration

## Acceptance criteria

- [ ] On Anvil with a real Safe v1.4.1 2-of-3, two in-app signatures and one execTransaction apply a MultiSend bundle
- [ ] A signature from a non-owner returns NOT_SAFE_OWNER
- [ ] An externally used nonce marks the tx Superseded
- [ ] Decoded calls equal the encoded calldata (round trip)

## Testing requirements

- Integration on Anvil with Safe v1.4.1

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
