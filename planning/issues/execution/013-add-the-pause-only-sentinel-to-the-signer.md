# [EXECUTION] Add the pause-only sentinel to the signer

| Field | Value |
|---|---|
| **ID** | EXE-013 |
| **Epic** | M10 · Orchestration & Execution |
| **Module** | `execution` ([spec](../../../docs/modules/execution/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | S (≤ 0.5 day) |
| **Area** | backend |
| **Status** | Ready for Assignment |
| **Traces to** | BR-068, ADR-017, AP-3 |
| **Blocks** | MDT-007, RCV-006, MDT-010 |
| **Submission cut** | A |

## Context

This ticket belongs to the epic **Orchestration & Execution**. It supports:

- F-026: Pause, resume & revoke
- F-027: Circuit breaker (auto-pause)

Problem behind this work (from `docs/FEATURES.md`):

- **F-026** solves: Emergency stop.
- **F-027** solves: Limits damage from bugs or compromise between human checks.

## Objective

The system can pause the module on-chain without any power to spend or govern.

## Scope

- Separate encrypted sentinel keystore
- GET /sentinel/address
- POST /sentinel/pause {treasuryId} building only GuardianSafe.execTransaction(module, 0, pause()) for the configured treasury and broadcasting it
- refuses any other target or calldata
- idempotent when already paused
- gas balance in health

## Out of scope

Deciding when to pause (MDT-007, RCV-006).

## Technical notes

Sentinel key ≠ executor key ≠ policy key.

## Dependencies

- EXE-005: Build the signer service
- EXE-006: Load the executor key from an encrypted keystore

## Acceptance criteria

- [ ] A pause request results in Paused within 2 blocks on Anvil
- [ ] Any other calldata or target is refused
- [ ] The key never appears in logs

## Testing requirements

- Unit + integration on Anvil

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
