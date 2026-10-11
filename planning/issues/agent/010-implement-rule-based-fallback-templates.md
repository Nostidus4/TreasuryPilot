# [AGENT] Implement rule-based fallback templates

| Field | Value |
|---|---|
| **ID** | AGT-010 |
| **Epic** | M09 · AI Agent |
| **Module** | `agent` ([spec](../../../docs/modules/agent/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | S (≤ 0.5 day) |
| **Area** | ai |
| **Status** | Ready for Review |
| **Traces to** | BR-055, FR-409 |
| **Blocks** | — |
| **Submission cut** | A |

## Context

This ticket belongs to the epic **AI Agent**. It supports:

- F-054: Rule-based fallback planner

Problem behind this work (from `docs/FEATURES.md`):

- **F-054** solves: Availability without granting extra authority.

## Objective

Keep paying when the model is unavailable, without widening authority.

## Scope

- Templates: pay direct, refill then pay, swap then pay
- eligibility check for BR-055 conditions
- planner_source RULE_BASED

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- ENG-007: Implement the terms-aware scheduler
- POL-003: Validate limits, buffers, deadlines, coverage and unknown operations

## Acceptance criteria

- [ ] AD-02: AI timeout with complete data completes via a template
- [ ] AD-03: with an Unknown operation no fallback runs

## Testing requirements

- Unit + integration

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
