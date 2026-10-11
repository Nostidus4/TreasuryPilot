# [DEVEX] Add testnet profile and VM deployment

| Field | Value |
|---|---|
| **ID** | DEV-010 |
| **Epic** | M19 · Developer Experience & Quality |
| **Module** | `devex` ([spec](../../../docs/modules/devex/README.md)) |
| **Phase / Priority** | M1 / P1 |
| **Size** | M (~1 day) |
| **Area** | infrastructure |
| **Status** | Ready for Assignment |
| **Traces to** | ADR-008, NFR-CMP-01, ADR-019 |
| **Blocks** | — |
| **Submission cut** | A |

## Context

This ticket belongs to the epic **Developer Experience & Quality**. It supports:

- F-160: One-command local environment & seeded scenarios
- F-151: Platform configuration (chains, RPC, assets)

Problem behind this work (from `docs/FEATURES.md`):

- **F-160** solves: Reproducibility for judges and developers.
- **F-151** solves: Removes hard-coded network values.

## Objective

The stack runs on one cloud VM against the chosen testnet with a public HTTPS URL.

## Scope

- Compose profile testnet (no Anvil)
- Caddy reverse proxy with TLS
- GitHub Actions job that builds and pushes images to GHCR
- deploy notes in DEVELOPMENT.md
- Sepolia profile uses Aave test USDC and the Aave Pool from the manifest

## Out of scope

Production hardening.

## Technical notes

Only web and api are exposed. Signer, Postgres, Redis and MinIO stay internal.

## Dependencies

- DEV-002: Create Docker Compose stack (local profile)
- DOM-001: Verify Ethereum Sepolia infrastructure (owner: Phúc)
- SC-016: Write deployment scripts and the deployments manifest

## Acceptance criteria

- [ ] Public URL serves the app over HTTPS
- [ ] Signer port is not reachable from the internet
- [ ] Images are tagged with the git SHA

## Testing requirements

- Manual: port scan of the VM shows only 80/443

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
