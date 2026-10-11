# [INVOICES] Implement deterministic anomaly checks

| Field | Value |
|---|---|
| **ID** | INV-007 |
| **Epic** | M05 · Invoices & Payment Requests |
| **Module** | `invoices` ([spec](../../../docs/modules/invoices/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | M (~1 day) |
| **Area** | backend |
| **Status** | Ready for Assignment |
| **Traces to** | FR-312, BR-072, BR-066, OQ-10 |
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

- Flag rules per docs/modules/invoices §8.4–8.5: ADDRESS_CHANGED, ADDRESS_NOT_REGISTERED, FIRST_PAYMENT_TO_PAYEE, NO_BASELINE, AMOUNT_OUTLIER (median ± 3·max(1.4826·MAD, 2 % median), n ≥ 5, integer median), CURRENCY_MISMATCH, CHAIN_MISMATCH, DUE_DATE_PAST, DUE_DATE_FAR, DUE_BEFORE_ISSUE, AI_UNAVAILABLE
- flags stored per revision, old ones Superseded
- severity, evidence and code per flag

## Out of scope

Instruction-text detection (AGT-006).

## Technical notes

Flags never change fields or state.

## Dependencies

- INV-006: Compute fingerprints at intake and block duplicates

## Acceptance criteria

- [ ] A changed address raises ADDRESS_CHANGED HIGH
- [ ] A new vendor shows NO_BASELINE rather than clean
- [ ] The §8.4 example flags 1,100 and not 1,050
- [ ] Identical recurring amounts with one cent difference do not flag
- [ ] Flags never change fields or state

## Testing requirements

- Unit: one test per rule
- property: flags are a pure function of the revision and history

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
