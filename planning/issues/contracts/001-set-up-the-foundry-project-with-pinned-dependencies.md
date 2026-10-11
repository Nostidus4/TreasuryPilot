# [CONTRACTS] Set up the Foundry project with pinned dependencies

| Field | Value |
|---|---|
| **ID** | SC-001 |
| **Epic** | M04 · Smart Contracts |
| **Module** | `contracts` ([spec](../../../docs/modules/contracts/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | S (≤ 0.5 day) |
| **Area** | contracts |
| **Status** | Ready for Review |
| **Traces to** | ADR-002, NFR-SEC-08 |
| **Blocks** | DEV-004, SC-002 |
| **Submission cut** | A |

## Context

This ticket belongs to the epic **Smart Contracts**. It supports:

- F-163: Security test suites

Problem behind this work (from `docs/FEATURES.md`):

- **F-163** solves: Evidence for the Security criterion.

## Objective

A compiling contracts workspace with Safe and OpenZeppelin pinned, and a test stablecoin.

## Scope

- foundry.toml with pinned solc
- install Safe contracts and OpenZeppelin at exact commits
- TestUSDC (6 decimals, mint for tests, name clearly marked TEST)
- helper to deploy a 1-of-1 Safe in tests

## Out of scope

Module logic.

## Technical notes

Record exact versions and commits in contracts/README.md.

## Dependencies

- DEV-001: Initialize monorepo skeleton

## Acceptance criteria

- [ ] `forge build` succeeds
- [ ] A test deploys a Safe and TestUSDC and transfers tokens through the Safe
- [ ] Dependency commits are documented

## Testing requirements

- Unit: Safe deployment helper test

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
