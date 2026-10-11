# [AUDIT] Add audit read and chain verification

| Field | Value |
|---|---|
| **ID** | AUD-002 |
| **Epic** | M15 · Audit & Evidence |
| **Module** | `audit` ([spec](../../../docs/modules/audit/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | S (≤ 0.5 day) |
| **Area** | backend |
| **Status** | Ready for Review |
| **Traces to** | FR-912 |
| **Blocks** | AUD-L01 |
| **Submission cut** | After submission |

## Context

This ticket belongs to the epic **Audit & Evidence**. It supports:

- F-120: Hash-chained audit log & on-chain events

Problem behind this work (from `docs/FEATURES.md`):

- **F-120** solves: Tamper-evident traceability.

## Objective

Auditors can read the log and prove it is intact.

## Scope

- GET /audit-log with filters
- GET /audit-log/verify
- standalone script for offline verification

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- AUD-001: Implement the hash-chained audit log

## Acceptance criteria

- [ ] Verification reports the first broken record after a manual tamper in a test database

## Testing requirements

- Integration

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
