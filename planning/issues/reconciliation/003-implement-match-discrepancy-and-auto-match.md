# [RECON] Implement match, discrepancy and auto-match

| Field | Value |
|---|---|
| **ID** | REC-003 |
| **Epic** | M11 · Verification & Reconciliation |
| **Module** | `reconciliation` ([spec](../../../docs/modules/reconciliation/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | S (≤ 0.5 day) |
| **Area** | backend |
| **Status** | Ready for Review |
| **Traces to** | FR-606 |
| **Blocks** | REC-004, REC-005 |
| **Submission cut** | B |

## Context

This ticket belongs to the epic **Verification & Reconciliation**. It supports:

- F-072: Reconciliation (Paid vs Matched)

Problem behind this work (from `docs/FEATURES.md`):

- **F-072** solves: P5.

## Objective

Finance can close out a payment with evidence.

## Scope

- GET list with filters
- POST match and discrepancy
- auto-match when the org setting is on and all evidence matches

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- REC-002: Build reconciliation records with classification

## Acceptance criteria

- [ ] Match is refused when evidence is incomplete
- [ ] Auto-match is off by default

## Testing requirements

- Integration

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
