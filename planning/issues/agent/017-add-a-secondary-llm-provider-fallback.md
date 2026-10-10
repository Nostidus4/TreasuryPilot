# [AGENT] Add a secondary LLM provider fallback

| Field | Value |
|---|---|
| **ID** | AGT-017 |
| **Epic** | M09 · AI Agent |
| **Module** | `agent` ([spec](../../../docs/modules/agent/README.md)) |
| **Phase / Priority** | M1 / P1 |
| **Size** | M (~1 day) |
| **Area** | ai |
| **Status** | Ready for Review |
| **Traces to** | FR-808, NFR-REL-05 |
| **Blocks** | — |

## Context

This ticket belongs to the epic **AI Agent**. It supports:

- F-094: Model adapter & routing

Problem behind this work (from `docs/FEATURES.md`):

- **F-094** solves: Vendor lock-in, cost, availability.

## Objective

Survive an outage of the primary provider.

## Scope

- Second adapter implementation behind the same interface
- failover policy in config
- contract tests run against both

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Provider choice to be agreed before starting.

## Dependencies

- AGT-001: Build the LLM adapter with routing and timeouts

## Acceptance criteria

- [ ] With the primary disabled, extraction and planning still work through the secondary

## Testing requirements

- Integration

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
