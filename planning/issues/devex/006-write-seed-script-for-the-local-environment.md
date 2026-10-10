# [DEVEX] Write seed script for the local environment

| Field | Value |
|---|---|
| **ID** | DEV-006 |
| **Epic** | M19 · Developer Experience & Quality |
| **Module** | `devex` ([spec](../../../docs/modules/devex/README.md)) |
| **Phase / Priority** | M1 / P1 |
| **Size** | M (~1 day) |
| **Area** | infrastructure |
| **Status** | Ready for Review |
| **Traces to** | FR-927 |
| **Blocks** | DEV-007 |

## Context

This ticket belongs to the epic **Developer Experience & Quality**. It supports:

- F-160: One-command local environment & seeded scenarios

Problem behind this work (from `docs/FEATURES.md`):

- **F-160** solves: Reproducibility for judges and developers.

## Objective

After `make seed`, a developer or judge has a working demo dataset.

## Scope

- Deploy contracts and 3 Safes to Anvil
- create org, users with roles, treasury, active mandate, 3 payees (one still cooling), 5 invoices in different states
- print login links and addresses

## Out of scope

Testnet seeding (part of DEV-010).

## Technical notes

Idempotent: running twice does not duplicate data. Uses the public API where possible.

## Dependencies

- SC-016: Write deployment scripts and the deployments manifest
- TRS-004: Implement treasury creation with Safe verification
- MDT-003: Implement mandate activation and read-back
- INV-003: Implement manual request creation and editing

## Acceptance criteria

- [ ] `make dev && make seed` yields a usable UI at localhost within 15 minutes on a fresh clone
- [ ] Running `make seed` twice leaves one dataset
- [ ] All seeded assets are labelled TEST

## Testing requirements

- Integration: seed in CI and call GET /orgs/{id}/treasuries/{id}

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
