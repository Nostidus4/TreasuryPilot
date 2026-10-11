# [DEVEX] Enforce module boundaries with import-linter

| Field | Value |
|---|---|
| **ID** | DEV-011 |
| **Epic** | M19 · Developer Experience & Quality |
| **Module** | `devex` ([spec](../../../docs/modules/devex/README.md)) |
| **Phase / Priority** | M1 / P1 |
| **Size** | S (≤ 0.5 day) |
| **Area** | infrastructure |
| **Status** | Ready for Review |
| **Traces to** | NFR-MAINT-01, ADR-001 |
| **Blocks** | — |
| **Submission cut** | After submission |

## Context

This ticket belongs to the epic **Developer Experience & Quality**. It supports:

- F-161: CI pipeline

Problem behind this work (from `docs/FEATURES.md`):

- **F-161** solves: Quality gate.

## Objective

py-core stays pure and services do not import each other.

## Scope

- import-linter config: py-core forbids sqlalchemy, httpx, web3, celery, fastapi
- services forbidden from importing each other
- run in CI

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Add the check to DEV-003's workflow.

## Dependencies

- DEV-001: Initialize monorepo skeleton

## Acceptance criteria

- [ ] A PR that imports web3 inside py-core fails CI
- [ ] A PR that imports the api package from the worker fails CI

## Testing requirements

- CI: negative test on a throwaway branch

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
