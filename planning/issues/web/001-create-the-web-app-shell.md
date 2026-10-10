# [WEB] Create the web app shell

| Field | Value |
|---|---|
| **ID** | WEB-001 |
| **Epic** | M16 · Web Application |
| **Module** | `web` ([spec](../../../docs/modules/web/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | M (~1 day) |
| **Area** | frontend |
| **Status** | Ready for Review |
| **Traces to** | ADR-013 |
| **Blocks** | DEV-005, WEB-002, WEB-015 |

## Context

This ticket belongs to the epic **Web Application**. It supports:

- F-130: Treasury dashboard

Problem behind this work (from `docs/FEATURES.md`):

- **F-130** solves: One glance at treasury health.

## Objective

A running React app with routing, styling and a typed API client.

## Scope

- Vite + React + TypeScript
- React Router
- Tailwind + shadcn/ui
- TanStack Query
- OpenAPI client generation script
- auth guard and layout
- error and empty states

## Out of scope

Feature pages.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- DEV-001: Initialize monorepo skeleton

## Acceptance criteria

- [ ] `pnpm dev` serves the shell
- [ ] The generated client compiles
- [ ] Unauthenticated users are redirected to login

## Testing requirements

- Unit: smoke render test

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
