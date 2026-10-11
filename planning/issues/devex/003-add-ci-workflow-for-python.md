# [DEVEX] Add CI workflow for Python

| Field | Value |
|---|---|
| **ID** | DEV-003 |
| **Epic** | M19 · Developer Experience & Quality |
| **Module** | `devex` ([spec](../../../docs/modules/devex/README.md)) |
| **Phase / Priority** | M1 / P1 |
| **Size** | S (≤ 0.5 day) |
| **Area** | infrastructure |
| **Status** | Ready for Assignment |
| **Traces to** | FR-928 |
| **Blocks** | DEV-012 |
| **Submission cut** | A |

## Context

This ticket belongs to the epic **Developer Experience & Quality**. It supports:

- F-161: CI pipeline

Problem behind this work (from `docs/FEATURES.md`):

- **F-161** solves: Quality gate.

## Objective

Every PR runs Python lint, type-check and tests.

## Scope

- .github/workflows/ci.yml: uv sync, ruff check, ruff format --check, mypy (strict for py-core), pytest with coverage
- gitleaks job
- cache uv

## Out of scope

Contracts and web workflows.

## Technical notes

Fail the job if py-core coverage < 85% (NFR-MAINT-03) once ENG tickets land; start as a warning.

## Dependencies

- DEV-001: Initialize monorepo skeleton

## Acceptance criteria

- [ ] Workflow runs on pull_request and push to main
- [ ] A failing test fails the check
- [ ] gitleaks blocks a planted fake secret in a test branch

## Testing requirements

- CI: a deliberate failing test in a throwaway PR to verify the gate

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
