# [COMPLIANCE] Add retention and deletion workflows

| Field | Value |
|---|---|
| **ID** | CMP-L03 |
| **Epic** | M14 · Compliance |
| **Module** | `compliance` ([spec](../../../docs/modules/compliance/README.md)) |
| **Phase / Priority** | Later / - |
| **Size** | M (~1 day) |
| **Area** | backend |
| **Status** | Accepted |
| **Traces to** | FR-910 |
| **Blocks** | CMP-L04 |
| **Submission cut** | After submission |

> **Phase: Later.** This ticket is intentionally coarser than M1 tickets. It must be re-estimated and split before it is scheduled.

## Context

This ticket belongs to the epic **Compliance**. It supports:

- F-114: Data retention & residency policies

Problem behind this work (from `docs/FEATURES.md`):

- **F-114** solves: GDPR/PDPL-type obligations.

## Objective

Data lifecycle.

## Scope

- Retention config
- deletion job
- legal hold

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- CMP-003: Implement data classification, encryption helpers and log redaction

## Acceptance criteria

- [ ] Deleted records keep only non-personal hashes

## Testing requirements

- Integration

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
