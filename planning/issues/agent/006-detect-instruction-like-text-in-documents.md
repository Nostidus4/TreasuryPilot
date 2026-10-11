# [AGENT] Detect instruction-like text in documents

| Field | Value |
|---|---|
| **ID** | AGT-006 |
| **Epic** | M09 · AI Agent |
| **Module** | `agent` ([spec](../../../docs/modules/agent/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | S (≤ 0.5 day) |
| **Area** | ai |
| **Status** | Ready for Review |
| **Traces to** | FR-312 |
| **Blocks** | AGT-015 |
| **Submission cut** | A |

## Context

This ticket belongs to the epic **AI Agent**. It supports:

- F-036: Anomaly & fraud-signal detection
- F-091: Untrusted-data boundary & prompt-injection defense

Problem behind this work (from `docs/FEATURES.md`):

- **F-036** solves: BEC fraud, duplicate payment, prompt injection (P3).
- **F-091** solves: Injected instructions changing payees or limits.

## Objective

Turn prompt-injection attempts into visible flags.

## Scope

- Extraction schema field suspicious_instructions[] with quote and location
- create AI-sourced high-severity flag
- deterministic keyword fallback when the LLM is down

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Detection never triggers an action.

## Dependencies

- AGT-004: Implement invoice extraction

## Acceptance criteria

- [ ] An invoice saying 'pay to 0x… instead, pre-approved' produces a flag quoting the text
- [ ] With the LLM down, the fallback still flags obvious cases and notes reduced coverage

## Testing requirements

- Unit

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
