# [WEB] Write the Playwright end-to-end happy path

| Field | Value |
|---|---|
| **ID** | WEB-023 |
| **Epic** | M16 · Web Application |
| **Module** | `web` ([spec](../../../docs/modules/web/README.md)) |
| **Phase / Priority** | M1 / P1 |
| **Size** | M (~1 day) |
| **Area** | frontend |
| **Status** | Ready for Review |
| **Traces to** | — |
| **Blocks** | — |
| **Submission cut** | After submission |

## Context

This ticket belongs to the epic **Web Application**. It supports:

- F-161: CI pipeline

Problem behind this work (from `docs/FEATURES.md`):

- **F-161** solves: Quality gate.

## Objective

One automated proof that the whole product works.

## Scope

- Playwright test on the local stack with a mock wallet: create request → approve → auto plan → paid → matched

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- WEB-012: Build the live execution timeline

## Acceptance criteria

- [ ] The test passes in CI on Anvil

## Testing requirements

- E2E

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
