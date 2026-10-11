# [AGENT] Build the Copilot backend

| Field | Value |
|---|---|
| **ID** | AGT-012 |
| **Epic** | M09 · AI Agent |
| **Module** | `agent` ([spec](../../../docs/modules/agent/README.md)) |
| **Phase / Priority** | M1 / P1 |
| **Size** | L (1.5–2 days; split if it grows) |
| **Area** | ai |
| **Status** | Ready for Assignment |
| **Traces to** | FR-801–802 |
| **Blocks** | AGT-016, WEB-016 |
| **Submission cut** | After submission |

## Context

This ticket belongs to the epic **AI Agent**. It supports:

- F-090: Treasury Copilot (what-if)

Problem behind this work (from `docs/FEATURES.md`):

- **F-090** solves: Fast, explainable decision support. Interaction quality.

## Objective

Answer treasury what-if questions with cited numbers and no side effects.

## Scope

- Thread and message tables and endpoints
- tool loop (max 6 calls) with simulate_schedule
- answer schema {answer, citations[]}
- numeric post-check against tool outputs
- refusal for execution requests
- SSE streaming

## Out of scope

UI (WEB-016).

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- AGT-007: Implement the read-only tool layer

## Acceptance criteria

- [ ] Asked to pay something, it refuses and points to the approval flow
- [ ] Every number in an answer appears in a cited tool result
- [ ] The audit log shows no writes from Copilot

## Testing requirements

- Integration with recorded responses

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
