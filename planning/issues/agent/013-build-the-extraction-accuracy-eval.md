# [AGENT] Build the extraction accuracy eval

| Field | Value |
|---|---|
| **ID** | AGT-013 |
| **Epic** | M09 · AI Agent |
| **Module** | `agent` ([spec](../../../docs/modules/agent/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | S (≤ 0.5 day) |
| **Area** | ai |
| **Status** | Ready for Review |
| **Traces to** | FR-805 |
| **Blocks** | — |
| **Submission cut** | B |

## Context

This ticket belongs to the epic **AI Agent**. It supports:

- F-092: AI evaluation harness (B1 vs B2)

Problem behind this work (from `docs/FEATURES.md`):

- **F-092** solves: Answers "why AI?" with data, honestly.

## Objective

Measure how well extraction works on the labelled invoices.

## Scope

- Runner over evals/invoices
- field-level exact match and terms F1
- report to docs/evidence/

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- AGT-005: Extract and validate payment terms
- DOM-004: Author the labelled invoice dataset (30)

## Acceptance criteria

- [ ] `make eval-extraction` produces a report with per-field accuracy
- [ ] Results are reproducible from recorded or live runs

## Testing requirements

- AI eval

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
