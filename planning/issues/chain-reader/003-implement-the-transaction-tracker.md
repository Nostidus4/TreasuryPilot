# [CHAIN] Implement the transaction tracker

| Field | Value |
|---|---|
| **ID** | CHR-003 |
| **Epic** | M06 · Chain Reader & Tx Tracking |
| **Module** | `chain-reader` ([spec](../../../docs/modules/chain-reader/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | M (~1 day) |
| **Area** | backend |
| **Status** | Ready for Review |
| **Traces to** | BR-053, FR-601 |
| **Blocks** | MDT-003, CHR-004, EXE-008, RCV-002 |

## Context

This ticket belongs to the epic **Chain Reader & Tx Tracking**. It supports:

- F-070: Transaction tracking & confirmation

Problem behind this work (from `docs/FEATURES.md`):

- **F-070** solves: "Broadcast" is not "done". Paid only after confirmation (BR-053).

## Objective

Know the true status of every submitted transaction.

## Scope

- Celery task polling receipts
- status Submitted → Pending → Confirmed after N confirmations or Reverted
- timeout → Unknown
- replacement transactions (same nonce) linked

## Out of scope

Reorgs (CHR-004).

## Technical notes

Never set a Failed status on timeout.

## Dependencies

- CHR-001: Build the RPC client with failover
- EXE-001: Create operations (outbox), transactions and gas ledger schema

## Acceptance criteria

- [ ] A transaction is Confirmed only after the configured depth
- [ ] A timeout sets Unknown
- [ ] A replacement with the same nonce is linked to the same operation

## Testing requirements

- Integration on Anvil

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
