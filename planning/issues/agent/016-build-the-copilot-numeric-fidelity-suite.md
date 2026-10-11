# [AGENT] Build the Copilot numeric-fidelity suite

| Field | Value |
|---|---|
| **ID** | AGT-016 |
| **Epic** | M09 · AI Agent |
| **Module** | `agent` ([spec](../../../docs/modules/agent/README.md)) |
| **Phase / Priority** | M1 / P1 |
| **Size** | S (≤ 0.5 day) |
| **Area** | ai |
| **Status** | Ready for Assignment |
| **Traces to** | FR-801 |
| **Blocks** | — |
| **Submission cut** | After submission |

## Context

This ticket belongs to the epic **AI Agent**. It supports:

- F-092: AI evaluation harness (B1 vs B2)

Problem behind this work (from `docs/FEATURES.md`):

- **F-092** solves: Answers "why AI?" with data, honestly.

## Objective

Check that Copilot answers match the engine.

## Scope

- Runner over evals/copilot
- compare numbers in answers with engine outputs

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- AGT-012: Build the Copilot backend
- DOM-007: Author Copilot question cases (20)

## Acceptance criteria

- [ ] All 20 cases have matching numbers or are listed as failures in the report

## Testing requirements

- AI eval

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
