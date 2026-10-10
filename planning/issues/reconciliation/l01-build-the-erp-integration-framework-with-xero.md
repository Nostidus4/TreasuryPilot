# [RECON] Build the ERP integration framework with Xero

| Field | Value |
|---|---|
| **ID** | REC-L01 |
| **Epic** | M11 · Verification & Reconciliation |
| **Module** | `reconciliation` ([spec](../../../docs/modules/reconciliation/README.md)) |
| **Phase / Priority** | Later / - |
| **Size** | L (1.5–2 days; split if it grows) |
| **Area** | backend |
| **Status** | Needs Discussion |
| **Traces to** | FR-609 |
| **Blocks** | REC-L02, REC-L03 |

> **Phase: Later.** This ticket is intentionally coarser than M1 tickets. It must be re-estimated and split before it is scheduled.

## Context

This ticket belongs to the epic **Verification & Reconciliation**. It supports:

- F-075: ERP / accounting integrations

Problem behind this work (from `docs/FEATURES.md`):

- **F-075** solves: Removes double entry.

## Objective

Sync bills and payments with an accounting system.

## Scope

- Connector interface
- OAuth
- bills in as drafts
- payments out with tx reference
- Xero adapter

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- REC-004: Export reconciliation CSV and journal lines

## Acceptance criteria

- [ ] A synced bill is never approved by the sync

## Testing requirements

- Integration with sandbox

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
