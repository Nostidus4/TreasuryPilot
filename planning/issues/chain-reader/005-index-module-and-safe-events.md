# [CHAIN] Index module and Safe events

| Field | Value |
|---|---|
| **ID** | CHR-005 |
| **Epic** | M06 · Chain Reader & Tx Tracking |
| **Module** | `chain-reader` ([spec](../../../docs/modules/chain-reader/README.md)) |
| **Phase / Priority** | M1 / P1 |
| **Size** | M (~1 day) |
| **Area** | backend |
| **Status** | Ready for Assignment |
| **Traces to** | FR-510, PH-6, M06-D6, M06-D9, ADR-019 |
| **Blocks** | MDT-005, CHR-006 |
| **Submission cut** | A |

## Context

This ticket belongs to the epic **Chain Reader & Tx Tracking**. It supports:

- F-050: Chain state reader & fresh snapshots
- F-120: Hash-chained audit log & on-chain events

Problem behind this work (from `docs/FEATURES.md`):

- **F-050** solves: Plans must use fresh, provable state, never an earlier snapshot after the state has changed.
- **F-120** solves: Tamper-evident traceability.

## Objective

Off-chain state follows on-chain events for mandate, payees, payments and pause.

## Scope

- Cursor-based eth_getLogs reader per stream (MODULE, SAFE_CONFIG, SAFE_EXEC) per docs/modules/chain-reader §8.3 with 64-block re-scan and ≤ 2,000-block chunks
- exact address filters
- observed_events and index_cursors
- subscriber registry used by M03/M05/M11 handlers
- Safe config events trigger coverage recompute
- index Supplied, Withdrawn (and BorrowExecuted, Repaid) events

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Idempotent by (chain, tx hash, log index).

## Dependencies

- CHR-001: Build the RPC client with failover
- SC-016: Write deployment scripts and the deployments manifest

## Acceptance criteria

- [ ] Re-reading the same range creates no duplicates
- [ ] PayeeAdded, Paused, ExceptionGranted, RequestCancelled and ExecutionSuccess events update application state
- [ ] Logs from an unrelated contract emitting the same topics are ignored
- [ ] A ChangedGuard event recomputes coverage

## Testing requirements

- Integration on Anvil

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
