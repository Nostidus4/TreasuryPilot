# [EXECUTION] Implement the executor with outbox semantics

| Field | Value |
|---|---|
| **ID** | EXE-007 |
| **Epic** | M10 · Orchestration & Execution |
| **Module** | `execution` ([spec](../../../docs/modules/execution/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | M (~1 day) |
| **Area** | backend |
| **Status** | Ready for Review |
| **Traces to** | BR-060–061, FR-505–506 |
| **Blocks** | EXE-008, EXE-010, RCV-001, RCV-005 |
| **Submission cut** | A |

## Context

This ticket belongs to the epic **Orchestration & Execution**. It supports:

- F-061: Sequential executor & signer service
- F-062: REFILL execution
- F-063: PAY execution

Problem behind this work (from `docs/FEATURES.md`):

- **F-061** solves: Key isolation from the LLM and the API process. Ordering safety.
- **F-062** solves: P1.
- **F-063** solves: The core job.

## Objective

Each step is recorded before it is signed and its transaction hash is saved before anything else happens.

## Scope

- For each plan step: insert operation NotSubmitted in the same DB transaction as the step state
- call the signer
- persist tx hash and nonce
- hand off to the tracker
- idempotent re-entry

## Out of scope

Sequencing between steps (EXE-008).

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- EXE-005: Build the signer service
- EXE-001: Create operations (outbox), transactions and gas ledger schema

## Acceptance criteria

- [ ] A crash between signer response and DB write is recoverable by step id lookup
- [ ] Re-running the task for a Submitted operation does not call the signer again

## Testing requirements

- Integration with fault injection

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
