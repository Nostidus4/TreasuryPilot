# [DOMAIN] Author the labelled invoice dataset (30)

| Field | Value |
|---|---|
| **ID** | DOM-004 |
| **Epic** | M20 · Domain & Evidence (non-code) |
| **Module** | `domain-evidence` ([spec](../../../docs/modules/domain-evidence/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | M (~1 day) |
| **Area** | non-code |
| **Status** | Ready for Review |
| **Traces to** | AGT-013 |
| **Blocks** | AGT-013 |

## Context

This ticket belongs to the epic **Domain & Evidence (non-code)**. It supports:

- F-092: AI evaluation harness (B1 vs B2)

Problem behind this work (from `docs/FEATURES.md`):

- **F-092** solves: Answers "why AI?" with data, honestly.

## Objective

Realistic invoices to measure extraction.

## Scope

- 30 invoices as PDF with JSON labels (fields and terms) in evals/invoices
- mix: clean, with discount terms, late fees, messy layouts, two languages
- no real company data

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- None

## Acceptance criteria

- [ ] 30 PDFs each with a label file that validates against the schema
- [ ] At least 8 have discount or late-fee terms

## Testing requirements

- Not applicable (non-code). Review by a second person is required.

## Definition of Done

- [ ] Deliverable committed to the repository at the stated path
- [ ] Reviewed by one other team member
- [ ] Linked from the relevant document or issue
