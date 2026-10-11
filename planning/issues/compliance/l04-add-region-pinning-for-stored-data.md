# [COMPLIANCE] Add region pinning for stored data

| Field | Value |
|---|---|
| **ID** | CMP-L04 |
| **Epic** | M14 · Compliance |
| **Module** | `compliance` ([spec](../../../docs/modules/compliance/README.md)) |
| **Phase / Priority** | Later / - |
| **Size** | M (~1 day) |
| **Area** | backend |
| **Status** | Accepted |
| **Traces to** | FR-910 |
| **Blocks** | — |
| **Submission cut** | After submission |

> **Phase: Later.** This ticket is intentionally coarser than M1 tickets. It must be re-estimated and split before it is scheduled.

## Context

This ticket belongs to the epic **Compliance**. It supports:

- F-114: Data retention & residency policies

Problem behind this work (from `docs/FEATURES.md`):

- **F-114** solves: GDPR/PDPL-type obligations.

## Objective

Data residency.

## Scope

- Per-org region for DB and object storage

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- CMP-L03: Add retention and deletion workflows

## Acceptance criteria

- [ ] Data for a pinned org is stored only in its region

## Testing requirements

- Infra test

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
