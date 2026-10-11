# [AGENT] Draft exception requests with a numeric post-check

| Field | Value |
|---|---|
| **ID** | AGT-011 |
| **Epic** | M09 · AI Agent |
| **Module** | `agent` ([spec](../../../docs/modules/agent/README.md)) |
| **Phase / Priority** | M1 / P1 |
| **Size** | S (≤ 0.5 day) |
| **Area** | ai |
| **Status** | Ready for Assignment |
| **Traces to** | FR-414, BR-043 |
| **Blocks** | — |
| **Submission cut** | B |

## Context

This ticket belongs to the epic **AI Agent**. It supports:

- F-057: AI exception-request drafting

Problem behind this work (from `docs/FEATURES.md`):

- **F-057** solves: Speeds up Owner decisions and makes them informed.

## Objective

Give the Owner a clear, correct justification for an over-cap payment.

## Scope

- ExceptionDraft schema {summary, reasons[], alternatives[]}
- numbers injected from the engine
- post-check that every number in the text matches engine values
- template fallback

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- AGT-001: Build the LLM adapter with routing and timeouts
- MDT-006: Implement one-time exception requests and owner grant transactions

## Acceptance criteria

- [ ] A draft whose numbers differ from the engine is discarded and the template is used
- [ ] The draft is attached to the exception record

## Testing requirements

- Unit

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
