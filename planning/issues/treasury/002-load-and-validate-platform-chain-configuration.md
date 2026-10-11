# [TREASURY] Load and validate platform chain configuration

| Field | Value |
|---|---|
| **ID** | TRS-002 |
| **Epic** | M02 · Treasury & Chain Configuration |
| **Module** | `treasury` ([spec](../../../docs/modules/treasury/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | S (≤ 0.5 day) |
| **Area** | backend |
| **Status** | Ready for Review |
| **Traces to** | FR-925 |
| **Blocks** | TRS-003, CHR-001 |
| **Submission cut** | A |

## Context

This ticket belongs to the epic **Treasury & Chain Configuration**. It supports:

- F-151: Platform configuration (chains, RPC, assets)

Problem behind this work (from `docs/FEATURES.md`):

- **F-151** solves: Removes hard-coded network values.

## Objective

Chains, RPC endpoints, confirmations and deployments come from a validated config, not from code.

## Scope

- Pydantic settings reading config and deployments/<chainId>.json
- sync into chains/deployments tables at startup
- fail fast on invalid chain id, missing RPC or missing module code hash

## Out of scope

Admin UI (Later).

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- TRS-001: Create treasury and chain schema

## Acceptance criteria

- [ ] Startup fails with a clear message on invalid config
- [ ] At least two RPC URLs per enabled chain are required

## Testing requirements

- Unit: config validation tests

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
