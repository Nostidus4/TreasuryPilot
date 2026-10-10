# [AGENT] Implement the read-only tool layer

| Field | Value |
|---|---|
| **ID** | AGT-007 |
| **Epic** | M09 · AI Agent |
| **Module** | `agent` ([spec](../../../docs/modules/agent/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | M (~1 day) |
| **Area** | ai |
| **Status** | Ready for Review |
| **Traces to** | AI_AGENT_ARCHITECTURE §3 |
| **Blocks** | AGT-008, AGT-012 |

## Context

This ticket belongs to the epic **AI Agent**. It supports:

- F-053: AI plan proposal & explanation
- F-090: Treasury Copilot (what-if)

Problem behind this work (from `docs/FEATURES.md`):

- **F-053** solves: Handles judgment cases (vendor criticality notes, ambiguous priorities, multi-constraint trade-offs) and explains them.
- **F-090** solves: Fast, explainable decision support. Interaction quality.

## Objective

Give the model facts and simulations, and nothing else.

## Scope

- Tools: get_snapshot, list_requests, get_policy_summary, simulate_schedule, get_evidence, explain_decision
- typed inputs and outputs
- org scoping
- call and payload budgets
- registry that rejects unknown tools

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

No tool may write. Add a test that enumerates tools and asserts read-only DB sessions.

## Dependencies

- CHR-002: Implement block-consistent snapshots
- ENG-008: Expose plan scoring and binding-constraint reporting
- POL-003: Validate limits, buffers, deadlines, coverage and unknown operations

## Acceptance criteria

- [ ] A tool call for another org's treasury is refused
- [ ] Exceeding the tool-call budget ends the loop
- [ ] All tools run in read-only transactions

## Testing requirements

- Unit + integration

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
