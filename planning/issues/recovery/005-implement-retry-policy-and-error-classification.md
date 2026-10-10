# [RECOVERY] Implement retry policy and error classification

| Field | Value |
|---|---|
| **ID** | RCV-005 |
| **Epic** | M12 · Recovery & Exceptions |
| **Module** | `recovery` ([spec](../../../docs/modules/recovery/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | S (≤ 0.5 day) |
| **Area** | backend |
| **Status** | Ready for Review |
| **Traces to** | BR-061, FR-706 |
| **Blocks** | — |

## Context

This ticket belongs to the epic **Recovery & Exceptions**. It supports:

- F-083: Idempotent retry policy

Problem behind this work (from `docs/FEATURES.md`):

- **F-083** solves: Retries that create new obligations or evade dedup.

## Objective

Transient errors are retried safely; everything else stops.

## Scope

- Classifier: retryable (RPC, timeout before broadcast, nonce too low, underpriced) vs terminal
- exponential backoff with max attempts
- ids never regenerated

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- EXE-007: Implement the executor with outbox semantics

## Acceptance criteria

- [ ] A 503 from the RPC is retried and succeeds
- [ ] After max attempts a review item is created
- [ ] Ids are identical across attempts

## Testing requirements

- Unit + integration

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
