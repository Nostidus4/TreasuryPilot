# [AUDIT] Anchor the audit hash root on-chain daily

| Field | Value |
|---|---|
| **ID** | AUD-L01 |
| **Epic** | M15 · Audit & Evidence |
| **Module** | `audit` ([spec](../../../docs/modules/audit/README.md)) |
| **Phase / Priority** | Later / - |
| **Size** | L (1.5–2 days; split if it grows) |
| **Area** | backend |
| **Status** | Accepted |
| **Traces to** | — |
| **Blocks** | — |
| **Submission cut** | After submission |

> **Phase: Later.** This ticket is intentionally coarser than M1 tickets. It must be re-estimated and split before it is scheduled.

## Context

This ticket belongs to the epic **Audit & Evidence**. It supports:

- F-120: Hash-chained audit log & on-chain events

Problem behind this work (from `docs/FEATURES.md`):

- **F-120** solves: Tamper-evident traceability.

## Objective

External tamper evidence.

## Scope

- Contract and deployment: store one authorized immutable root per organization and UTC day
- Publisher and configuration: capture org heads in one repeatable-read snapshot and publish the exact captured hashes with a dedicated publisher
- Integration acceptance: run PostgreSQL plus Anvil and prove the on-chain root equals the captured audit head

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Re-estimate: L total (1.5–2 days), split into three sequential, reviewable S slices: contract/deployment, publisher/configuration, and live integration acceptance. Do not mark complete or deploy before a reviewed contract address, configured publisher identity, and passing PostgreSQL/Anvil proof are available.

## Dependencies

- AUD-002: Add audit read and chain verification

## Acceptance criteria

- [ ] The anchored hash matches audit_heads.last_hash from the recorded database snapshot
- [ ] A PostgreSQL/Anvil integration test proves the captured head is stored on-chain
- [ ] The deployment chain, contract address, and dedicated publisher identity are verified

## Testing requirements

- Contract unit tests
- Worker unit tests
- PostgreSQL + Anvil integration

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
