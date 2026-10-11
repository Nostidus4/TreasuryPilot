# [RECOVERY] Automate the crash-recovery test

| Field | Value |
|---|---|
| **ID** | RCV-007 |
| **Epic** | M12 · Recovery & Exceptions |
| **Module** | `recovery` ([spec](../../../docs/modules/recovery/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | S (≤ 0.5 day) |
| **Area** | backend |
| **Status** | Ready for Review |
| **Traces to** | NFR-REL-02 |
| **Blocks** | — |
| **Submission cut** | A |

## Context

This ticket belongs to the epic **Recovery & Exceptions**. It supports:

- F-080: Unknown-state recovery (no double pay)

Problem behind this work (from `docs/FEATURES.md`):

- **F-080** solves: Double payment risk.

## Objective

Prove there is never a double payment when the executor dies mid-flight.

## Scope

- Test harness that kills the worker at randomized points around signer call and DB write, restarts it and asserts exactly one PAY on-chain
- 20 iterations

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

This is demo scene 6 and key evidence.

## Dependencies

- RCV-002: Resolve unknown operations from chain evidence

## Acceptance criteria

- [ ] 20 of 20 iterations end with exactly one payment and a Paid request

## Testing requirements

- Integration: crash suite

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
