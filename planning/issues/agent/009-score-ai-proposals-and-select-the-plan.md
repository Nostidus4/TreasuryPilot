# [AGENT] Score AI proposals and select the plan

| Field | Value |
|---|---|
| **ID** | AGT-009 |
| **Epic** | M09 · AI Agent |
| **Module** | `agent` ([spec](../../../docs/modules/agent/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | S (≤ 0.5 day) |
| **Area** | ai |
| **Status** | Ready for Assignment |
| **Traces to** | FR-407, BR-056 |
| **Blocks** | EXE-004, AGT-014 |
| **Submission cut** | A |

## Context

This ticket belongs to the epic **AI Agent**. It supports:

- F-053: AI plan proposal & explanation

Problem behind this work (from `docs/FEATURES.md`):

- **F-053** solves: Handles judgment cases (vendor criticality notes, ambiguous priorities, multi-constraint trade-offs) and explains them.

## Objective

The AI's plan is used only if it is valid and at least as good.

## Scope

- Build a concrete plan from the proposal with engine amounts
- score against the deterministic plan
- select the better feasible one
- store planner_source and chosen_reason
- invalid proposals → review item AI_PLAN_REJECTED

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- AGT-008: Implement the plan proposer
- ENG-008: Expose plan scoring and binding-constraint reporting

## Acceptance criteria

- [ ] A worse AI plan is not chosen and the comparison is logged
- [ ] An out-of-mandate proposal creates a review item and is never executed

## Testing requirements

- Unit

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
