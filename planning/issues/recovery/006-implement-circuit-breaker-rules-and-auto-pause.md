# [RECOVERY] Implement circuit-breaker rules and auto-pause

| Field | Value |
|---|---|
| **ID** | RCV-006 |
| **Epic** | M12 · Recovery & Exceptions |
| **Module** | `recovery` ([spec](../../../docs/modules/recovery/README.md)) |
| **Phase / Priority** | M1 / P2 |
| **Size** | M (~1 day) |
| **Area** | backend |
| **Status** | Ready for Review |
| **Traces to** | BR-065, FR-222 |
| **Blocks** | — |

## Context

This ticket belongs to the epic **Recovery & Exceptions**. It supports:

- F-027: Circuit breaker (auto-pause)

Problem behind this work (from `docs/FEATURES.md`):

- **F-027** solves: Limits damage from bugs or compromise between human checks.

## Objective

Stop automatically when something looks wrong.

## Scope

- Rule evaluation on events: ≥3 contract rejections in 10 minutes, AI plan out of mandate, coverage drop, post-condition discrepancy
- action alert or pause
- circuit_events
- cool-down

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- REC-001: Verify post-conditions after each confirmed step
- MDT-007: Implement pause and resume (backend and transactions)

## Acceptance criteria

- [ ] Three injected rejections pause the treasury within one evaluation cycle
- [ ] Only the Owner can resume

## Testing requirements

- Integration

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
