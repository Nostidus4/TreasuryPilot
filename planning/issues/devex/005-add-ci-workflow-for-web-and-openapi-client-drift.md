# [DEVEX] Add CI workflow for web and OpenAPI client drift

| Field | Value |
|---|---|
| **ID** | DEV-005 |
| **Epic** | M19 · Developer Experience & Quality |
| **Module** | `devex` ([spec](../../../docs/modules/devex/README.md)) |
| **Phase / Priority** | M1 / P1 |
| **Size** | S (≤ 0.5 day) |
| **Area** | infrastructure |
| **Status** | Ready for Review |
| **Traces to** | FR-928, ADR-010 |
| **Blocks** | — |
| **Submission cut** | After submission |

## Context

This ticket belongs to the epic **Developer Experience & Quality**. It supports:

- F-161: CI pipeline

Problem behind this work (from `docs/FEATURES.md`):

- **F-161** solves: Quality gate.

## Objective

Every PR builds the web app and proves the generated API client is up to date.

## Scope

- .github/workflows/web.yml: pnpm install, eslint, tsc --noEmit, vite build
- job that regenerates the OpenAPI client and fails on diff

## Out of scope

E2E tests (WEB-023).

## Technical notes

`make openapi` exports the schema from FastAPI without starting the server.

## Dependencies

- WEB-001: Create the web app shell

## Acceptance criteria

- [ ] Build fails on a type error
- [ ] A stale generated client fails the drift check

## Testing requirements

- CI: change an API model without regenerating and confirm the check fails

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
