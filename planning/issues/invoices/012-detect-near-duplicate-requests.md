# [INVOICES] Detect near-duplicate requests

| Field | Value |
|---|---|
| **ID** | INV-012 |
| **Epic** | M05 · Invoices & Payment Requests |
| **Module** | `invoices` ([spec](../../../docs/modules/invoices/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | S (≤ 0.5 day) |
| **Area** | backend |
| **Status** | Ready for Assignment |
| **Traces to** | BR-076, FR-323, M05-D5 |
| **Blocks** | — |
| **Submission cut** | A |

## Context

This ticket belongs to the epic **Invoices & Payment Requests**. It supports:

- F-036: Anomaly & fraud-signal detection
- F-037: Duplicate-invoice fingerprint

Problem behind this work (from `docs/FEATURES.md`):

- **F-036** solves: BEC fraud, duplicate payment, prompt injection (P3).
- **F-037** solves: The same invoice entered under two request IDs (a gap the source admits in UC-04).

## Objective

Catch invoices re-submitted with a slightly altered number, without bothering recurring payments.

## Scope

- Candidate query: same vendor, same amount, issue dates within 45 days, status not Rejected/Cancelled, different fingerprint
- Damerau-Levenshtein distance on normalized invoice numbers
- POSSIBLE_DUPLICATE HIGH when d ≤ 2, LOW otherwise, evidence with the other request id
- index (vendor_id, amount, issue_date)

## Out of scope

Exact duplicates (INV-006).

## Technical notes

Pure-Python distance function (no new dependency).

## Dependencies

- INV-006: Compute fingerprints at intake and block duplicates

## Acceptance criteria

- [ ] INV-2026-0412 vs INV-2026-0421 raises HIGH
- [ ] RENT-SEP vs RENT-OCT raises LOW
- [ ] Different amounts raise nothing
- [ ] Runs in < 50 ms with 10,000 requests per vendor

## Testing requirements

- Unit: examples in docs/modules/invoices §8.3
- performance test

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
