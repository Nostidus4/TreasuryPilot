# [INVOICES] Implement deterministic anomaly checks

| Field | Value |
|---|---|
| **ID** | INV-007 |
| **Epic** | M05 · Invoices & Payment Requests |
| **Module** | `invoices` ([spec](../../../docs/modules/invoices/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | M (~1 day) |
| **Area** | backend |
| **Status** | Ready for Review |
| **Traces to** | FR-312, BR-072 |
| **Blocks** | INV-009 |
| **Submission cut** | A |

## Context

This ticket belongs to the epic **Invoices & Payment Requests**. It supports:

- F-036: Anomaly & fraud-signal detection

Problem behind this work (from `docs/FEATURES.md`):

- **F-036** solves: BEC fraud, duplicate payment, prompt injection (P3).

## Objective

Flag fraud signals without relying on the LLM.

## Scope

- Flags: address differs from registry or vendor history (checksum compare), amount outlier (median ± 3·MAD, needs ≥ 5 history points), currency or chain mismatch, due-date anomaly, duplicate
- severity, evidence and reason code per flag
- 'no baseline' state for new vendors

## Out of scope

Instruction-text detection (AGT-006).

## Technical notes

Flags never change fields or state.

## Dependencies

- INV-006: Compute fingerprints at intake and block duplicates

## Acceptance criteria

- [ ] A changed address raises a high-severity flag
- [ ] A new vendor shows NO_BASELINE rather than clean
- [ ] Outlier detection matches a hand-computed example

## Testing requirements

- Unit

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
