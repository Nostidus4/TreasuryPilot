# [DEVEX] Build the reliability run harness

| Field | Value |
|---|---|
| **ID** | DEV-009 |
| **Epic** | M19 · Developer Experience & Quality |
| **Module** | `devex` ([spec](../../../docs/modules/devex/README.md)) |
| **Phase / Priority** | M1 / P1 |
| **Size** | S (≤ 0.5 day) |
| **Area** | infrastructure |
| **Status** | Ready for Assignment |
| **Traces to** | FR-931, NFR-REL-01 |
| **Blocks** | — |
| **Submission cut** | After submission |

## Context

This ticket belongs to the epic **Developer Experience & Quality**. It supports:

- F-164: Reliability run harness

Problem behind this work (from `docs/FEATURES.md`):

- **F-164** solves: Evidence for the "stable, repeatable" part of Task Completion.

## Objective

Produce the stability numbers judges ask for.

## Scope

- `make reliability`: run demo-main 30 times on Anvil and N times on testnet
- collect completion, median latency per phase, fees, failure categories
- write docs/evidence/reliability-<date>.md

## Out of scope

Fixing the failures it finds.

## Technical notes

Failures are categorized, never dropped from the report.

## Dependencies

- DEV-007: Build scenario runner CLI

## Acceptance criteria

- [ ] Report shows 30 local runs with a completion percentage
- [ ] Testnet run count is a parameter
- [ ] Failed runs appear in the report with a category

## Testing requirements

- Integration: 3-run smoke in CI

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
