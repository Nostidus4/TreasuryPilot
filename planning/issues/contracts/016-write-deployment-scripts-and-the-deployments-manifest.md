# [CONTRACTS] Write deployment scripts and the deployments manifest

| Field | Value |
|---|---|
| **ID** | SC-016 |
| **Epic** | M04 · Smart Contracts |
| **Module** | `contracts` ([spec](../../../docs/modules/contracts/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | M (~1 day) |
| **Area** | contracts |
| **Status** | Ready for Review |
| **Traces to** | FR-925, ADR-012 |
| **Blocks** | DEV-006, DEV-010, TRS-006, CHR-005, EXE-005 |

## Context

This ticket belongs to the epic **Smart Contracts**. It supports:

- F-151: Platform configuration (chains, RPC, assets)

Problem behind this work (from `docs/FEATURES.md`):

- **F-151** solves: Removes hard-coded network values.

## Objective

Repeatable deployment to Anvil and the chosen testnet, with addresses recorded.

## Scope

- forge script to deploy TestUSDC (local), the module, and enable it on three Safes
- write deployments/<chainId>.json with addresses and code hashes
- verify on the explorer for testnet

## Out of scope

Chain choice (DOM-001).

## Technical notes

Local deployment must not depend on DOM-001; testnet deployment does.

## Dependencies

- SC-010: Implement pause, resume, revoke and guardian

## Acceptance criteria

- [ ] `make deploy-local` produces deployments/31337.json
- [ ] The manifest contains module, token and Safe addresses plus code hashes
- [ ] Testnet deploy is a parameterized run of the same script

## Testing requirements

- Integration: deploy on Anvil in CI

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
