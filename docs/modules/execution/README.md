# M10 · Orchestration & Execution

**Status:** Draft for gate G2 · **Path:** `docs/modules/execution/`

## Purpose
Deadline-driven trigger, per-treasury sequencing, outbox, executor client, signer service, gas management, swap execution (P2).

## Features
F-060, F-061, F-062, F-063, F-064, F-065 (Later), F-066, F-067 (Later)

## Inputs
Approved requests, attested plans, schedules (Celery beat).

## Outputs
Operations, transactions, executor gas alerts.

## APIs
`/treasuries/{t}/run-now`, `/operations/{id}`; internal signer `/sign-and-send` (API_SPEC §5, internal).

## Data model
operations, transactions, gas_ledger

## Dependencies
M06, M07, M08, M09, M12, M04, Redis/Celery.

## Security concerns
Key isolation (signer); payload mismatch (signer re-checks the attestation); duplicate delivery (idempotent tasks + unique step_id); concurrency (advisory lock).

## Failure scenarios
Worker crash mid-flight → M12 recovery. Signer down → operation stays NotSubmitted, retried. Simulation revert → no broadcast, review item.

## Open questions
None.
