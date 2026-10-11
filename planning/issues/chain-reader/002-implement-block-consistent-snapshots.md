# [CHAIN] Implement block-consistent snapshots

| Field | Value |
|---|---|
| **ID** | CHR-002 |
| **Epic** | M06 · Chain Reader & Tx Tracking |
| **Module** | `chain-reader` ([spec](../../../docs/modules/chain-reader/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | M (~1 day) |
| **Area** | backend |
| **Status** | Ready for Assignment |
| **Traces to** | BR-051, FR-401–402, ADR-019 |
| **Blocks** | EXE-004, AGT-007, AUD-004, WEB-010, POL-007 |
| **Submission cut** | A |

## Context

This ticket belongs to the epic **Chain Reader & Tx Tracking**. It supports:

- F-050: Chain state reader & fresh snapshots

Problem behind this work (from `docs/FEATURES.md`):

- **F-050** solves: Plans must use fresh, provable state, never an earlier snapshot after the state has changed.

## Objective

One consistent view of balances, counters, payees and mandate at a block.

## Scope

- Multicall3 aggregate3 pinned to one block with the read set of docs/modules/chain-reader §8.1
- snapshot record with purpose, block number, hash, timestamp, provider, coverage and missing fields
- freshness helper (≤ 30 s and ≤ 2 blocks)
- dashboard snapshot every 60 s with 7-day pruning
- Aave reads at the snapshot block: aToken balance, pool available liquidity, getReserveData rates, getUserAccountData

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- CHR-001: Build the RPC client with failover
- TRS-004: Implement treasury creation with Safe verification

## Acceptance criteria

- [ ] All values in a snapshot come from the same block
- [ ] A failed sub-call is listed in missing and the snapshot is stored
- [ ] is_fresh rejects a snapshot 3 blocks behind head

## Testing requirements

- Integration on Anvil

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
