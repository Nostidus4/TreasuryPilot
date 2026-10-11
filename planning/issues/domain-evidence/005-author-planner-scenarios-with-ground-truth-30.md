# [DOMAIN] Author planner scenarios with ground truth (≥30)

| Field | Value |
|---|---|
| **ID** | DOM-005 |
| **Epic** | M20 · Domain & Evidence (non-code) |
| **Module** | `domain-evidence` ([spec](../../../docs/modules/domain-evidence/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | L (1.5–2 days; split if it grows) |
| **Area** | non-code |
| **Status** | Ready for Review |
| **Traces to** | AGT-014, BR-052 |
| **Blocks** | AGT-014, DOM-007 |
| **Submission cut** | A |

## Context

This ticket belongs to the epic **Domain & Evidence (non-code)**. It supports:

- F-092: AI evaluation harness (B1 vs B2)

Problem behind this work (from `docs/FEATURES.md`):

- **F-092** solves: Answers "why AI?" with data, honestly.

## Objective

Scenarios that show when smart scheduling matters.

## Scope

- YAML scenarios in evals/scenarios: requests, terms, balances, limits, dates
- expected optimum value computed by hand or script
- dev and held-out split by scenario family

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Work with a developer on the file format.

## Dependencies

- None

## Acceptance criteria

- [ ] At least 30 scenarios, at least 10 held out
- [ ] Each has a documented expected result

## Testing requirements

- Not applicable (non-code). Review by a second person is required.

## Definition of Done

- [ ] Deliverable committed to the repository at the stated path
- [ ] Reviewed by one other team member
- [ ] Linked from the relevant document or issue
