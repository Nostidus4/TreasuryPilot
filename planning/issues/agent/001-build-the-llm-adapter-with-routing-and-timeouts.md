# [AGENT] Build the LLM adapter with routing and timeouts

| Field | Value |
|---|---|
| **ID** | AGT-001 |
| **Epic** | M09 · AI Agent |
| **Module** | `agent` ([spec](../../../docs/modules/agent/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | M (~1 day) |
| **Area** | ai |
| **Status** | Ready for Review |
| **Traces to** | ADR-005, FR-808 |
| **Blocks** | AGT-002, AGT-003, AGT-011, AGT-017 |

## Context

This ticket belongs to the epic **AI Agent**. It supports:

- F-094: Model adapter & routing

Problem behind this work (from `docs/FEATURES.md`):

- **F-094** solves: Vendor lock-in, cost, availability.

## Objective

One place where all LLM calls go, with per-task model choice.

## Scope

- Adapter interface (complete with schema, tool loop)
- Anthropic SDK implementation with structured outputs and tool use
- config.yaml: model per task, timeouts, max tool calls, token budgets
- typed errors (AiTimeout, AiUnavailable, AiSchemaError)

## Out of scope

Secondary provider (AGT-017).

## Technical notes

Runs only in worker-ai.

## Dependencies

- EXE-002: Set up Celery with core and ai queues

## Acceptance criteria

- [ ] Switching the model for a task requires only a config change
- [ ] A timeout raises AiTimeout within the configured limit
- [ ] Outputs that fail the schema raise AiSchemaError

## Testing requirements

- Unit with a fake provider

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
