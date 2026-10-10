# [CHAIN] Implement block-consistent snapshots

| Field | Value |
|---|---|
| **ID** | CHR-002 |
| **Epic** | M06 · Chain Reader & Tx Tracking |
| **Module** | `chain-reader` ([spec](../../../docs/modules/chain-reader/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | M (~1 day) |
| **Area** | backend |
| **Status** | Ready for Review |
| **Traces to** | BR-051, FR-401–402 |
| **Blocks** | EXE-004, AGT-007, AUD-004, WEB-010 |

## Context

This ticket belongs to the epic **Chain Reader & Tx Tracking**. It supports:

- F-050: Chain state reader & fresh snapshots

Problem behind this work (from `docs/FEATURES.md`):

- **F-050** solves: Plans must use fresh, provable state, never an earlier snapshot after the state has changed.

## Objective

One consistent view of balances, counters, payees and mandate at a block.

## Scope

- Batched reads at a single block (multicall or block-pinned calls)
- snapshot record with block number, hash, observed time, coverage and missing fields
- freshness check helper

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- CHR-001: Build the RPC client with failover
- TRS-004: Implement treasury creation with Safe verification

## Acceptance criteria

- [ ] All values in a snapshot come from the same block
- [ ] A partial read yields coverage PARTIAL with the missing fields listed

## Testing requirements

- Integration on Anvil

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
