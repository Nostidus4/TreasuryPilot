# [DOMAIN] Author Copilot question cases (20)

| Field | Value |
|---|---|
| **ID** | DOM-007 |
| **Epic** | M20 · Domain & Evidence (non-code) |
| **Module** | `domain-evidence` ([spec](../../../docs/modules/domain-evidence/README.md)) |
| **Phase / Priority** | M1 / P1 |
| **Size** | S (≤ 0.5 day) |
| **Area** | non-code |
| **Status** | Ready for Review |
| **Traces to** | AGT-016 |
| **Blocks** | AGT-016 |
| **Submission cut** | After submission |

## Context

This ticket belongs to the epic **Domain & Evidence (non-code)**. It supports:

- F-092: AI evaluation harness (B1 vs B2)

Problem behind this work (from `docs/FEATURES.md`):

- **F-092** solves: Answers "why AI?" with data, honestly.

## Objective

Questions with known answers.

## Scope

- 20 questions with the scenario state and expected numbers in evals/copilot

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- DOM-005: Author planner scenarios with ground truth (≥30)

## Acceptance criteria

- [ ] 20 cases with expected numeric answers

## Testing requirements

- Not applicable (non-code). Review by a second person is required.

## Definition of Done

- [ ] Deliverable committed to the repository at the stated path
- [ ] Reviewed by one other team member
- [ ] Linked from the relevant document or issue
