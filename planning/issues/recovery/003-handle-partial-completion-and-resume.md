# [RECOVERY] Handle partial completion and resume

| Field | Value |
|---|---|
| **ID** | RCV-003 |
| **Epic** | M12 · Recovery & Exceptions |
| **Module** | `recovery` ([spec](../../../docs/modules/recovery/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | S (≤ 0.5 day) |
| **Area** | backend |
| **Status** | Ready for Review |
| **Traces to** | BR-054, FR-703 |
| **Blocks** | — |
| **Submission cut** | After submission |

## Context

This ticket belongs to the epic **Recovery & Exceptions**. It supports:

- F-081: Partial-completion handling

Problem behind this work (from `docs/FEATURES.md`):

- **F-081** solves: Non-atomic multi-transaction plans (BR-054).

## Objective

A blocked later step never undoes or repeats an earlier one.

## Scope

- Plan status PartiallyCompleted
- resume runs only unfinished steps after re-validation
- cancel leaves funds where they are and reports it

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- EXE-008: Sequence steps with re-read and re-validation

## Acceptance criteria

- [ ] After refill succeeded and pay was blocked, a retry sends only the pay
- [ ] No second refill occurs

## Testing requirements

- Integration: AT-07

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
