# [AUDIT] Implement the hash-chained audit log

| Field | Value |
|---|---|
| **ID** | AUD-001 |
| **Epic** | M15 · Audit & Evidence |
| **Module** | `audit` ([spec](../../../docs/modules/audit/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | M (~1 day) |
| **Area** | backend |
| **Status** | Ready for Assignment |
| **Traces to** | BR-097, FR-911, NFR-AUD-01–02, M15-D1 |
| **Blocks** | AUD-002, AUD-003, OBS-004 |
| **Submission cut** | A |

## Context

This ticket belongs to the epic **Audit & Evidence**. It supports:

- F-120: Hash-chained audit log & on-chain events

Problem behind this work (from `docs/FEATURES.md`):

- **F-120** solves: Tamper-evident traceability.

## Objective

A tamper-evident record of everything that matters.

## Scope

- audit_log migration with no-update/no-delete trigger
- write(actor, action, entity, data) computing hash from the previous record per org
- helper to write in the caller's transaction
- per-org audit_heads row locked FOR UPDATE to append; canonical JSON (sorted keys, amounts as strings, ISO-8601 UTC) (M15-D1)

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Financial actions call write in the same DB transaction and fail if it fails.

## Dependencies

- IDN-001: Create identity database schema and migrations

## Acceptance criteria

- [ ] Updating or deleting an audit row is rejected by the database
- [ ] Records form a valid chain per org
- [ ] A forced audit failure aborts the financial action

## Testing requirements

- Unit + integration

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
