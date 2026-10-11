# [OBSERVABILITY] Compute the savings report

| Field | Value |
|---|---|
| **ID** | OBS-005 |
| **Epic** | M17 · Observability & Analytics |
| **Module** | `observability` ([spec](../../../docs/modules/observability/README.md)) |
| **Phase / Priority** | M1 / P1 |
| **Size** | M (~1 day) |
| **Area** | infrastructure |
| **Status** | Ready for Review |
| **Traces to** | FR-922 |
| **Blocks** | WEB-018 |
| **Submission cut** | After submission |

## Context

This ticket belongs to the epic **Observability & Analytics**. It supports:

- F-141: Savings report

Problem behind this work (from `docs/FEATURES.md`):

- **F-141** solves: Shows the AI's value in money.

## Objective

Show the value created versus the baseline.

## Scope

- Counterfactual B1 simulation for executed batches using stored snapshots
- discounts captured and late fees avoided
- methodology text
- GET /metrics/savings

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- OBS-004: Compute operational metrics
- ENG-006: Implement the baseline scheduler B1 (earliest deadline first)

## Acceptance criteria

- [ ] Savings for a seeded batch equal a hand-computed value
- [ ] Negative savings are reported as negative

## Testing requirements

- Integration

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
