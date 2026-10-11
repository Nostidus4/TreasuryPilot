# [DEVEX] Add the deployment config gate to CI

| Field | Value |
|---|---|
| **ID** | DEV-012 |
| **Epic** | M19 · Developer Experience & Quality |
| **Module** | `devex` ([spec](../../../docs/modules/devex/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | S (≤ 0.5 day) |
| **Area** | infrastructure |
| **Status** | Ready for Assignment |
| **Traces to** | ADR-019, V3-14 |
| **Blocks** | — |
| **Submission cut** | A |

## Context

This ticket belongs to the epic **Developer Experience & Quality**. It supports:

- F-151: Platform configuration (chains, RPC, assets)

Problem behind this work (from `docs/FEATURES.md`):

- **F-151** solves: Removes hard-coded network values.

## Objective

Never deploy or demo against the wrong chain, token or Aave market.

## Scope

- make config-check comparing deployments/<chainId>.json with on-chain chain id, token decimals, Aave Pool → aToken mapping
- run in CI and before the demo

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- SC-016: Write deployment scripts and the deployments manifest
- DEV-003: Add CI workflow for Python

## Acceptance criteria

- [ ] A wrong decimals value or aToken mapping fails CI
- [ ] The check passes for the Sepolia manifest

## Testing requirements

- CI

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
