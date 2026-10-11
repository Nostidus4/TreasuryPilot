# [RECON] Add the NetSuite connector

| Field | Value |
|---|---|
| **ID** | REC-L03 |
| **Epic** | M11 · Verification & Reconciliation |
| **Module** | `reconciliation` ([spec](../../../docs/modules/reconciliation/README.md)) |
| **Phase / Priority** | Later / - |
| **Size** | M (~1 day) |
| **Area** | backend |
| **Status** | Accepted |
| **Traces to** | FR-609 |
| **Blocks** | — |
| **Submission cut** | After submission |

> **Phase: Later.** This ticket is intentionally coarser than M1 tickets. It must be re-estimated and split before it is scheduled.

## Context

This ticket belongs to the epic **Verification & Reconciliation**. It supports:

- F-075: ERP / accounting integrations

Problem behind this work (from `docs/FEATURES.md`):

- **F-075** solves: Removes double entry.

## Objective

NetSuite sync.

## Scope

- Adapter on the connector interface

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- REC-L01: Build the ERP integration framework with Xero

## Acceptance criteria

- [ ] Same contract tests as Xero pass

## Testing requirements

- Integration

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
