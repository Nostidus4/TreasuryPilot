# [WEB] Build the governance signing inbox

| Field | Value |
|---|---|
| **ID** | WEB-025 |
| **Epic** | M16 · Web Application |
| **Module** | `web` ([spec](../../../docs/modules/web/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | M (~1 day) |
| **Area** | frontend |
| **Status** | Ready for Assignment |
| **Traces to** | FR-225, M03-D1 |
| **Blocks** | WEB-005 |
| **Submission cut** | A |

## Context

This ticket belongs to the epic **Web Application**. It supports:

- F-020: Mandate configuration
- F-021: Mandate activation, versioning & lifecycle
- F-022: Payee registry with screening & cooling period
- F-023: Spending limits & treasury-wide UTC daily counters
- F-024: Minimum buffer & target balance protection
- F-025: One-time exception
- F-026: Pause, resume & revoke

Problem behind this work (from `docs/FEATURES.md`):

- **F-020** solves: Turns "trust the agent" into an explicit, enforceable, auditable grant (P2).
- **F-021** solves: Policy must exist where it is enforced. A database copy is only a cache (GA p.11).
- **F-022** solves: Vendor/BEC fraud. An attacker who changes an address in an invoice cannot get paid quickly, and the Owner has time to notice (P3).

## Objective

Owners see, sign and execute pending Safe transactions inside TreasuryPilot.

## Scope

- List of governance txs by status
- detail with decoded calls, human summary and diff
- sign with the connected wallet (EIP-712 SafeTx)
- progress n/threshold
- Execute button for the last owner sending execTransaction
- Superseded and failed states
- optional open-in-Safe{Wallet} link

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

The typed data shown must be the object passed to signTypedData.

## Dependencies

- WEB-003: Add wallet connection and SIWE linking
- MDT-009: Build governance transactions and collect owner signatures in the app

## Acceptance criteria

- [ ] Two owners can sign and the second executes
- [ ] A non-owner sees the item read-only
- [ ] A Superseded tx cannot be signed

## Testing requirements

- E2E with mock wallets

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
