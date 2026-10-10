# [DEVEX] Initialize monorepo skeleton

| Field | Value |
|---|---|
| **ID** | DEV-001 |
| **Epic** | M19 · Developer Experience & Quality |
| **Module** | `devex` ([spec](../../../docs/modules/devex/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | M (~1 day) |
| **Area** | infrastructure |
| **Status** | Ready for Review |
| **Traces to** | ADR-001 |
| **Blocks** | DEV-002, DEV-003, DEV-011, SC-001, ENG-001, CMP-003, WEB-001 |

## Context

This ticket belongs to the epic **Developer Experience & Quality**. It supports:

- F-160: One-command local environment & seeded scenarios

Problem behind this work (from `docs/FEATURES.md`):

- **F-160** solves: Reproducibility for judges and developers.

## Objective

Create the folder layout and tooling so every other ticket has a place to land.

## Scope

- Create apps/, services/{api,worker,signer}, packages/py-core, contracts/, infra/, evals/, scenarios/, deployments/
- uv workspace (root pyproject.toml) with empty packages that import
- pnpm workspace with empty apps/web
- Makefile with placeholder targets (dev, test, lint)
- pre-commit with ruff, prettier, forge fmt, gitleaks

## Out of scope

Any business code; CI workflows (DEV-003..005).

## Technical notes

Follow docs/REPOSITORY_STRUCTURE.md exactly. Python 3.12. Pin tool versions.

## Dependencies

- None

## Acceptance criteria

- [ ] `uv sync` succeeds on a fresh clone
- [ ] `pnpm install` succeeds
- [ ] `pre-commit run --all-files` passes
- [ ] Folder tree matches REPOSITORY_STRUCTURE.md

## Testing requirements

- Unit: a trivial import test per Python package

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
