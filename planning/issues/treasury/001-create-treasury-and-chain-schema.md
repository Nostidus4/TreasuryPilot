# [TREASURY] Create treasury and chain schema

| Field | Value |
|---|---|
| **ID** | TRS-001 |
| **Epic** | M02 · Treasury & Chain Configuration |
| **Module** | `treasury` ([spec](../../../docs/modules/treasury/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | S (≤ 0.5 day) |
| **Area** | backend |
| **Status** | Ready for Assignment |
| **Traces to** | DATA_MODEL §2.2 |
| **Blocks** | TRS-002, MDT-001 |
| **Submission cut** | A |

## Context

This ticket belongs to the epic **Treasury & Chain Configuration**. It supports:

- F-010: Treasury creation
- F-013: Asset registry

Problem behind this work (from `docs/FEATURES.md`):

- **F-010** solves: Defines the scope of the money the agent manages.
- **F-013** solves: Prevents token impersonation and decimal errors.

## Objective

Tables for chains, assets, deployments, treasuries, wallets and Safe snapshots.

## Scope

- Alembic migration and models
- unique constraints from DATA_MODEL §2.2

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- IDN-001: Create identity database schema and migrations

## Acceptance criteria

- [ ] Migration applies and downgrades cleanly

## Testing requirements

- Integration: migration test

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
