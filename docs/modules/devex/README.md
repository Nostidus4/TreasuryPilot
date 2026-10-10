# M19 · DevEx & Quality

**Status:** Draft for gate G2 · **Path:** `docs/modules/devex/`

## Purpose
Compose environment, CI, scenario runner + demo runbook, security suites, reliability harness.

## Features
F-160, F-161, F-162, F-163, F-164

## Inputs
Repo code.

## Outputs
Running stacks, CI results, reports in `docs/evidence/`.

## APIs
CLI: `make dev`, `scenario run <name>`, `make bench`, `make reliability`.

## Data model
—

## Dependencies
All.

## Security concerns
Scenario tooling refuses mainnet (BR-095); secrets scanning in CI.

## Failure scenarios
Flaky testnet → retries reported, never hidden.

## Open questions
None.
