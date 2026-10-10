# [RECOVERY] Resolve unknown operations from chain evidence

| Field | Value |
|---|---|
| **ID** | RCV-002 |
| **Epic** | M12 · Recovery & Exceptions |
| **Module** | `recovery` ([spec](../../../docs/modules/recovery/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | M (~1 day) |
| **Area** | backend |
| **Status** | Ready for Review |
| **Traces to** | BR-060–061 |
| **Blocks** | RCV-007 |

## Context

This ticket belongs to the epic **Recovery & Exceptions**. It supports:

- F-080: Unknown-state recovery (no double pay)

Problem behind this work (from `docs/FEATURES.md`):

- **F-080** solves: Double payment risk.

## Objective

Decide the true outcome of an uncertain operation without guessing.

## Scope

- Resolution order: receipt by tx hash, then account nonce, then module used(stepId)/used(requestId)
- outcomes: Confirmed, Reverted, still Pending, or safe to submit with the same ids
- escalate to review after a threshold

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

No AI involvement.

## Dependencies

- RCV-001: Scan in-flight operations at startup
- CHR-003: Implement the transaction tracker

## Acceptance criteria

- [ ] If the chain shows the step used, the operation becomes Confirmed without resubmission
- [ ] A never-broadcast operation is resubmitted with the same step id

## Testing requirements

- Integration with fault injection

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
