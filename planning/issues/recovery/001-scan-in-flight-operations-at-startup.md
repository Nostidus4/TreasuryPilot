# [RECOVERY] Scan in-flight operations at startup

| Field | Value |
|---|---|
| **ID** | RCV-001 |
| **Epic** | M12 · Recovery & Exceptions |
| **Module** | `recovery` ([spec](../../../docs/modules/recovery/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | S (≤ 0.5 day) |
| **Area** | backend |
| **Status** | Ready for Review |
| **Traces to** | BR-060, FR-701–702 |
| **Blocks** | RCV-002 |

## Context

This ticket belongs to the epic **Recovery & Exceptions**. It supports:

- F-080: Unknown-state recovery (no double pay)

Problem behind this work (from `docs/FEATURES.md`):

- **F-080** solves: Double payment risk.

## Objective

Nothing new happens until old work is understood.

## Scope

- On worker start and periodically: load operations in NotSubmitted, Submitted, Pending, Unknown
- enqueue resolution
- flag treasuries as blocked while any remain

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- EXE-007: Implement the executor with outbox semantics

## Acceptance criteria

- [ ] A treasury with an Unknown operation is skipped by the trigger
- [ ] The scan runs on every worker start

## Testing requirements

- Integration

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
