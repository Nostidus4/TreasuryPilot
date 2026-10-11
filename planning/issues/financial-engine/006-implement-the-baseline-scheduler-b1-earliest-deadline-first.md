# [ENGINE] Implement the baseline scheduler B1 (earliest deadline first)

| Field | Value |
|---|---|
| **ID** | ENG-006 |
| **Epic** | M07 · Financial Engine (py-core) |
| **Module** | `financial-engine` ([spec](../../../docs/modules/financial-engine/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | S (≤ 0.5 day) |
| **Area** | backend |
| **Status** | Ready for Assignment |
| **Traces to** | BR-052 |
| **Blocks** | ENG-007, AGT-014, OBS-005, ENG-012 |
| **Submission cut** | A |

## Context

This ticket belongs to the epic **Financial Engine (py-core)**. It supports:

- F-052: Terms-aware deterministic scheduler
- F-092: AI evaluation harness (B1 vs B2)

Problem behind this work (from `docs/FEATURES.md`):

- **F-052** solves: P4: rules like "earliest due first" leave money on the table.
- **F-092** solves: Answers "why AI?" with data, honestly.

## Objective

The rule-based reference schedule every AI plan is compared against.

## Scope

- schedule_edf(requests, snapshot, policy) over the rolling horizon (≤ 30 UTC days, M07-D3)
- order by (net_due_day, approved_seq)
- per-day pay and refill caps, source drawdown, payee cooling, NEEDS_EXCEPTION for over-cap requests
- infeasible items with the first blocking reason

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- ENG-003: Implement the refill decision table
- ENG-005: Model payment terms and their value function

## Acceptance criteria

- [ ] Requests are ordered by due day then approval order
- [ ] Items blocked by cooling payee, daily cap, source capacity, refill bound or per-request cap are reported with the matching reason
- [ ] Output is a Schedule with solver = EDF

## Testing requirements

- Unit: ordering and infeasibility tests

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
