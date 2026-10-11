# [AGENT] Implement untrusted-content wrapping and sanitization

| Field | Value |
|---|---|
| **ID** | AGT-003 |
| **Epic** | M09 · AI Agent |
| **Module** | `agent` ([spec](../../../docs/modules/agent/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | S (≤ 0.5 day) |
| **Area** | ai |
| **Status** | Ready for Assignment |
| **Traces to** | BR-070, FR-803–804 |
| **Blocks** | AGT-004 |
| **Submission cut** | A |

## Context

This ticket belongs to the epic **AI Agent**. It supports:

- F-091: Untrusted-data boundary & prompt-injection defense

Problem behind this work (from `docs/FEATURES.md`):

- **F-091** solves: Injected instructions changing payees or limits.

## Objective

External text reaches the model only as labelled data.

## Scope

- wrap_untrusted(source, text): tags, source label, length cap, strip active content
- prompt templates with a fixed system section
- lint test that no prompt template interpolates untrusted text outside the wrapper
- secret scanner on prompt inputs

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- AGT-001: Build the LLM adapter with routing and timeouts

## Acceptance criteria

- [ ] A prompt built with unwrapped untrusted text fails the lint test
- [ ] Inputs containing key-like strings are rejected

## Testing requirements

- Unit

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
