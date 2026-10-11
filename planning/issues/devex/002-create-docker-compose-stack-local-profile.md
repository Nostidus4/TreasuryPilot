# [DEVEX] Create Docker Compose stack (local profile)

| Field | Value |
|---|---|
| **ID** | DEV-002 |
| **Epic** | M19 · Developer Experience & Quality |
| **Module** | `devex` ([spec](../../../docs/modules/devex/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | M (~1 day) |
| **Area** | infrastructure |
| **Status** | Ready for Review |
| **Traces to** | ADR-008, FR-927 |
| **Blocks** | DEV-010, IDN-001, EXE-002 |
| **Submission cut** | A |

## Context

This ticket belongs to the epic **Developer Experience & Quality**. It supports:

- F-160: One-command local environment & seeded scenarios

Problem behind this work (from `docs/FEATURES.md`):

- **F-160** solves: Reproducibility for judges and developers.

## Objective

One command starts the infrastructure services needed for development.

## Scope

- infra/compose.yaml with postgres 16, redis 7, minio, anvil
- healthchecks and named volumes
- infra/env/.env.example (names only)
- `make dev` and `make down`

## Out of scope

Application containers (added by their own tickets); testnet profile (DEV-010).

## Technical notes

Anvil with a fixed mnemonic and chain id 31337. MinIO bucket created by an init job.

## Dependencies

- DEV-001: Initialize monorepo skeleton

## Acceptance criteria

- [ ] `make dev` brings all four services to healthy
- [ ] Postgres, Redis, MinIO and Anvil reachable from the host
- [ ] No secret values committed

## Testing requirements

- Integration: a smoke script that checks each service port

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
