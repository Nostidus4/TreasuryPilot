# [RECON] Export reconciliation CSV and journal lines

| Field | Value |
|---|---|
| **ID** | REC-004 |
| **Epic** | M11 · Verification & Reconciliation |
| **Module** | `reconciliation` ([spec](../../../docs/modules/reconciliation/README.md)) |
| **Phase / Priority** | M1 / P1 |
| **Size** | M (~1 day) |
| **Area** | backend |
| **Status** | Ready for Assignment |
| **Traces to** | FR-607 |
| **Blocks** | REC-L01, WEB-014 |
| **Submission cut** | B |

## Context

This ticket belongs to the epic **Verification & Reconciliation**. It supports:

- F-073: Reconciliation export (CSV / journal)

Problem behind this work (from `docs/FEATURES.md`):

- **F-073** solves: Accounting handoff.

## Objective

Hand accounting a file they can use.

## Scope

- CSV export for a period
- journal format with a generic account mapping and per-org mapping table
- formula neutralization
- totals check

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- REC-003: Implement match, discrepancy and auto-match

## Acceptance criteria

- [ ] Export totals equal on-chain totals for the period
- [ ] Unmatched items are included with their status

## Testing requirements

- Integration

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
