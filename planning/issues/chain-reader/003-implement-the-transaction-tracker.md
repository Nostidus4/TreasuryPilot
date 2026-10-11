# [CHAIN] Implement the transaction tracker

| Field | Value |
|---|---|
| **ID** | CHR-003 |
| **Epic** | M06 · Chain Reader & Tx Tracking |
| **Module** | `chain-reader` ([spec](../../../docs/modules/chain-reader/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | M (~1 day) |
| **Area** | backend |
| **Status** | Ready for Assignment |
| **Traces to** | BR-053, BR-060, FR-601, PH-5, M06-D1, M06-D5 |
| **Blocks** | MDT-003, CHR-004, EXE-008, RCV-002 |
| **Submission cut** | A |

## Context

This ticket belongs to the epic **Chain Reader & Tx Tracking**. It supports:

- F-070: Transaction tracking & confirmation

Problem behind this work (from `docs/FEATURES.md`):

- **F-070** solves: "Broadcast" is not "done". Paid only after confirmation (BR-053).

## Objective

Know the true status of every submitted transaction.

## Scope

- Celery task every 6 s
- status per docs/modules/chain-reader §5 (Submitted, Pending, Confirmed, Reverted, Dropped, Unknown)
- Confirmed at 3 confirmations and secondary cross-check Match
- Unknown after 10 min without receipt and not in mempool
- replacement linking by (from, nonce)
- revert selector decoded via POL-001
- day attribution by mined block timestamp

## Out of scope

Reorgs (CHR-004).

## Technical notes

Never set a Failed status on timeout.

## Dependencies

- CHR-001: Build the RPC client with failover
- EXE-001: Create operations (outbox), transactions and gas ledger schema

## Acceptance criteria

- [ ] A transaction is Confirmed only after 3 confirmations and a matching cross-check
- [ ] A cross-check mismatch never yields Confirmed
- [ ] A timeout sets Unknown, never Failed
- [ ] A replacement with the same nonce marks the original Dropped and links it

## Testing requirements

- Integration on Anvil

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
