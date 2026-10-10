# [EXECUTION] Set up Celery with core and ai queues

| Field | Value |
|---|---|
| **ID** | EXE-002 |
| **Epic** | M10 · Orchestration & Execution |
| **Module** | `execution` ([spec](../../../docs/modules/execution/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | M (~1 day) |
| **Area** | backend |
| **Status** | Ready for Review |
| **Traces to** | ADR-007 |
| **Blocks** | EXE-003, EXE-L04, AGT-001 |

## Context

This ticket belongs to the epic **Orchestration & Execution**. It supports:

- F-060: Deadline-driven autonomous trigger
- F-061: Sequential executor & signer service

Problem behind this work (from `docs/FEATURES.md`):

- **F-060** solves: Makes the agent a financial participant, not a button.
- **F-061** solves: Key isolation from the LLM and the API process. Ordering safety.

## Objective

A safe job runtime where LLM tasks hold no signing secrets.

## Scope

- Celery app with Redis broker
- queues core and ai, two compose services (worker, worker-ai) and beat
- base task: idempotency helper, correlation ids, acks_late, reject on worker lost
- per-treasury pg_advisory_xact_lock helper

## Out of scope

Business tasks.

## Technical notes

worker-ai gets only the LLM key and limited DB credentials.

## Dependencies

- DEV-002: Create Docker Compose stack (local profile)

## Acceptance criteria

- [ ] Two tasks for the same treasury never run their critical section concurrently
- [ ] A killed worker's task is redelivered
- [ ] worker-ai has no access to the attestation key or signer secret

## Testing requirements

- Integration: lock contention test

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
