# [DEVEX] Add CI workflow for contracts

| Field | Value |
|---|---|
| **ID** | DEV-004 |
| **Epic** | M19 · Developer Experience & Quality |
| **Module** | `devex` ([spec](../../../docs/modules/devex/README.md)) |
| **Phase / Priority** | M1 / P1 |
| **Size** | S (≤ 0.5 day) |
| **Area** | infrastructure |
| **Status** | Ready for Review |
| **Traces to** | FR-928, NFR-SEC-02, NFR-SEC-07 |
| **Blocks** | — |

## Context

This ticket belongs to the epic **Developer Experience & Quality**. It supports:

- F-161: CI pipeline
- F-163: Security test suites

Problem behind this work (from `docs/FEATURES.md`):

- **F-161** solves: Quality gate.
- **F-163** solves: Evidence for the Security criterion.

## Objective

Every PR that touches contracts runs build, tests, fuzz, invariants and static analysis.

## Scope

- .github/workflows/contracts.yml: forge fmt --check, forge build, forge test (fuzz runs 10k on main, 1k on PR), Slither
- upload Slither report as artifact

## Out of scope

Fixing Slither findings (SC-015).

## Technical notes

Pin the Foundry version. Path filter on contracts/**.

## Dependencies

- SC-001: Set up the Foundry project with pinned dependencies

## Acceptance criteria

- [ ] Workflow triggers on changes under contracts/
- [ ] Fuzz run count is configurable by env
- [ ] Slither report is downloadable from the run

## Testing requirements

- CI: run on a PR that adds a failing invariant and confirm it fails

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
