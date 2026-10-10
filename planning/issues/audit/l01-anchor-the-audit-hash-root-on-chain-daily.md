# [AUDIT] Anchor the audit hash root on-chain daily

| Field | Value |
|---|---|
| **ID** | AUD-L01 |
| **Epic** | M15 · Audit & Evidence |
| **Module** | `audit` ([spec](../../../docs/modules/audit/README.md)) |
| **Phase / Priority** | Later / - |
| **Size** | S (≤ 0.5 day) |
| **Area** | backend |
| **Status** | Needs Discussion |
| **Traces to** | — |
| **Blocks** | — |

> **Phase: Later.** This ticket is intentionally coarser than M1 tickets. It must be re-estimated and split before it is scheduled.

## Context

This ticket belongs to the epic **Audit & Evidence**. It supports:

- F-120: Hash-chained audit log & on-chain events

Problem behind this work (from `docs/FEATURES.md`):

- **F-120** solves: Tamper-evident traceability.

## Objective

External tamper evidence.

## Scope

- Daily job publishing the org chain head hash

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- AUD-002: Add audit read and chain verification

## Acceptance criteria

- [ ] The anchored hash matches the log head at that time

## Testing requirements

- Integration

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
