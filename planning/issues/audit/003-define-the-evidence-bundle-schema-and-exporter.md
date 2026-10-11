# [AUDIT] Define the evidence bundle schema and exporter

| Field | Value |
|---|---|
| **ID** | AUD-003 |
| **Epic** | M15 · Audit & Evidence |
| **Module** | `audit` ([spec](../../../docs/modules/audit/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | M (~1 day) |
| **Area** | backend |
| **Status** | Ready for Review |
| **Traces to** | FR-913, BR-095 |
| **Blocks** | DEV-007 |
| **Submission cut** | A |

## Context

This ticket belongs to the epic **Audit & Evidence**. It supports:

- F-121: Evidence bundle export

Problem behind this work (from `docs/FEATURES.md`):

- **F-121** solves: Competition "execution evidence" and enterprise audit.

## Objective

One file that proves what happened for a request or scenario.

## Scope

- JSON schema evidence-bundle.v1 per GA p.39 fields
- exporter joining approvals, plan, validations, ai_calls, attestation, operations, transactions, verifications
- fixture labels
- GET /requests/{id}/evidence

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Never include secrets or raw signatures that could be reused beyond what is already on-chain.

## Dependencies

- AUD-001: Implement the hash-chained audit log
- EXE-008: Sequence steps with re-read and re-validation

## Acceptance criteria

- [ ] A paid request exports a bundle that validates against the schema
- [ ] Every tx hash in it resolves on the chain
- [ ] A blocked request exports with validator logs and no fabricated hash

## Testing requirements

- Integration

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
