# [AGENT] Build the planner benchmark (B1 vs B2)

| Field | Value |
|---|---|
| **ID** | AGT-014 |
| **Epic** | M09 · AI Agent |
| **Module** | `agent` ([spec](../../../docs/modules/agent/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | M (~1 day) |
| **Area** | ai |
| **Status** | Ready for Assignment |
| **Traces to** | FR-805, BR-052, ADR-019 |
| **Blocks** | — |
| **Submission cut** | A |

## Context

This ticket belongs to the epic **AI Agent**. It supports:

- F-092: AI evaluation harness (B1 vs B2)

Problem behind this work (from `docs/FEATURES.md`):

- **F-092** solves: Answers "why AI?" with data, honestly.

## Objective

Show with data what the AI adds over the rule baseline.

## Scope

- Scenario loader for evals/scenarios (dev and held-out)
- run B1 and B2 with identical state and checks
- metrics: value saved, on-time %, exceptions, tx count, violations, latency, cost
- N repetitions for B2
- markdown and CSV report
- baseline B0 (manual/EDF, cash idle) before B1 and B2; metrics add reserve breaches and net benefit incl. supply interest

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Ground truth never enters prompts.

## Dependencies

- AGT-009: Score AI proposals and select the plan
- ENG-006: Implement the baseline scheduler B1 (earliest deadline first)
- DOM-005: Author planner scenarios with ground truth (≥30)

## Acceptance criteria

- [ ] `make bench` runs both arms on all scenarios
- [ ] Violations are 0 in both arms or the run fails
- [ ] The report includes scenarios where B2 is worse
- [ ] The report has three arms B0, B1, B2

## Testing requirements

- AI eval

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
