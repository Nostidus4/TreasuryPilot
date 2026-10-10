# [AGENT] Implement the plan proposer

| Field | Value |
|---|---|
| **ID** | AGT-008 |
| **Epic** | M09 · AI Agent |
| **Module** | `agent` ([spec](../../../docs/modules/agent/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | M (~1 day) |
| **Area** | ai |
| **Status** | Ready for Review |
| **Traces to** | FR-406, FR-408 |
| **Blocks** | AGT-009 |

## Context

This ticket belongs to the epic **AI Agent**. It supports:

- F-053: AI plan proposal & explanation

Problem behind this work (from `docs/FEATURES.md`):

- **F-053** solves: Handles judgment cases (vendor criticality notes, ambiguous priorities, multi-constraint trade-offs) and explains them.

## Objective

Ask the model for an ordering and rationale in a strict schema.

## Scope

- PlanProposal schema {requestOrder, deferrals, exceptionRequests, rationale[], evidenceIds[]}
- prompt v1
- tool loop with budget
- reference integrity check (ids exist and belong to the org)

## Out of scope

Selection (AGT-009).

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- AGT-007: Implement the read-only tool layer

## Acceptance criteria

- [ ] A proposal referencing an unknown request is rejected
- [ ] The rationale cites evidence ids that resolve
- [ ] No amounts are accepted from the model

## Testing requirements

- Unit with recorded responses

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
