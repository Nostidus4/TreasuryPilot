# [AGENT] Log every AI call and fail closed

| Field | Value |
|---|---|
| **ID** | AGT-002 |
| **Epic** | M09 · AI Agent |
| **Module** | `agent` ([spec](../../../docs/modules/agent/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | S (≤ 0.5 day) |
| **Area** | ai |
| **Status** | Ready for Assignment |
| **Traces to** | FR-806–807, BR-097 |
| **Blocks** | AGT-004 |
| **Submission cut** | A |

## Context

This ticket belongs to the epic **AI Agent**. It supports:

- F-093: AI decision log

Problem behind this work (from `docs/FEATURES.md`):

- **F-093** solves: Traceability. "Why did the agent do this?"

## Objective

No AI decision exists without a record.

## Scope

- ai_calls table migration
- wrapper recording purpose, model, prompt version, input refs, tool calls, output, validation result, latency, tokens, cost
- if the write fails the call result is discarded

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Store references, not secrets. Redact document text beyond a preview.

## Dependencies

- AGT-001: Build the LLM adapter with routing and timeouts

## Acceptance criteria

- [ ] Every adapter call produces one ai_calls row
- [ ] A simulated DB failure makes the calling task fail

## Testing requirements

- Integration

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
