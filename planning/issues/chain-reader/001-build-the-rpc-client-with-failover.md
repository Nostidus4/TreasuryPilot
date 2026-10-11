# [CHAIN] Build the RPC client with failover

| Field | Value |
|---|---|
| **ID** | CHR-001 |
| **Epic** | M06 · Chain Reader & Tx Tracking |
| **Module** | `chain-reader` ([spec](../../../docs/modules/chain-reader/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | M (~1 day) |
| **Area** | backend |
| **Status** | Ready for Assignment |
| **Traces to** | NFR-REL-04 |
| **Blocks** | TRS-003, CHR-002, CHR-003, CHR-005, EXE-012 |
| **Submission cut** | A |

## Context

This ticket belongs to the epic **Chain Reader & Tx Tracking**. It supports:

- F-050: Chain state reader & fresh snapshots

Problem behind this work (from `docs/FEATURES.md`):

- **F-050** solves: Plans must use fresh, provable state, never an earlier snapshot after the state has changed.

## Objective

Chain access that survives one provider failing.

## Scope

- web3.py wrapper with ordered providers, timeouts, retry and failover
- provider health tracking
- typed errors (RpcUnavailable)

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- TRS-002: Load and validate platform chain configuration

## Acceptance criteria

- [ ] With the first provider down, calls succeed through the second
- [ ] With all down, RpcUnavailable is raised and nothing returns a default value

## Testing requirements

- Unit with mocked providers

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
